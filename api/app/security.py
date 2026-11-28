"""보안: ① API 키 인증(+ 파일 열기용 서명 링크) ② 민감 파일 판별 ③ AI로 보내기 전 개인정보 가리기(masking).

Gemini 무료 등급 약관에는 '보낸 내용이 제품 개선에 쓰이고 사람이 검토할 수 있으니
민감한 정보는 보내지 말라'고 적혀 있다. 그래서
  - 신분증·증명서·통장 사본처럼 민감한 파일은 내용을 아예 보내지 않고,
  - 일반 문서도 전화번호·이메일·계좌번호 같은 값은 [MASKED]로 가린 뒤 보낸다.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from .config import settings


# ---------------------------------------------------------------------------
# ① API 키 인증 (X-API-Key 헤더)
# ---------------------------------------------------------------------------
def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:  # 키를 설정하지 않은 개발 환경에서는 인증 생략
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="X-API-Key 헤더가 없거나 틀렸습니다.")


FILE_LINK_SECONDS = 3600          # 대시보드가 만든 '파일 열기' 링크의 유효 시간
FILE_LINK_MAX_SECONDS = 7 * 24 * 3600


def file_link_signature(file_id: int, exp: int) -> str:
    """브라우저에서 헤더 없이 파일을 열 수 있게 하는 서명 (HMAC-SHA256, 키 = API 키)."""
    key = (settings.api_key or "local-dev").encode()
    return hmac.new(key, f"file:{file_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def check_file_link(file_id: int, exp: int, sig: str, now: float | None = None) -> None:
    """서명이 맞고 만료 전인지 확인. API 키를 쓰지 않는 개발 환경에서는 통과."""
    if not settings.api_key:
        return
    now = time.time() if now is None else now
    if not (now <= exp <= now + FILE_LINK_MAX_SECONDS) or not hmac.compare_digest(sig, file_link_signature(file_id, exp)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="파일 열기 링크가 틀렸거나 만료되었습니다. 검색을 다시 해 주세요.")


# ---------------------------------------------------------------------------
# ② 민감 정보 패턴
# ---------------------------------------------------------------------------
# 주민등록번호(외국인등록번호 포함): 900101-1234567, 일부를 가린 900101-1****** 도 민감 서류로 본다
RRN = re.compile(
    r"(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\s?[-–]\s?[1-8](?:\d{6}|[*xX●○]{6})(?!\d)")
# 카드번호: 4자리씩 4묶음 (룬 알고리즘으로 한 번 더 확인)
CARD = re.compile(r"(?<!\d)(?:\d{4}[- ]){3}\d{4}(?!\d)")
# 계좌번호처럼 보이는 숫자 묶음 (전화번호와 헷갈리므로 주변에 '계좌·예금주·은행' 같은 단어가 있을 때만 인정)
ACCOUNT = re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,7}(?:-\d{1,3})?(?!\d)")
ACCOUNT_CONTEXT = re.compile(r"계좌|예금주|은행|통장|입금|송금|account", re.I)
PHONE = re.compile(r"(?<!\d)01[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# 파일 이름이나 문서 첫머리에 이 단어가 있으면 민감 서류로 본다
SENSITIVE_KEYWORDS = [
    "주민등록증", "주민등록등본", "주민등록초본", "운전면허증", "신분증", "여권", "외국인등록증",
    "가족관계증명서", "기본증명서", "혼인관계증명서", "입양관계증명서",
    "통장사본", "통장 사본", "계좌사본", "통장표지",
    "건강보험자격득실", "진단서", "처방전", "소득금액증명", "소득증명",
]


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_phone_like(text: str) -> bool:
    return bool(re.fullmatch(r"0\d{1,2}-\d{3,4}-\d{4}", text))


def find_account_numbers(text: str) -> list[str]:
    found = []
    for m in ACCOUNT.finditer(text):
        if _is_phone_like(m.group()):
            continue
        window = text[max(0, m.start() - 40): m.end() + 40]
        if ACCOUNT_CONTEXT.search(window):
            found.append(m.group())
    return found


@dataclass
class SensitiveCheck:
    sensitive: bool
    reason: str = ""


def detect_sensitive(name: str, text: str = "", extra_keywords: list[str] | None = None) -> SensitiveCheck:
    """파일 이름과 내용(글자)을 보고 민감 서류인지 판단한다."""
    keywords = SENSITIVE_KEYWORDS + [k.strip() for k in (extra_keywords or []) if k.strip()]
    compact_name = name.replace(" ", "")
    for kw in keywords:
        if kw.replace(" ", "") in compact_name:
            return SensitiveCheck(True, f"파일 이름에 '{kw}'")
    if text:
        if RRN.search(text):
            return SensitiveCheck(True, "주민등록번호 형식의 숫자")
        if any(luhn_ok(m.group()) for m in CARD.finditer(text)):
            return SensitiveCheck(True, "카드번호 형식의 숫자")
        if find_account_numbers(text):
            return SensitiveCheck(True, "계좌번호")
        head = text[:300].replace(" ", "")
        for kw in keywords:
            if kw.replace(" ", "") in head:
                return SensitiveCheck(True, f"문서 첫머리에 '{kw}'")
    return SensitiveCheck(False)


# ---------------------------------------------------------------------------
# ③ 가리기
# ---------------------------------------------------------------------------
def mask_text(text: str) -> tuple[str, int]:
    """AI로 보내기 전에 개인정보로 보이는 값을 [MASKED]로 바꾼다. (가린 문자열, 가린 개수)"""
    count = 0

    def repl(_m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[MASKED]"

    text = RRN.sub(repl, text)
    text = CARD.sub(lambda m: repl(m) if luhn_ok(m.group()) else m.group(), text)
    for acc in set(find_account_numbers(text)):
        n = text.count(acc)
        text = text.replace(acc, "[MASKED]")
        count += n
    text = PHONE.sub(repl, text)
    text = EMAIL.sub(repl, text)
    return text, count
