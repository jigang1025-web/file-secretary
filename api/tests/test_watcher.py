"""폴더 감시 데몬 — 새 파일을 미리 분석해 두면 '살펴보기'가 Gemini를 다시 부르지 않는다."""
import os
import time

from app import planner
from app.config import settings
from app.db import WatcherStatus, get_app_settings
from app.watcher import WatchState, scan_once


def _gemini_on():
    settings.llm_cache = True


def test_watcher_prefetches_new_files(session, app_env, fake_gemini):
    _gemini_on()
    (app_env / "notice.txt").write_text("오픈소스 프로그래밍 기말 프로젝트 공지", encoding="utf-8")
    (app_env / "memo.txt").write_text("자료구조 과제 메모", encoding="utf-8")
    state = WatchState()

    first = scan_once(state, app_env)            # 처음 본 파일은 다운로드 중일 수 있어 기다린다
    assert first["analyzed_now"] == 0 and fake_gemini.requests == []
    second = scan_once(state, app_env)           # 크기·시각이 그대로면 분석
    assert second["analyzed_now"] == 2 and second["ready"] == 2
    assert len(fake_gemini.requests) == 1

    third = scan_once(state, app_env)            # 이미 분석한 파일은 다시 보내지 않음
    assert third["analyzed_now"] == 0 and len(fake_gemini.requests) == 1

    # 사용자가 '폴더 살펴보기'를 누르면 저장된 결과를 써서 Gemini를 부르지 않는다
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    assert len(fake_gemini.requests) == 1
    assert all(i.source == "gemini" for i in plan.items)

    row = session.get(WatcherStatus, 1)
    session.refresh(row)
    assert row.ready == 2 and row.loose == 2


def test_watcher_skips_sensitive_and_retries_failures(session, app_env, fake_gemini):
    _gemini_on()
    settings.watch_retry_seconds = 60
    (app_env / "통장사본.txt").write_text("예금주 홍길동 계좌번호 123-456-789012", encoding="utf-8")
    (app_env / "memo.txt").write_text("기계학습 과제", encoding="utf-8")
    fake_gemini.fail_with = 400  # 다시 시도해도 안 되는 오류 → 실패로 기록
    state = WatchState()
    scan_once(state, app_env)
    summary = scan_once(state, app_env)
    assert summary["failed"] == 1 and summary["ready"] == 1  # 민감 파일은 AI 없이 '준비됨'
    sent = str([r["body"]["input"] for r in fake_gemini.requests])
    assert "123-456-789012" not in sent and "통장사본" not in sent

    calls = len(fake_gemini.requests)
    fake_gemini.fail_with = None
    scan_once(state, app_env, now=time.time() + 10)          # 다시 시도할 시각 전 → 보내지 않음
    assert len(fake_gemini.requests) == calls
    after = scan_once(state, app_env, now=time.time() + 120)  # 시각이 지나면 다시 시도
    assert after["failed"] == 0 and after["ready"] == 2


def test_watcher_waits_for_file_to_finish_downloading(session, app_env, fake_gemini):
    _gemini_on()
    f = app_env / "big.txt"
    f.write_text("일부만 받은 내용", encoding="utf-8")
    state = WatchState()
    scan_once(state, app_env)
    f.write_text("일부만 받은 내용 + 이어서 받은 내용", encoding="utf-8")  # 크기가 바뀜
    os.utime(f, (time.time() + 5, time.time() + 5))
    assert scan_once(state, app_env)["analyzed_now"] == 0
    assert scan_once(state, app_env)["analyzed_now"] == 1


def test_watcher_status_endpoint(client, app_env):
    res = client.get("/api/v1/watcher")
    assert res.status_code == 200 and res.json()["running"] is False
