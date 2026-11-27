"""'말로 검색' — 예: "교수님이 보낸 기말 프로젝트 공지 찾아줘"

1단계(내 컴퓨터): 제목·키워드·요약·원래 이름을 글자 조각(2글자 단위)으로 비교해 후보를 고른다.
2단계(Gemini, 키가 있을 때): 후보 목록에서 질문에 맞는 파일을 골라 순서를 정하고 한 줄 답을 쓴다.
   민감 파일은 2단계로 보내지 않는다(내 컴퓨터 점수로만 보여 줌).
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import analyzer
from .config import settings
from .db import FileRecord

log = logging.getLogger(__name__)

LONG_JOSA = ("에서", "으로", "이랑", "한테", "까지", "부터", "에게")
SHORT_JOSA = ("은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만", "랑")
STOP = {"찾아줘", "찾아", "찾기", "찾고", "파일", "좀", "보여줘", "줘", "어디", "있어", "있는", "있던", "거", "것",
        "그", "관련", "내", "나", "저", "자료", "보낸", "받은", "했던", "그거"}


def tokens(query: str) -> list[str]:
    """검색어를 단어로 나눈다. 두 글자 이상 조사(에서·으로…)는 떼고, 한 글자 조사는 variants()에서 처리한다."""
    out = []
    for word in re.findall(r"[0-9A-Za-z가-힣]+", query.lower()):
        for j in LONG_JOSA:
            if len(word) > len(j) + 1 and word.endswith(j):
                word = word[: -len(j)]
                break
        if word and word not in STOP:
            out.append(word)
    return out


def variants(word: str) -> list[str]:
    """'교수님이' → ['교수님이', '교수님'], '와이파이' → ['와이파이', '와이파'] (둘 중 더 잘 맞는 쪽을 쓴다)."""
    forms = [word]
    for j in SHORT_JOSA:
        if len(word) > 2 and word.endswith(j):
            forms.append(word[:-1])
            break
    return forms


def _bigrams(text: str) -> set[str]:
    s = re.sub(r"\s+", "", text.lower())
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


FIELD_WEIGHTS = (("title", 3.0), ("keywords", 2.5), ("course", 2.0), ("category", 1.5),
                 ("summary", 1.5), ("original_name", 1.0), ("path_rel", 1.0), ("excerpt", 0.5))


def keyword_score(toks: list[str], rec: FileRecord) -> float:
    fields = []
    for name, weight in FIELD_WEIGHTS:
        value = getattr(rec, name)
        if isinstance(value, list):
            value = " ".join(value)
        if value:
            low = value.lower()
            fields.append((low, re.sub(r"\s+", "", low), weight))
    total = 0.0
    for word in toks:
        best = 0.0
        for tok in variants(word):
            tb = _bigrams(tok)
            for low, compact, weight in fields:
                if tok in compact or tok in low:
                    s = 1.0
                else:
                    overlap = len(tb & _bigrams(compact)) / len(tb) if tb else 0.0
                    s = overlap if overlap >= 0.5 else 0.0
                best = max(best, s * weight)
        total += best
    return total


@dataclass
class Hit:
    record: FileRecord
    score: float
    reason: str


class _Pick(BaseModel):
    id: int
    reason: str = ""


class _SearchAnswer(BaseModel):
    answer: str
    results: list[_Pick]


SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Korean, 1-2 sentences"},
        "results": {"type": "array", "maxItems": 5, "items": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "reason": {"type": "string", "description": "Korean, 1 sentence"}},
            "required": ["id", "reason"]}},
    },
    "required": ["answer", "results"],
}

SEARCH_PROMPT = """너는 내 컴퓨터 파일을 찾아 주는 검색 비서다.
사용자의 질문에 맞는 파일을 후보 목록에서만 골라 관련이 높은 순서로 최대 5개 답한다.
- 후보에 없는 id를 만들지 않는다.
- 맞는 파일이 없으면 results를 빈 배열로 두고 answer에 그렇게 말한다.
- answer는 한국어 1~2문장, reason은 왜 그 파일인지 한국어 한 문장."""


def _describe(rec: FileRecord) -> str:
    kw = ", ".join(rec.keywords or [])
    return (f"id={rec.id} | 제목: {rec.title} | 위치: {rec.path_rel} | 분류: {rec.category} {rec.course} | "
            f"날짜: {rec.date} | 요약: {rec.summary} | 키워드: {kw}")


def search(session: Session, query: str, limit: int = 8) -> tuple[str, list[Hit], str]:
    """(한 줄 답, 결과 목록, source) — source: gemini | mock | fallback"""
    records = session.scalars(select(FileRecord)).all()
    toks = tokens(query) or [query.strip().lower()]
    scored = sorted(((keyword_score(toks, r), r) for r in records), key=lambda x: -x[0])
    local = [(s, r) for s, r in scored if s > 0]

    def _mock(source: str) -> tuple[str, list[Hit], str]:
        hits = [Hit(r, s, f"제목·요약·키워드에 '{' '.join(toks)}'와 비슷한 단어가 있습니다.")
                for s, r in local[:limit]]
        if hits:
            answer = f"'{query}'와 관련 있어 보이는 파일 {len(hits)}개를 찾았습니다."
        else:
            answer = f"'{query}'와 맞는 파일을 찾지 못했습니다. 다른 단어로 검색해 보세요."
        return answer, hits, source

    if not settings.use_gemini:
        return _mock("mock")

    # Gemini에게는 민감하지 않은 파일만 후보로 보낸다
    candidates = [r for _, r in local if not r.sensitive][:20]
    if len(candidates) < 5:  # 단어가 안 겹쳐도 뜻이 같은 파일을 찾도록 최근 파일을 더한다
        chosen = {r.id for r in candidates}
        recent = sorted((r for r in records if not r.sensitive and r.id not in chosen),
                        key=lambda r: r.id, reverse=True)
        candidates += recent[: 30 - len(candidates)]
    if not candidates:
        return _mock("mock")
    parts = [{"type": "text", "text": f"질문: {query}\n\n후보 파일 목록:\n" +
              "\n".join(_describe(r) for r in candidates)}]
    try:
        deadline = time.monotonic() + 30  # 검색은 30초 안에
        text = analyzer.run_with_limit(
            lambda: analyzer.call_with_retry(parts, SEARCH_PROMPT, SEARCH_SCHEMA, deadline=deadline), 35)
        parsed = _SearchAnswer.model_validate_json(text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Gemini 검색 실패 → 단어 비교 결과로 대체: %s", exc)
        return _mock("fallback")
    by_id = {r.id: r for r in candidates}
    local_score = {r.id: s for s, r in local}
    hits: list[Hit] = []
    for pick in parsed.results:
        rec = by_id.get(pick.id)
        if rec is not None and all(h.record.id != rec.id for h in hits):
            hits.append(Hit(rec, local_score.get(rec.id, 0.0), pick.reason.strip()))
    # 민감 파일은 내 컴퓨터 점수로만 뒤에 붙인다
    for s, r in local:
        if r.sensitive and len(hits) < limit:
            hits.append(Hit(r, s, "🔒 민감 파일 — AI에 보내지 않고 이름으로만 찾았습니다."))
    return parsed.answer.strip(), hits[:limit], "gemini"
