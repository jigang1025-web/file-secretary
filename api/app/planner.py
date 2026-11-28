"""폴더를 살펴보고 '정리 계획'(원래 이름 → 새 이름·폴더)을 만드는 부분.

순서
1. 정리할 폴더 맨 위에 있는 파일 목록 (하위 폴더 = 이미 정리된 것은 건드리지 않음)
2. 내용 지문(SHA-256)으로 중복 파일 찾기
3. 글자·이미지 추출 → 민감 파일 판별 → 개인정보 가리기
4. AI 분석 (Gemini 또는 규칙 기반)
5. 새 이름 만들기: 날짜_과목_제목.확장자 (Windows에서 못 쓰는 문자 제거, 이름 겹침 방지)
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import analyzer
from .config import settings
from .db import AnalysisCache, AppSettings, FileRecord, Plan, PlanItem
from .extractors import Extracted, extract, kind_of
from .security import SENSITIVE_KEYWORDS, detect_sensitive, mask_text

log = logging.getLogger(__name__)

MARKER = ".file-secretary-demo"
SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store", MARKER}
PARTIAL_EXT = {".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload"}
DUPLICATE_DIR = "중복 파일"

NAME_PATTERNS = {
    "date_course_title": ["date", "course", "title"],
    "course_title_date": ["course", "title", "date"],
    "title_date": ["title", "date"],
    "title_only": ["title"],
}

WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}


# ---------------------------------------------------------------------------
# 경로·이름 도구
# ---------------------------------------------------------------------------
def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def safe_join(root: Path, relative: str) -> Path:
    """root 밖으로 나가는 경로(../ 등)를 막는다."""
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError(f"정리 폴더 밖의 경로입니다: {relative}")
    return candidate


def sanitize_component(text: str, max_len: int = 80) -> str:
    """파일·폴더 이름 한 조각에서 Windows에서 못 쓰는 문자를 없앤다."""
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip().strip(".")
    text = text[:max_len].strip().strip(".")
    if text.lower() in WINDOWS_RESERVED:
        text = f"_{text}"
    return text


def sanitize_dest_dir(value: str) -> str:
    parts = [sanitize_component(p, 60) for p in re.split(r"[\\/]+", value or "")]
    parts = [p for p in parts if p and p not in (".", "..")]
    return "/".join(parts)


def strip_course(title: str, course: str) -> str:
    """제목에 과목명이 또 들어 있으면 뺀다 ('오픈소스 프로그래밍 기말 안내' → '기말 안내')."""
    compact = course.replace(" ", "")
    if compact:
        pattern = r"\s*".join(map(re.escape, compact))
        title = re.sub(pattern, " ", title, flags=re.I)
    return re.sub(r"\s+", " ", title).strip(" _-")


def build_name(pattern: str, date_str: str, course: str, title: str, ext: str) -> str:
    title = sanitize_component(strip_course(title, course), 60) or "파일"
    values = {"date": date_str, "course": sanitize_component(course, 30), "title": title}
    segments = [values[k] for k in NAME_PATTERNS.get(pattern, NAME_PATTERNS["date_course_title"]) if values[k]]
    stem = "_".join(segments)[:120].strip(" ._")
    return f"{stem}{ext.lower()}"


def unique_name(dest_abs: Path, name: str, taken: set[str]) -> str:
    """같은 폴더에 같은 이름이 있으면 '이름 (2).pdf' 처럼 번호를 붙인다 (대소문자 무시 = Windows 기준)."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    existing = {p.name.lower() for p in dest_abs.iterdir()} if dest_abs.is_dir() else set()
    candidate, n = name, 2
    while candidate.lower() in existing or f"{dest_abs}/{candidate}".lower() in taken:
        candidate = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
        n += 1
    taken.add(f"{dest_abs}/{candidate}".lower())
    return candidate


def dest_dir_for(category: str, course: str) -> str:
    if category == "수업":
        return f"수업/{sanitize_component(course, 40) or '기타'}"
    return category


# ---------------------------------------------------------------------------
# 날짜
# ---------------------------------------------------------------------------
NAME_DATE = [re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"),
             re.compile(r"(?<!\d)(20\d{2})[-_.](\d{1,2})[-_.](\d{1,2})(?!\d)")]
_DATE = r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})(?!\d)"
TEXT_DATE = re.compile(r"(?<!\d)" + _DATE)
# '공지일: 2026년 11월 9일'처럼 이름표가 붙은 날짜를 먼저 쓴다 (마감일은 대표 날짜가 아님)
LABELED_DATE = re.compile(r"(?:공지일|게시일|작성일|발행일|결제일|등록일|발급일|작성\s?일자|일자|날짜)\s*[:：]?\s*" + _DATE)
SPREADSHEET_EXT = {".xlsx", ".xls", ".csv"}


