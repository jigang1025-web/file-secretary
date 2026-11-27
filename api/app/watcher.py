"""폴더 감시 데몬 — 정리 폴더에 새 파일이 들어오면 미리 Gemini로 분석해 저장해 둔다.

리눅스 강의의 daemon(항상 실행되는 프로그램)처럼 따로 떠서 계속 돈다:
    python -m app.watcher          (docker compose의 watcher 서비스)

왜 필요한가
- Gemini 무료 등급은 응답이 느리고(요청당 십수 초) 하루 요청 수가 정해져 있다.
- 파일이 들어올 때마다 조금씩 미리 분석해 두면, 사용자가 '폴더 살펴보기'를 누를 때는
  저장된 결과(analysis_cache)를 바로 쓰므로 기다리지 않는다.

동작
1. WATCH_INTERVAL_SECONDS마다 정리 폴더 맨 위의 파일 목록을 본다 (Windows 폴더 연결에서는
   변경 알림이 오지 않을 수 있어 주기적으로 확인하는 polling 방식).
2. 크기·수정 시각이 한 번 더 확인해도 같으면(다운로드가 끝난 파일) 분석 대상으로 삼는다.
3. planner.prefetch()로 분석해 저장한다. 실패한 파일은 WATCH_RETRY_SECONDS 뒤에 다시 시도한다.
4. 상태를 watcher_status 표에 적어 대시보드가 "미리 분석 n/m"을 보여 준다.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from . import db
from .db import WatcherStatus, get_app_settings, init_db
from .planner import list_candidates, prefetch

log = logging.getLogger("app.watcher")
HEARTBEAT = Path(os.getenv("WATCH_HEARTBEAT", "/tmp/watcher.heartbeat"))


@dataclass
class WatchState:
    pending: dict[str, tuple[int, float]] = field(default_factory=dict)   # 처음 본 파일 (안정 확인 대기)
    done: dict[str, tuple[int, float]] = field(default_factory=dict)      # 분석 끝 (ai | local)
    failed: dict[str, tuple[tuple[int, float], float]] = field(default_factory=dict)  # 서명, 다시 시도할 시각


def scan_once(state: WatchState, root: Path, now: float | None = None) -> dict:
    """한 번 둘러보고 상태 요약을 돌려준다 (테스트에서 직접 부른다)."""
    now = time.time() if now is None else now
    files = list_candidates(root, settings.max_files_per_scan)
    current: dict[str, tuple[Path, tuple[int, float]]] = {}
    for p in files:
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        current[p.name] = (p, (st.st_size, st.st_mtime))
    # 사라진 파일(정리됨·삭제됨)은 잊는다
    for book in (state.pending, state.done, state.failed):
        for name in list(book):
            if name not in current:
                del book[name]

    ready_to_run: list[Path] = []
    for name, (p, sig) in current.items():
        if state.done.get(name) == sig:
            continue
        if name in state.failed:
            old_sig, retry_at = state.failed[name]
            if old_sig == sig:
                if now >= retry_at:          # 다시 시도할 시각이 됨 (이미 다운로드가 끝난 파일)
                    ready_to_run.append(p)
                continue
        if state.pending.get(name) == sig:   # 두 번 연속 같은 크기·시각 → 다운로드 완료로 본다
            ready_to_run.append(p)
        else:
            state.pending[name] = sig

    outcome: dict[str, str] = {}
    if ready_to_run:
        _write_status("analyzing", len(current), len(state.done), len(state.failed),
                      f"새 파일 {len(ready_to_run)}개를 미리 읽는 중")
        with db.SessionLocal() as session:
            cfg = get_app_settings(session)
            outcome = prefetch(session, root, cfg, ready_to_run)
        for p in ready_to_run:
            sig = current[p.name][1]
            state.pending.pop(p.name, None)
            if outcome.get(p.name, "failed") == "failed":
                state.failed[p.name] = (sig, now + settings.watch_retry_seconds)
                state.done.pop(p.name, None)
            else:
                state.done[p.name] = sig
                state.failed.pop(p.name, None)

    summary = {"loose": len(current), "ready": len(state.done), "failed": len(state.failed),
               "analyzed_now": sum(1 for v in outcome.values() if v != "failed")}
    if summary["loose"] == 0:
        msg = "정리할 새 파일이 없습니다"
    elif summary["ready"] >= summary["loose"]:
        msg = "새 파일을 모두 미리 읽었습니다"
    elif summary["failed"]:
        msg = f"{summary['failed']}개는 AI 응답이 없어 잠시 뒤 다시 시도합니다"
    else:
        msg = "새 파일을 확인하는 중입니다"
    _write_status("idle", summary["loose"], summary["ready"], summary["failed"], msg)
    return summary


def _write_status(state: str, loose: int, ready: int, failed: int, message: str) -> None:
    try:
        with db.SessionLocal() as session:
            row = session.get(WatcherStatus, 1) or WatcherStatus(id=1)
            row.state, row.loose, row.ready, row.failed, row.message = state, loose, ready, failed, message
            session.merge(row)
            session.commit()
    except Exception as exc:  # noqa: BLE001 — 상태 기록 실패가 감시를 멈추게 하지 않도록
        log.warning("상태 기록 실패: %s", exc)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    root = settings.target_dir.resolve()
    if not settings.use_gemini:
        log.info("Gemini를 쓰지 않는 설정(규칙 기반)이라 미리 분석할 일이 없습니다. 대기만 합니다.")
        _write_status("off", 0, 0, 0, "규칙 기반 모드라 미리 분석을 쓰지 않습니다")
    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)  # docker compose stop → 깔끔하게 종료
    signal.signal(signal.SIGINT, _stop)
    log.info("폴더 감시 시작: %s (%d초마다)", root, settings.watch_interval_seconds)
    state = WatchState()
    while not stopping:
        HEARTBEAT.touch()  # 컨테이너 healthcheck가 이 파일이 최근에 바뀌었는지 본다
        if settings.use_gemini and root.is_dir():
            try:
                summary = scan_once(state, root)
                if summary["analyzed_now"]:
                    log.info("미리 분석: %(analyzed_now)d개 (준비 %(ready)d/%(loose)d)", summary)
            except Exception:  # noqa: BLE001 — 한 번 실패해도 데몬은 계속 돈다
                log.exception("감시 중 오류 (다음 주기에 다시 시도)")
        for _ in range(settings.watch_interval_seconds):
            if stopping:
                break
            time.sleep(1)
    log.info("폴더 감시 종료")


if __name__ == "__main__":
    main()
