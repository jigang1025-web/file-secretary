"""환경변수로 바꾸는 설정 값 모음 (.env → docker compose → 컨테이너 환경변수).

LLM_MODE
  auto   : GEMINI_API_KEY가 있으면 Gemini, 없으면 규칙 기반(mock) (기본값)
  gemini : 항상 Gemini 호출 (실패하면 규칙 기반으로 대체)
  mock   : 항상 규칙 기반 (API 키 없이 시연·테스트할 때)
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        """환경변수를 다시 읽는다 (테스트에서 값을 바꿀 때 사용)."""
        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        # 기본 모델이 붐비거나(503)·한도 초과(429)·응답 지연이면 차례로 시도할 예비 모델 (쉼표로 구분)
        self.gemini_fallback_models = [
            m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash").split(",")
            if m.strip()]
        # 테스트에서 가짜 Gemini 서버로 보낼 때만 사용 (보통은 비워 둔다)
        self.gemini_base_url = os.getenv("GEMINI_BASE_URL", "")
        self.llm_mode = os.getenv("LLM_MODE", "auto").strip().lower()
        # 응답이 이 시간(초) 안에 안 오면 포기하고 예비 모델로 넘어간다 (붐비는 모델에 오래 매달리지 않도록)
        self.llm_timeout_seconds = float(os.getenv("LLM_TIMEOUT_SECONDS", "25"))
        self.llm_batch_size = max(1, _int("LLM_BATCH_SIZE", 8))
        # 호출 한도(429)·일시 오류(5xx) 때 SDK가 다시 시도하는 총 횟수 (처음 요청 포함)
        self.llm_retry_attempts = max(1, _int("LLM_RETRY_ATTEMPTS", 2))
        # 묶음을 동시에 몇 개까지 보낼지 (1이면 차례로). 무료 한도(분당 요청 수)를 생각해 4 정도가 적당
        # Gemini 결과를 파일 내용별로 저장해 두고 같은 파일은 다시 묻지 않는다 (무료 한도 절약·즉시 응답)
        self.llm_cache = _bool("LLM_CACHE", True)
        # 한 번 살펴볼 때 AI 분석에 쓰는 최대 시간(초). 넘으면 남은 파일은 규칙 기반으로 마무리 (시연이 멈추지 않도록)
        self.llm_total_budget_seconds = float(os.getenv("LLM_TOTAL_BUDGET_SECONDS", "60"))
        # 모델이 답하기 전에 '생각'하는 정도 (minimal·low·medium·high). 파일 분류는 low면 충분하고 훨씬 빠르다. 비우면 모델 기본값
        self.llm_thinking_level = os.getenv("LLM_THINKING_LEVEL", "low").strip().lower()
        self.llm_concurrency = max(1, _int("LLM_CONCURRENCY", 4))
        # 우리 API를 보호하는 키. 비어 있으면 인증을 생략한다(개발용).
        self.api_key = os.getenv("SECRETARY_API_KEY", "")
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///./secretary.db")
        # 정리할 폴더. 도커에서는 호스트 폴더가 /data/target 으로 연결(bind mount)된다.
        self.target_dir = Path(os.getenv("TARGET_DIR", "./target")).expanduser()
        # 연습용 샘플 파일 위치 (연습 폴더 초기화 기능에서 사용)
        self.samples_dir = Path(os.getenv("SAMPLES_DIR", "../demo/samples")).expanduser()
        self.max_files_per_scan = max(1, _int("MAX_FILES_PER_SCAN", 200))
        self.max_text_chars = max(500, _int("MAX_TEXT_CHARS", 4000))
        # 이미지 속 글자를 내 컴퓨터에서 읽어(OCR) 민감 정보가 보이면 AI로 보내지 않는다.
        self.ocr_enabled = _bool("OCR_ENABLED", True) and shutil.which("tesseract") is not None
        self.old_installer_days = max(1, _int("OLD_INSTALLER_DAYS", 30))
        # 폴더 감시 데몬(app/watcher.py): 확인 주기, 실패한 파일을 다시 시도하기까지의 시간(초)
        self.watch_interval_seconds = max(3, _int("WATCH_INTERVAL_SECONDS", 15))
        self.watch_retry_seconds = max(30, _int("WATCH_RETRY_SECONDS", 600))
        # 감시 데몬이 파일을 모두 읽은 뒤, 자주 쓰는 검색 질문의 AI 답을 미리 받아 둔다 ('|'로 구분, 비우면 끔)
        self.warm_queries = [q.strip() for q in os.getenv(
            "SEARCH_WARMUP_QUERIES", "기말 프로젝트 공지|카페 와이파이 비밀번호|이번 달 영수증|자료구조 시험 범위").split("|") if q.strip()]
        self.warm_timeout_seconds = float(os.getenv("SEARCH_WARMUP_TIMEOUT_SECONDS", "90"))
        self.extract_workers = max(1, _int("EXTRACT_WORKERS", 4))

    @property
    def effective_llm_mode(self) -> str:
        if self.llm_mode == "mock":
            return "mock"
        if self.llm_mode == "gemini":
            return "gemini"
        return "gemini" if self.gemini_api_key else "mock"

    @property
    def use_gemini(self) -> bool:
        return self.effective_llm_mode == "gemini" and bool(self.gemini_api_key)


settings = Settings()