def _ymd(y: str, m: str, d: str) -> str:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return ""


def date_from_name(name: str) -> str:
    for pattern in NAME_DATE:
        for m in pattern.finditer(name):
            value = _ymd(*m.groups())
            if value:
                return value
    return ""


def date_from_text(text: str) -> str:
    """문서의 대표 날짜: 이름표가 붙은 날짜 → 없으면 제목 근처(앞 120자)의 날짜."""
    for m in LABELED_DATE.finditer(text[:3000]):
        value = _ymd(*m.groups())
        if value:
            return value
    for m in TEXT_DATE.finditer(text[:120]):
        value = _ymd(*m.groups())
        if value:
            return value
    return ""


def mtime_date(mtime: float) -> str:
    return datetime.fromtimestamp(mtime).date().isoformat()


# ---------------------------------------------------------------------------
# 파일 목록·지문
# ---------------------------------------------------------------------------
def list_candidates(root: Path, limit: int) -> list[Path]:
    files = []
    for p in root.iterdir():
        name = p.name
        if name.startswith(".") or name.startswith("~$") or name.lower() in SKIP_NAMES:
            continue
        if p.suffix.lower() in PARTIAL_EXT or p.is_symlink() or not p.is_file():
            continue
        files.append(p)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)  # 최근 파일부터
    return files[:limit]


def file_hash(path: Path) -> str:
    """내용 지문. 아주 큰 파일(200MB 초과)은 앞·뒤 4MB와 크기로 빠르게 계산한다."""
    size = path.stat().st_size
    h = hashlib.sha256()
    with path.open("rb") as f:
        if size <= 200 * 1024 * 1024:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
            return h.hexdigest()
        h.update(f.read(4 * 1024 * 1024))
        f.seek(-4 * 1024 * 1024, 2)
        h.update(f.read())
        h.update(str(size).encode())
        return "p:" + h.hexdigest()


# ---------------------------------------------------------------------------
# 계획 만들기
# ---------------------------------------------------------------------------
@dataclass
class _Work:
    path: Path
    rel: str
    size: int
    mtime: float
    sha: str
    ext: str
    kind: str
    flags: list[str] = field(default_factory=list)
    duplicate_of: str = ""
    extracted: Extracted | None = None
    sensitive: bool = False
    sensitive_reason: str = ""
    masked_text: str = ""


def sensitive_title(name: str, text: str, extra: list[str] | None = None) -> str:
    """민감 파일 제목: 파일 이름 → 문서 첫머리 순서로 '가족관계증명서' 같은 단어를 찾는다 (내 컴퓨터에서만)."""
    keywords = SENSITIVE_KEYWORDS + [k for k in (extra or []) if k.strip()]
    for hay in (name.replace(" ", ""), text[:300].replace(" ", "")):
        for kw in keywords:
            if kw.replace(" ", "") in hay:
                return kw.replace(" ", "")
    return ""


def keep_original_name(kind: str, source: str) -> bool:
    """설치 파일·음성/영상은 원래 이름이 더 알아보기 쉽다. 압축 파일은 AI가 안을 보고 이름을 지었을 때만 바꾼다."""
    if kind in ("installer", "media"):
        return True
    return kind in ("archive", "other") and source != "gemini"


def _cache_key(sha: str, cfg, want_image: bool) -> str:
    basis = json.dumps([sha, cfg.courses or [], want_image, settings.gemini_model, analyzer.CACHE_VERSION],
                       ensure_ascii=False)
    return hashlib.sha256(basis.encode()).hexdigest()


def _store_cache(session, key: str, ins: analyzer.Insight) -> None:
    """분석 결과 저장. 감시 데몬과 API가 같은 파일을 동시에 저장해도 오류 없이 넘어간다."""
    try:
        session.merge(AnalysisCache(key=key, insight=dataclasses.asdict(ins)))
        session.commit()
    except IntegrityError:
        session.rollback()


def _analyze_with_cache(session, inputs, works, cfg, want_image) -> dict:
    """저장된 Gemini 결과가 있는 파일은 그대로 쓰고, 처음 보는 파일만 Gemini에 보낸다."""
    if not (settings.use_gemini and settings.llm_cache) or not inputs:
        return analyzer.analyze(inputs, cfg.courses or [])
    keys = {inp.index: _cache_key(works[inp.index].sha, cfg, want_image) for inp in inputs}
    rows = {r.key: r for r in session.scalars(select(AnalysisCache).where(AnalysisCache.key.in_(keys.values())))}
    session.commit()  # AI를 기다리는 동안 DB 트랜잭션을 열어 두지 않는다
    insights: dict = {}
    misses = []
    for inp in inputs:
        row = rows.get(keys[inp.index])
        if row:
            insights[inp.index] = analyzer.Insight(**row.insight)
        else:
            misses.append(inp)
    if misses:
        fresh = analyzer.analyze(misses, cfg.courses or [])
        insights.update(fresh)
        for inp in misses:
            ins = fresh.get(inp.index)
            if ins and ins.source == "gemini":  # 실패해서 규칙 기반으로 대신한 결과는 저장하지 않음
                _store_cache(session, keys[inp.index], ins)
    log.info("AI 분석: 저장된 결과 %d개, 새로 분석 %d개", len(inputs) - len(misses), len(misses))
    return insights


