"""생성 AI(Gemini)로 파일 내용을 이해하는 부분 + 키가 없을 때 쓰는 규칙 기반 분석.

Gemini 호출은 공식 문서와 같은 google-genai SDK의 interactions API를 쓴다.
- 여러 파일을 한 번에 묶어 보낸다 (기본 8개) → 무료 등급 호출 한도를 아낀다.
- 이미지는 축소 JPEG, 글자가 없는 스캔 PDF는 원본을 함께 보낸다 (멀티모달 입력).
- 응답을 JSON 스키마로 강제한다 (구조화 출력) → 파이썬에서 바로 검증.
- 실패하면(네트워크·할당량·형식 오류) 그 묶음만 규칙 기반으로 대체하고 정리는 계속한다.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel, Field

from .config import settings

log = logging.getLogger(__name__)

# 프롬프트·결과 형식을 바꾸면 올려서 저장된 분석 결과(analysis_cache)를 새로 받게 한다
CACHE_VERSION = 2  # 2: name_ok(원래 이름이 이미 알아보기 쉬운지) 추가

CATEGORIES = ["수업", "문서", "개인서류", "영수증·결제", "사진", "스크린샷", "영상·음성", "설치파일",
              "압축파일", "기타"]

RECEIPT_WORDS = re.compile(r"영수증|결제|주문|구매|카드승인|거래명세|invoice|receipt", re.I)
# 사진으로 찍은 영수증은 OCR이 단어를 끊어 읽는 경우가 많아 단서를 더 넓게 본다
RECEIPT_IMAGE_WORDS = re.compile(r"영수증|결제|주문|승인|합계|부가세|카드|VAT|receipt|total", re.I)
SCREENSHOT_NAME = re.compile(r"screenshot|스크린샷|캡처|capture|screen ?shot|snip", re.I)


@dataclass
class AnalysisInput:
    index: int
    name: str
    ext: str
    kind: str
    size: int
    date_hint: str                 # 받은 날짜(파일 이름·촬영일·수정일 중 하나)
    text: str = ""                 # 가린(masked) 문서 글자
    ocr_text: str = ""             # 이미지에서 내 컴퓨터로 읽은 글자 (규칙 기반에서만 사용)
    image: bytes | None = None
    image_mime: str = "image/jpeg"
    document: bytes | None = None


@dataclass
class Insight:
    category: str
    course: str = ""
    title: str = ""
    date: str = ""
    summary: str = ""
    keywords: list[str] = field(default_factory=list)
    name_ok: bool = False          # 원래 파일 이름만 봐도 무슨 파일인지 알 수 있는가
    source: str = "mock"           # gemini | mock | fallback | rule
    error: str | None = None


# ---------------------------------------------------------------------------
# 과목 목록: "기계학습: 머신러닝, ML" 처럼 별칭을 쓸 수 있다
# ---------------------------------------------------------------------------
def parse_courses(lines: list[str]) -> dict[str, list[str]]:
    courses: dict[str, list[str]] = {}
    for line in lines:
        if not line.strip():
            continue
        name, _, aliases = line.partition(":")
        name = name.strip()
        if name:
            courses[name] = [name] + [a.strip() for a in aliases.split(",") if a.strip()]
    return courses


def _compact(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def match_course(text: str, courses: dict[str, list[str]]) -> str:
    hay = _compact(text)
    best, best_pos = "", None
    for name, aliases in courses.items():
        for alias in aliases:
            a = _compact(alias)
            if len(a) < 2:
                continue
            pos = hay.find(a)
            if pos >= 0 and (best_pos is None or pos < best_pos):  # 가장 먼저 나온 과목
                best, best_pos = name, pos
    return best


def normalize_course(value: str, courses: dict[str, list[str]]) -> str:
    """Gemini가 돌려준 과목 이름을 사용자 목록의 정확한 이름으로 맞춘다 (없으면 빈 문자열)."""
    if not value:
        return ""
    v = _compact(value)
    for name, aliases in courses.items():
        if any(_compact(a) == v for a in aliases):
            return name
    return match_course(value, courses)


# ---------------------------------------------------------------------------
# 규칙 기반 분석 (Gemini 키가 없거나 실패했을 때)
# ---------------------------------------------------------------------------
NOISE_NAME = re.compile(
    r"kakaotalk_?\d*_?\d*|screenshot_?[\d_-]*|img_?\d+|dsc_?\d+|scan_?\d+|image|\(\d+\)|"
    r"다운로드|복사본|copy|최종|진짜|final|제출용|새 텍스트 문서|제목 없음|무제|untitled|새 문서|새 한글 문서",
    re.I)
DATEISH = re.compile(r"^[\d\s.\-/:년월일]+$")


def shorten(text: str, limit: int = 40) -> str:
    """단어 중간이나 괄호 안에서 끊기지 않게 줄인다."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    if cut.count("(") > cut.count(")"):
        cut = cut[: cut.rfind("(")]
    return cut.strip(" -—·:,")


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip(" -•·*#|")
        if line.startswith("[시트]"):
            continue
        hangul = len(re.findall(r"[가-힣]", line))
        if len(line) < 2 or DATEISH.match(line) or (hangul < 2 and len(line) < 6):
            continue
        return shorten(line, 40)
    return ""


