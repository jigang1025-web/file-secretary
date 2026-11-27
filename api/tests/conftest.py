"""테스트 공통 준비물.

- 테스트마다 새 DB(SQLite 파일)와 새 '정리 폴더'를 만든다.
- TEST_DATABASE_URL을 주면 PostgreSQL로도 같은 테스트를 돌릴 수 있다.
- fake_gemini: 진짜 google-genai SDK가 로컬 가짜 서버로 요청하게 해서, 보내는 내용(이미지·민감 정보 제외 등)을 검사한다.
"""
from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./.pytest-secretary.db")
os.environ["LLM_MODE"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import db  # noqa: E402
from app.config import settings  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SAMPLES = REPO / "demo" / "samples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
API_KEY = "test-key"


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.setattr(settings, "target_dir", target)
    monkeypatch.setattr(settings, "samples_dir", SAMPLES)
    monkeypatch.setattr(settings, "llm_mode", "mock")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "gemini_base_url", "")
    monkeypatch.setattr(settings, "api_key", API_KEY)

    url = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    engine = db.make_engine(url)
    if url.startswith("postgresql"):
        db.Base.metadata.drop_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    db.init_db()
    yield target
    engine.dispose()


@pytest.fixture()
def session(app_env):
    with db.SessionLocal() as s:
        yield s


@pytest.fixture()
def client(app_env):
    from app.main import app

    with TestClient(app, headers={"X-API-Key": API_KEY}) as c:
        yield c


@pytest.fixture()
def demo_target(app_env):
    from app.demo import reset_demo

    reset_demo(app_env, SAMPLES)
    return app_env


# ---------------------------------------------------------------------------
# 가짜 Gemini 서버
# ---------------------------------------------------------------------------
class FakeGemini:
    def __init__(self):
        self.requests: list[dict] = []
        self.fail_with: int | None = None
        self.fail_models: dict[str, int] = {}  # 모델별로 실패시키기 (예비 모델 테스트)
        self.file_responder = self.default_files
        self.search_responder = self.default_search

    @staticmethod
    def texts(body: dict) -> str:
        parts = body["input"][0]["content"] if body["input"] and "content" in body["input"][0] else body["input"]
        return "\n".join(p.get("text", "") for p in parts if p.get("type") == "text")

    @staticmethod
    def default_files(indexes: list[int], body: dict) -> dict:
        return {"files": [{"index": i, "category": "문서", "course": "", "title": f"AI 제목 {i}",
                           "date": "", "summary": "AI 요약", "keywords": ["AI"]} for i in indexes]}

    @staticmethod
    def default_search(ids: list[int], body: dict) -> dict:
        return {"answer": "찾았습니다.", "results": [{"id": ids[0], "reason": "가장 비슷함"}] if ids else []}

    def respond(self, body: dict) -> dict:
        text = self.texts(body)
        if "검색 비서" in body.get("system_instruction", ""):
            ids = [int(x) for x in re.findall(r"id=(\d+)", text)]
            return self.search_responder(ids, body)
        indexes = [int(x) for x in re.findall(r"\[파일 index=(\d+)\]", text)]
        return self.file_responder(indexes, body)


@pytest.fixture()
def fake_gemini(app_env, monkeypatch):
    fake = FakeGemini()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
            fake.requests.append({"path": self.path, "key": self.headers.get("x-goog-api-key"), "body": body})
            code = fake.fail_models.get(body.get("model")) or fake.fail_with
            if code:
                data = json.dumps({"error": {"code": code, "message": "boom", "status": "INTERNAL"}})
                self.send_response(code)
            else:
                out = json.dumps(fake.respond(body), ensure_ascii=False)
                data = json.dumps({"id": "fake", "steps": [
                    {"type": "model_output", "content": [{"type": "text", "text": out}]}]})
                self.send_response(200)
            raw = data.encode()
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "gemini_base_url", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(settings, "gemini_api_key", "fake-key")
    monkeypatch.setattr(settings, "llm_mode", "gemini")
    monkeypatch.setattr(settings, "llm_timeout_seconds", 10)
    monkeypatch.setattr(settings, "llm_retry_attempts", 1)  # 테스트에서는 다시 시도하지 않음 (빠르게)
    monkeypatch.setattr(settings, "llm_total_budget_seconds", 60)
    monkeypatch.setattr(settings, "llm_cache", False)  # 저장 결과 재사용은 해당 테스트에서만
    monkeypatch.setattr(settings, "llm_concurrency", 1)  # 요청 순서를 검사하는 테스트를 위해 기본은 차례로
    monkeypatch.setattr(settings, "gemini_fallback_models", [])  # 예비 모델은 해당 테스트에서만
    from app import analyzer
    monkeypatch.setattr(analyzer, "_active_model", None)
    yield fake
    server.shutdown()
