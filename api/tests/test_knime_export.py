"""KNIME 실습용 CSV 내보내기."""
import csv
import io

from app import planner
from app.config import settings
from app.db import get_app_settings


def _rows(text: str) -> list[dict]:
    assert text.startswith("﻿")
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def test_export_rule_mode_has_answers_and_features(client, demo_target):
    res = client.get("/api/v1/export/knime.csv")
    assert res.status_code == 200 and "text/csv" in res.headers["content-type"]
    rows = {r["file_name"]: r for r in _rows(res.text)}
    assert len(rows) == 26
    assert rows["KakaoTalk_20261103_153201234.jpg"]["name_type"] == "kakaotalk"
    assert rows["Screenshot_20261115-224512.png"]["name_type"] == "screenshot"
    assert rows["다운로드 (7).pdf"]["name_type"] == "generic"
    assert rows["다운로드 (7).pdf"]["true_category"] == "수업"
    assert rows["다운로드 (1).pdf"]["is_duplicate"] == "1"
    assert rows["통장사본.pdf"]["is_sensitive"] == "1" and rows["통장사본.pdf"]["rule_category"] == "개인서류"
    assert rows["ChromeSetup.exe"]["rule_category"] == "설치파일"
    assert all(r["ai_category"] == "" for r in rows.values())   # 규칙 기반 모드라 AI 결과 없음
    # 정답이 있는 파일(중복 제외) 중 규칙 기반이 맞힌 비율 — KNIME Scorer와 같은 계산
    judged = [r for r in rows.values() if r["true_category"] and r["is_duplicate"] == "0"]
    assert len(judged) == 24


def test_export_uses_cached_ai_without_calling_gemini(session, demo_target, fake_gemini, client):
    settings.llm_cache = True
    planner.build_plan(session, demo_target, get_app_settings(session))   # AI 결과 저장
    calls = len(fake_gemini.requests)
    rows = _rows(client.get("/api/v1/export/knime.csv").text)
    assert len(fake_gemini.requests) == calls                           # 내보내기는 Gemini를 부르지 않는다
    sent = [r for r in rows if r["ai_category"]]
    assert len(sent) == 21                                               # 민감 3 + 중복 2 제외
    assert all(r["ai_category"] == "문서" for r in sent)                 # 가짜 서버의 답
    secret = next(r for r in rows if r["file_name"] == "통장사본.pdf")
    assert secret["ai_category"] == ""