def _title_from_name(name: str) -> str:
    stem = name.rsplit(".", 1)[0]
    stem = NOISE_NAME.sub(" ", stem)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:30] if len(re.sub(r"[\d\s]", "", stem)) >= 2 else ""


def name_is_meaningful(name: str) -> bool:
    """규칙 기반 판단: 자동으로 붙은 이름이 아니고, 한글이 충분히(6자 이상) 들어 있으면 알아보기 쉬운 이름으로 본다."""
    stem = name.rsplit(".", 1)[0]
    if NOISE_NAME.search(stem):
        return False
    return len(re.findall(r"[가-힣]", stem)) >= 6


def _summary_from_text(text: str) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return (flat[:110] + "…") if len(flat) > 110 else flat


def mock_insight(inp: AnalysisInput, courses: dict[str, list[str]], source: str = "mock",
                 error: str | None = None) -> Insight:
    text = inp.text or inp.ocr_text
    hay = f"{inp.name}\n{text[:3000]}"
    course = ""
    if inp.kind == "installer":
        category = "설치파일"
    elif inp.kind == "archive":
        category = "압축파일"
    elif inp.kind == "media":
        category = "영상·음성"
    elif inp.kind == "image":
        course = match_course(hay, courses)
        if course:
            category = "수업"
        elif RECEIPT_IMAGE_WORDS.search(hay):
            category = "영수증·결제"
        elif SCREENSHOT_NAME.search(inp.name) or inp.ext == ".png":
            category = "스크린샷"
        else:
            category = "사진"
    elif inp.kind == "document":
        course = match_course(hay, courses)
        if course:
            category = "수업"
        elif RECEIPT_WORDS.search(hay):
            category = "영수증·결제"
        else:
            category = "문서"
    else:
        category = "기타"

    title = ""
    if inp.kind == "document":
        title = _title_from_text(inp.text)
    elif inp.kind == "image" and inp.ocr_text:
        title = _title_from_text(inp.ocr_text)
    title = title or _title_from_name(inp.name) or category
    summary = _summary_from_text(text) if text else f"(규칙 기반) {category} 파일입니다."
    keywords = [w for w in dict.fromkeys(re.findall(r"[가-힣A-Za-z0-9]{2,}", f"{course} {title}"))][:5]
    return Insight(category=category, course=course, title=title, date="", summary=summary,
                   keywords=keywords, name_ok=name_is_meaningful(inp.name), source=source, error=error)


def sensitive_insight(inp: AnalysisInput, reason_keyword: str = "") -> Insight:
    """민감 파일은 AI에 보내지 않고 이름만으로 정리한다."""
    title = reason_keyword or _title_from_name(inp.name) or "개인서류"
    return Insight(category="개인서류", title=title,
                   summary="민감한 정보가 있을 수 있어 내용을 AI에 보내지 않았습니다.",
                   keywords=[title], source="rule")


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
class _FileInsight(BaseModel):
    index: int
    category: str
    course: str = ""
    title: str = ""
    date: str = ""
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    name_ok: bool = False


class _BatchInsights(BaseModel):
    files: list[_FileInsight]


INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "The [파일 index=N] number"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "course": {"type": "string",
                               "description": "Exactly one name from the user's course list, or empty string"},
                    "title": {"type": "string",
                              "description": "Korean title, 2-25 chars, no date, no course name, no \\/:*?\"<>|"},
                    "date": {"type": "string",
                             "description": "YYYY-MM-DD date written in the content (issue/creation date), or empty"},
                    "summary": {"type": "string", "description": "Korean, 1-2 sentences"},
                    "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                    "name_ok": {"type": "boolean",
                                "description": "true if the ORIGINAL file name alone already tells clearly what the file is"},
                },
                "required": ["index", "category", "course", "title", "date", "summary", "keywords", "name_ok"],
            },
        }
    },
    "required": ["files"],
}

SYSTEM_PROMPT = """너는 대학생의 컴퓨터 파일을 정리해 주는 '파일 정리 비서'다.
각 파일의 이름, 형식, 받은 날짜, 내용 일부(또는 이미지)를 보고 정리 정보를 JSON으로 답한다.

규칙
1. category는 다음 중 하나: {categories}
   - 수업: 강의자료·과제·시험·수업 공지처럼 특정 과목과 관련된 파일 (사진·캡처라도 수업 내용이면 수업)
   - 문서: 과목과 무관한 일반 문서 (장학·행정 안내, 신청서, 메모 등)
   - 영수증·결제: 영수증, 주문·결제 내역, 거래명세서
   - 스크린샷: 화면을 캡처한 이미지, 사진: 카메라로 찍은 사진
   - 개인서류: 신분증·증명서 같은 개인 서류
2. course는 사용자 과목 목록에 있는 이름을 그대로 쓰고, 해당 과목이 없으면 빈 문자열로 둔다.
3. title은 내용을 대표하는 한국어 제목 2~25자. 날짜와 과목명은 넣지 말고,
   파일 이름에 쓸 수 없는 문자(\\ / : * ? " < > |)도 쓰지 않는다. 예: '기말 프로젝트 안내', '카페 영수증'
4. date는 내용에 적힌 대표 날짜(작성일·공지일·발행일)를 YYYY-MM-DD로. 없거나 확실하지 않으면 빈 문자열. 지어내지 않는다.
5. summary는 한국어 1~2문장, keywords는 나중에 검색할 때 쓸 단어 3~6개.
6. [MASKED]는 개인정보를 일부러 가린 것이다. 추측하지 않는다.
7. 입력된 모든 파일(index)에 빠짐없이 답한다.
8. name_ok는 원래 파일 이름만 보고도 무슨 파일인지 구체적으로 알 수 있으면 true다.
   예: '한국근현대사 연표 양식', '2026학년도 2학기 부·복수전공 신청 안내' → true
   KakaoTalk_날짜, Screenshot, IMG_번호, 다운로드 (7), scan0001, 제목 없음, 새 문서, final_진짜최종(2),
   '강의자료_week10'처럼 자동으로 붙었거나 과목·내용을 알 수 없는 이름은 false다."""


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n}B"


def build_parts(batch: list[AnalysisInput], course_names: list[str]) -> list[dict]:
    """Gemini interactions API의 input 목록 (텍스트·이미지·문서 조각)."""
    parts: list[dict] = [{
        "type": "text",
        "text": (f"오늘 날짜: {date.today().isoformat()}\n"
                 f"사용자 과목 목록: {', '.join(course_names) if course_names else '(없음)'}\n"
                 f"아래 {len(batch)}개 파일을 분석하세요."),
    }]
    for inp in batch:
        header = (f"\n[파일 index={inp.index}] 이름: {inp.name} | 형식: {inp.ext or '없음'} | "
                  f"크기: {_human_size(inp.size)} | 받은 날짜: {inp.date_hint}")
        if inp.text:
            body = f"\n내용 일부:\n{inp.text}"
        elif inp.image or inp.document:
            body = "\n(아래 첨부를 보고 판단하세요)"
        else:
            body = "\n(내용을 읽을 수 없는 파일 — 이름과 형식으로만 판단하세요)"
        parts.append({"type": "text", "text": header + body})
        if inp.image:
            parts.append({"type": "image", "data": base64.b64encode(inp.image).decode(),
                          "mime_type": inp.image_mime})
        elif inp.document and not inp.text:
            parts.append({"type": "document", "data": base64.b64encode(inp.document).decode(),
                          "mime_type": "application/pdf"})
    return parts