def _collect(session: Session, root: Path, paths: list[Path]) -> list[_Work]:
    """① 파일 정보와 내용 지문 → ② 중복 표시 → 오래된 설치 파일 표시."""
    works: list[_Work] = []
    for p in paths:
        st = p.stat()
        works.append(_Work(path=p, rel=rel(root, p), size=st.st_size, mtime=st.st_mtime,
                           sha=file_hash(p), ext=p.suffix.lower(), kind=kind_of(p.suffix)))

    # ② 중복: 같은 지문 중 가장 오래된 파일을 원본으로 본다
    by_hash: dict[str, list[_Work]] = {}
    for w in works:
        by_hash.setdefault(w.sha, []).append(w)
    for group in by_hash.values():
        group.sort(key=lambda w: (w.mtime, len(w.path.name)))
        for dup in group[1:]:
            dup.duplicate_of = group[0].path.name
            dup.flags.append(f"'{group[0].path.name}'와 내용이 같은 중복 파일")
    current = {w.rel for w in works}
    for w in works:
        if w.duplicate_of:
            continue
        twin = session.scalars(select(FileRecord).where(FileRecord.sha256 == w.sha)).first()
        if twin and twin.path_rel not in current and safe_join(root, twin.path_rel).exists():
            w.duplicate_of = twin.path_rel
            w.flags.append(f"이미 정리된 '{twin.path_rel}'와 같은 파일")

    # 오래된 설치 파일
    now = time.time()
    for w in works:
        if w.kind == "installer" and now - w.mtime > settings.old_installer_days * 86400:
            w.flags.append(f"{settings.old_installer_days}일 넘은 설치 파일 — 지워도 되는지 확인해 보세요")
    return works


def _extract_all(targets: list[_Work], cfg: AppSettings, want_image: bool) -> None:
    """③ 내용 추출 (병렬) → 민감 판별 → 가리기."""
    def _extract(w: _Work) -> Extracted:
        return extract(w.path, settings.max_text_chars, want_image=want_image,
                       ocr=settings.ocr_enabled and w.kind == "image")

    with ThreadPoolExecutor(max_workers=settings.extract_workers) as pool:
        for w, ex in zip(targets, pool.map(_extract, targets)):
            w.extracted = ex
            check = detect_sensitive(w.path.name, f"{ex.text}\n{ex.ocr_text}", cfg.extra_sensitive_keywords)
            w.sensitive, w.sensitive_reason = check.sensitive, check.reason
            if not w.sensitive:
                w.masked_text, _ = mask_text(ex.text)


def _make_inputs(works: list[_Work], want_image: bool) -> list[analyzer.AnalysisInput]:
    """④ AI에 보낼 입력 (중복·민감·추출 안 한 파일 제외)."""
    inputs: list[analyzer.AnalysisInput] = []
    for i, w in enumerate(works):
        if w.duplicate_of or w.sensitive or w.extracted is None:
            continue
        ex = w.extracted
        inputs.append(analyzer.AnalysisInput(
            index=i, name=w.path.name, ext=w.ext, kind=w.kind, size=w.size,
            date_hint=date_from_name(w.path.name) or ex.exif_date or mtime_date(w.mtime),
            text=w.masked_text, ocr_text=ex.ocr_text,
            image=ex.image if want_image else None, image_mime=ex.image_mime,
            document=ex.document if settings.use_gemini else None))
    return inputs


def prefetch(session: Session, root: Path, cfg: AppSettings, paths: list[Path]) -> dict[str, str]:
    """감시 데몬용: 새 파일을 미리 Gemini로 분석해 저장만 한다 (계획은 만들지 않음).

    돌려주는 값: {상대 경로: "ai"(AI 결과 저장됨) | "local"(중복·민감 → AI 불필요) | "failed"(나중에 다시)}
    """
    root = root.resolve()
    if not (settings.use_gemini and settings.llm_cache) or not paths:
        return {}
    works = _collect(session, root, paths)
    want_image = cfg.analyze_images
    keys = {w.rel: _cache_key(w.sha, cfg, want_image) for w in works if not w.duplicate_of}
    have = set(session.scalars(select(AnalysisCache.key).where(AnalysisCache.key.in_(keys.values()))))
    session.commit()
    todo = [w for w in works if not w.duplicate_of and keys[w.rel] not in have]
    _extract_all(todo, cfg, want_image)
    insights = _analyze_with_cache(session, _make_inputs(works, want_image), works, cfg, want_image)
    outcome: dict[str, str] = {}
    for i, w in enumerate(works):
        if w.duplicate_of or w.sensitive:
            outcome[w.rel] = "local"
        elif keys[w.rel] in have or (insights.get(i) and insights[i].source == "gemini"):
            outcome[w.rel] = "ai"
        else:
            outcome[w.rel] = "failed"
    return outcome