def _call_gemini(parts: list[dict], system: str, schema: dict, model: str | None = None,
                 timeout: float | None = None) -> str:
    from google import genai  # 규칙 기반 모드에서는 SDK를 불러올 필요가 없음

    # 호출 한도(429)나 일시 오류(5xx)면 SDK가 1초→최대 6초 간격으로 다시 시도한다
    options: dict = {"retry_options": {"attempts": settings.llm_retry_attempts,
                                       "initial_delay": 1.0, "max_delay": 6.0}}
    if settings.gemini_base_url:
        options["base_url"] = settings.gemini_base_url
    client = genai.Client(api_key=settings.gemini_api_key, http_options=options)
    extra: dict = {}
    if settings.llm_thinking_level:
        extra["generation_config"] = {"thinking_level": settings.llm_thinking_level}
    interaction = client.interactions.create(
        **extra,
        model=model or settings.gemini_model,
        system_instruction=system,
        input=parts,
        response_format={"type": "text", "mime_type": "application/json", "schema": schema},
        store=False,  # 대화 기록을 서버에 저장하지 않도록 요청
        timeout=timeout or settings.llm_timeout_seconds,
    )
    return interaction.output_text


# 마지막으로 성공한 모델. 기본 모델이 붐비면 다음 묶음부터는 이 모델로 바로 보낸다.
_active_model: str | None = None

_TRANSIENT_MARKERS = ("503", "429", "500", "502", "504", "unavailable", "resource_exhausted",
                      "high demand", "overloaded", "rate limit", "timed out", "timeout",
                      # 이 계정에서 쓸 수 없는 모델(404)도 다음 모델로 넘어간다
                      "404", "not_found", "no longer available")


def is_transient(exc: Exception) -> bool:
    """다른 모델로는 될 수 있는 오류인가 (서버 혼잡·한도 초과·응답 지연·쓸 수 없는 모델)."""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(m in text for m in _TRANSIENT_MARKERS)


def model_chain() -> list[str]:
    chain = [settings.gemini_model, *settings.gemini_fallback_models]
    if _active_model in chain:  # 최근에 성공한 모델을 먼저
        chain.remove(_active_model)
        chain.insert(0, _active_model)
    return list(dict.fromkeys(chain))


class BudgetExceeded(TimeoutError):
    """한 번 살펴보기에 정한 AI 분석 시간을 다 썼다."""