def build_plan(session: Session, root: Path, cfg: AppSettings, limit: int | None = None) -> Plan:
    root = root.resolve()
    limit = min(limit or settings.max_files_per_scan, settings.max_files_per_scan)
    works = _collect(session, root, list_candidates(root, limit))
    want_image = settings.use_gemini and cfg.analyze_images
    _extract_all([w for w in works if not w.duplicate_of], cfg, want_image)
    inputs = _make_inputs(works, want_image)
    insights = _analyze_with_cache(session, inputs, works, cfg, want_image)

    # ⑤ 새 이름·폴더
    plan = Plan(status="draft", total=len(works))
    taken: set[str] = set()
    sources: set[str] = set()
    for i, w in enumerate(works):
        ex = w.extracted
        if w.duplicate_of:
            ins = analyzer.Insight(category=DUPLICATE_DIR, title=w.path.stem, source="rule",
                                   summary="중복 파일이라 분석하지 않았습니다.")
            dest, new_name = DUPLICATE_DIR, w.path.name
        else:
            if w.sensitive:
                local_text = f"{ex.text}\n{ex.ocr_text}" if ex else ""
                ins = analyzer.sensitive_insight(
                    analyzer.AnalysisInput(index=i, name=w.path.name, ext=w.ext, kind=w.kind, size=w.size,
                                           date_hint=""),
                    sensitive_title(w.path.name, local_text, cfg.extra_sensitive_keywords))
            else:
                ins = insights.get(i) or analyzer.Insight(category="기타", title=w.path.stem)
            text_for_date = "" if (w.sensitive or w.ext in SPREADSHEET_EXT) else (ex.text if ex else "")
            day = (ins.date or date_from_text(text_for_date) or date_from_name(w.path.name)
                   or (ex.exif_date if ex else "") or mtime_date(w.mtime))
            ins.date = day
            dest = dest_dir_for(ins.category, ins.course)
            if keep_original_name(w.kind, ins.source):
                new_name = w.path.name
            elif cfg.keep_good_names is not False and ins.name_ok and not w.sensitive:
                new_name = w.path.name
                w.flags = [*w.flags, "이름이 이미 알아보기 쉬워 그대로 둠"]
            else:
                new_name = build_name(cfg.name_pattern, day, ins.course, ins.title, w.ext)
        new_name = unique_name(safe_join(root, dest), new_name, taken)
        sources.add(ins.source)
        errors = [e for e in ((ex.error if ex else None), ins.error) if e]
        preview = ""
        if ex and not w.sensitive:
            preview = (w.masked_text or ex.ocr_text)[:300]
        plan.items.append(PlanItem(
            src_rel=w.rel, size=w.size, mtime=w.mtime, sha256=w.sha, ext=w.ext, kind=w.kind,
            category=ins.category, course=ins.course, title=ins.title, date=ins.date,
            summary=ins.summary, keywords=ins.keywords, new_name=new_name, dest_dir=dest,
            include=True, sensitive=w.sensitive, sensitive_reason=w.sensitive_reason,
            flags=w.flags, source=ins.source, error="; ".join(errors) or None, preview=preview))
        _upsert_record(session, w, ins, preview)

    plan.llm_source = "gemini" if "gemini" in sources else ("fallback" if "fallback" in sources else "mock")
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def _upsert_record(session: Session, w: _Work, ins: analyzer.Insight, excerpt: str) -> None:
    """정리 전에도 검색할 수 있도록 지금 위치로 색인해 둔다."""
    rec = session.scalars(select(FileRecord).where(FileRecord.path_rel == w.rel)).first()
    if rec is None:
        rec = FileRecord(path_rel=w.rel)
        session.add(rec)
    rec.original_name = w.path.name
    rec.title, rec.category, rec.course, rec.date = ins.title, ins.category, ins.course, ins.date
    rec.summary, rec.keywords = ins.summary, ins.keywords
    rec.excerpt = excerpt
    rec.sensitive, rec.sha256, rec.size, rec.ext = w.sensitive, w.sha, w.size, w.ext