def call_with_retry(parts: list[dict], system: str, schema: dict, deadline: float | None = None) -> str:
    """Gemini 호출. 같은 모델 재시도는 SDK의 retry_options가 맡고,
    그래도 혼잡·한도·지연 오류면 예비 모델(GEMINI_FALLBACK_MODELS)로 넘어간다."""
    global _active_model
    last: Exception | None = None
    for model in model_chain():
        timeout = settings.llm_timeout_seconds
        if deadline is not None:
            left = deadline - time.monotonic()
            if left < 3:
                raise BudgetExceeded(f"AI 분석 시간({settings.llm_total_budget_seconds:.0f}초)을 넘겨 규칙 기반으로 마무리")
            timeout = min(timeout, left)
        size_kb = sum(len(p.get("text", "")) + len(p.get("data", "")) for p in parts) // 1024
        started = time.monotonic()
        log.info("Gemini 호출 시작: %s, 보낸 양 약 %dKB", model, size_kb)
        try:
            text = _call_gemini(parts, system, schema, model, timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("Gemini 호출 실패: %s, %.1f초, %s", model, time.monotonic() - started, str(exc)[:160])
            if not is_transient(exc):
                raise  # 키 오류 등은 다른 모델로 바꿔도 안 되므로 바로 알림
            log.warning("Gemini %s 사용 불가(%s) → 다음 모델 시도", model, str(exc)[:120])
            last = exc
            continue
        log.info("Gemini 호출 성공: %s, %.1f초", model, time.monotonic() - started)
        if model != _active_model:
            log.info("Gemini 모델 %s 사용", model)
        _active_model = model
        return text
    assert last is not None
    raise last


def clean_title(title: str) -> str:
    title = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", title or "")
    return re.sub(r"\s+", " ", title).strip()[:40]


def valid_date(value: str) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", (value or "").strip())
    if not m:
        return ""
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return ""


def _make_batches(items: list[AnalysisInput]) -> list[list[AnalysisInput]]:
    """한 번에 보낼 묶음: 개수(LLM_BATCH_SIZE)와 용량(약 12MB, 요청 한도 20MB)을 함께 제한."""
    batches, current, size = [], [], 0
    for inp in items:
        weight = len(inp.text) + len(inp.image or b"") + len(inp.document or b"")
        if current and (len(current) >= settings.llm_batch_size or size + weight > 12 * 1024 * 1024):
            batches.append(current)
            current, size = [], 0
        current.append(inp)
        size += weight
    if current:
        batches.append(current)
    return batches


def _gemini_batch(batch: list[AnalysisInput], courses: dict[str, list[str]],
                  deadline: float | None = None) -> dict[int, Insight]:
    system = SYSTEM_PROMPT.format(categories=", ".join(CATEGORIES))
    text = call_with_retry(build_parts(batch, list(courses)), system, INSIGHT_SCHEMA, deadline)
    parsed = _BatchInsights.model_validate_json(text)
    results: dict[int, Insight] = {}
    for f in parsed.files:
        category = f.category if f.category in CATEGORIES else "기타"
        course = normalize_course(f.course, courses)
        if category == "수업" and not course:
            course = ""
        results[f.index] = Insight(
            category=category, course=course, title=clean_title(f.title), date=valid_date(f.date),
            summary=(f.summary or "").strip()[:300], keywords=[k.strip() for k in f.keywords if k.strip()][:6],
            name_ok=bool(f.name_ok), source="gemini")
    return results


def analyze(items: list[AnalysisInput], course_lines: list[str]) -> dict[int, Insight]:
    """파일 목록을 분석해 {index: Insight}를 돌려준다."""
    courses = parse_courses(course_lines)
    if not settings.use_gemini:
        return {inp.index: mock_insight(inp, courses) for inp in items}

    deadline = time.monotonic() + settings.llm_total_budget_seconds

    def run(batch: list[AnalysisInput]) -> dict[int, Insight]:
        try:
            got = _gemini_batch(batch, courses, deadline)
        except Exception as exc:  # noqa: BLE001 — 실패한 묶음만 규칙 기반으로 대체
            log.warning("Gemini 분석 실패 → 규칙 기반으로 대체: %s", exc)
            err = f"{type(exc).__name__}: {str(exc)[:200]}"
            got = {inp.index: mock_insight(inp, courses, "fallback", err) for inp in batch}
        return {inp.index: got.get(inp.index) or mock_insight(
            inp, courses, "fallback", "Gemini 응답에 이 파일이 빠져 규칙 기반으로 분석") for inp in batch}

    # 묶음들을 동시에 보낸다 → 전체 시간 ≈ 가장 느린 묶음 하나의 시간
    batches = _make_batches(items)
    results: dict[int, Insight] = {}
    workers = min(settings.llm_concurrency, len(batches)) or 1
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(run, b): b for b in batches}
    # 어디서 멈추든(네트워크·SDK 내부 등) 정한 시간이 지나면 기다리지 않는다 (시연이 멈추지 않도록)
    done, not_done = wait(futures, timeout=settings.llm_total_budget_seconds + 5)
    for fut in done:
        results.update(fut.result())
    if not_done:
        log.warning("AI 분석이 %.0f초 안에 끝나지 않은 묶음 %d개 → 규칙 기반으로 마무리",
                    settings.llm_total_budget_seconds, len(not_done))
        for fut in not_done:
            fut.cancel()
            for inp in futures[fut]:
                results[inp.index] = mock_insight(inp, courses, "fallback", "AI 응답 시간 초과로 규칙 기반으로 분석")
    pool.shutdown(wait=False, cancel_futures=True)
    return results


def run_with_limit(fn, seconds: float):
    """fn()을 따로 실행하고 seconds가 지나면 기다리지 않고 TimeoutError를 낸다."""
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(fn)
    try:
        return fut.result(timeout=seconds)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
