"""파일 정리 비서 REST API (FastAPI).

| 메서드 | 경로                                   | 역할                                   |
|--------|----------------------------------------|----------------------------------------|
| POST   | /api/v1/plans                          | 폴더를 살펴보고 정리 계획 만들기 (C)     |
| GET    | /api/v1/plans, /api/v1/plans/{id}      | 계획 목록·상세 (R)                      |
| PATCH  | /api/v1/plans/{id}/items/{item_id}     | 새 이름·폴더·포함 여부 고치기 (U)        |
| DELETE | /api/v1/plans/{id}                     | 적용 전 계획 취소 (D)                   |
| POST   | /api/v1/plans/{id}/apply               | 계획대로 파일 옮기기                    |
| GET    | /api/v1/batches                        | 정리 기록                              |
| POST   | /api/v1/batches/{id}/undo              | 되돌리기                               |
| GET    | /api/v1/files, /api/v1/files/{id}/content | 색인된 파일 목록, 파일 내려받기       |
| GET    | /api/v1/search?q=                      | 말로 검색                              |
| GET    | /api/v1/tree, /api/v1/stats            | 폴더 구조·통계 (화면용)                 |
| GET/PUT| /api/v1/settings                       | 설정 조회·전체 교체                     |
| POST   | /api/v1/demo/reset                     | 연습 폴더 초기화                        |

실행 후 http://localhost:8000/docs 에서 자동 생성된 API 문서를 볼 수 있다.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import demo, mover, planner
from .config import settings
from .db import Batch, FileRecord, Plan, PlanItem, get_app_settings, get_session, init_db
from .schemas import (BatchOut, FileOut, PlanCreate, PlanItemOut, PlanItemUpdate, PlanOut, PlanSummary,
                      SearchHit, SearchOut, SettingsIn, SettingsOut, StatsOut, TreeNode)
from .search import search as run_search
from .security import require_api_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def target_root() -> Path:
    root = settings.target_dir.resolve()
    if not root.is_dir():
        raise HTTPException(status_code=500, detail=f"정리 폴더가 없습니다: {root} (.env의 HOST_TARGET_DIR 확인)")
    return root


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="파일 정리 비서 API",
    version="0.1.0",
    description="생성 AI가 파일 내용을 읽고 이름을 짓고, 폴더별로 정리하고, 말로 찾아 주는 서비스",
    lifespan=lifespan,
)


@app.get("/health", tags=["system"])
def health():
    """도커 healthcheck용 (인증 없음)."""
    return {"status": "ok", "llm_mode": settings.effective_llm_mode, "model": settings.gemini_model,
            "ocr": settings.ocr_enabled}


router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


# ---------------------------------------------------------------------------
# 설정
# ---------------------------------------------------------------------------
def _settings_out(session: Session) -> SettingsOut:
    cfg = get_app_settings(session)
    root = settings.target_dir.resolve()
    return SettingsOut(
        courses=cfg.courses or [], name_pattern=cfg.name_pattern, analyze_images=cfg.analyze_images,
        extra_sensitive_keywords=cfg.extra_sensitive_keywords or [], target_dir=str(root),
        llm_mode=settings.effective_llm_mode, gemini_model=settings.gemini_model,
        ocr_enabled=settings.ocr_enabled,
        demo_reset_available=(settings.samples_dir / "manifest.json").exists()
        and root.is_dir() and demo.is_resettable(root))


@router.get("/settings", response_model=SettingsOut, tags=["settings"])
def read_settings(session: Session = Depends(get_session)):
    return _settings_out(session)


@router.put("/settings", response_model=SettingsOut, tags=["settings"])
def replace_settings(body: SettingsIn, session: Session = Depends(get_session)):
    """PUT은 설정 전체를 교체한다 (같은 요청을 여러 번 보내도 결과가 같음 = 멱등)."""
    cfg = get_app_settings(session)
    cfg.courses = [c.strip() for c in body.courses if c.strip()]
    cfg.name_pattern = body.name_pattern
    cfg.analyze_images = body.analyze_images
    cfg.extra_sensitive_keywords = [k.strip() for k in body.extra_sensitive_keywords if k.strip()]
    session.commit()
    return _settings_out(session)


# ---------------------------------------------------------------------------
# 정리 계획
# ---------------------------------------------------------------------------
def _get_plan(session: Session, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"{plan_id}번 계획이 없습니다.")
    return plan


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED, tags=["plans"])
def create_plan(body: PlanCreate | None = None, session: Session = Depends(get_session)):
    """정리 폴더 맨 위의 파일을 살펴보고 정리 계획을 만든다. 파일은 아직 옮기지 않는다."""
    root = target_root()
    for old in session.scalars(select(Plan).where(Plan.status == "draft")).all():
        old.status = "cancelled"  # 적용하지 않은 예전 계획은 취소
    session.commit()
    return planner.build_plan(session, root, get_app_settings(session), (body.max_files if body else None))


@router.get("/plans", response_model=list[PlanSummary], tags=["plans"])
def list_plans(limit: int = Query(20, ge=1, le=200), session: Session = Depends(get_session)):
    return session.scalars(select(Plan).order_by(Plan.id.desc()).limit(limit)).all()


@router.get("/plans/{plan_id}", response_model=PlanOut, tags=["plans"])
def get_plan(plan_id: int, session: Session = Depends(get_session)):
    return _get_plan(session, plan_id)


@router.patch("/plans/{plan_id}/items/{item_id}", response_model=PlanItemOut, tags=["plans"])
def update_item(plan_id: int, item_id: int, body: PlanItemUpdate, session: Session = Depends(get_session)):
    """사용자가 미리보기에서 고친 새 이름·폴더·포함 여부를 저장 (보낸 값만 바꾸는 부분 수정)."""
    plan = _get_plan(session, plan_id)
    if plan.status != "draft":
        raise HTTPException(status_code=409, detail="이미 적용했거나 취소한 계획은 고칠 수 없습니다.")
    item = session.get(PlanItem, item_id)
    if item is None or item.plan_id != plan_id:
        raise HTTPException(status_code=404, detail=f"{item_id}번 항목이 없습니다.")
    data = body.model_dump(exclude_unset=True)
    if data.get("new_name") is not None:
        name = planner.sanitize_component(data["new_name"], 150)
        if not name:
            raise HTTPException(status_code=422, detail="파일 이름이 비어 있습니다.")
        if item.ext and not name.lower().endswith(item.ext):
            name += item.ext  # 확장자를 지웠으면 원래 확장자를 붙인다
        item.new_name = name
    if data.get("dest_dir") is not None:
        item.dest_dir = planner.sanitize_dest_dir(data["dest_dir"])
    if data.get("include") is not None:
        item.include = data["include"]
    session.commit()
    return item


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["plans"])
def cancel_plan(plan_id: int, session: Session = Depends(get_session)):
    plan = _get_plan(session, plan_id)
    if plan.status != "draft":
        raise HTTPException(status_code=409, detail="적용 전 계획만 취소할 수 있습니다.")
    plan.status = "cancelled"
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/plans/{plan_id}/apply", response_model=BatchOut, status_code=status.HTTP_201_CREATED,
             tags=["plans"])
def apply_plan(plan_id: int, session: Session = Depends(get_session)):
    plan = _get_plan(session, plan_id)
    try:
        return mover.apply_plan(session, plan, target_root())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 정리 기록·되돌리기
# ---------------------------------------------------------------------------
@router.get("/batches", response_model=list[BatchOut], tags=["batches"])
def list_batches(limit: int = Query(20, ge=1, le=200), session: Session = Depends(get_session)):
    return session.scalars(select(Batch).order_by(Batch.id.desc()).limit(limit)).all()


@router.post("/batches/{batch_id}/undo", response_model=BatchOut, tags=["batches"])
def undo(batch_id: int, session: Session = Depends(get_session)):
    batch = session.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"{batch_id}번 기록이 없습니다.")
    try:
        return mover.undo_batch(session, batch, target_root())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 파일 색인·검색
# ---------------------------------------------------------------------------
@router.get("/files", response_model=list[FileOut], tags=["files"])
def list_files(category: str | None = None, course: str | None = None,
               limit: int = Query(200, ge=1, le=5000), session: Session = Depends(get_session)):
    stmt = select(FileRecord).order_by(FileRecord.id.desc()).limit(limit)
    if category:
        stmt = stmt.where(FileRecord.category == category)
    if course:
        stmt = stmt.where(FileRecord.course == course)
    return session.scalars(stmt).all()


@router.get("/files/{file_id}/content", tags=["files"])
def download_file(file_id: int, session: Session = Depends(get_session)):
    rec = session.get(FileRecord, file_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="파일 기록이 없습니다.")
    try:
        path = planner.safe_join(target_root(), rec.path_rel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="파일이 그 위치에 없습니다 (옮겼거나 지웠나요?).")
    return FileResponse(path, filename=path.name)


@router.get("/search", response_model=SearchOut, tags=["files"])
def search(q: str = Query(..., min_length=1, max_length=200), limit: int = Query(8, ge=1, le=30),
           session: Session = Depends(get_session)):
    answer, hits, source = run_search(session, q, limit)
    return SearchOut(query=q, answer=answer, source=source,
                     results=[SearchHit(file=FileOut.model_validate(h.record), reason=h.reason,
                                        score=round(h.score, 3)) for h in hits])


# ---------------------------------------------------------------------------
# 화면용: 폴더 구조·통계
# ---------------------------------------------------------------------------
def _tree(path: Path, root: Path, depth: int, budget: list[int]) -> TreeNode:
    node = TreeNode(name=path.name or str(path), path=planner.rel(root, path) if path != root else "",
                    is_dir=path.is_dir())
    if not node.is_dir:
        node.size = path.stat().st_size
        return node
    if depth <= 0:
        return node
    entries = sorted((p for p in path.iterdir() if not p.name.startswith(".")),
                     key=lambda p: (not p.is_dir(), p.name.lower()))
    for p in entries:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        node.children.append(_tree(p, root, depth - 1, budget))
    return node


@router.get("/tree", response_model=TreeNode, tags=["system"])
def tree(depth: int = Query(3, ge=1, le=6)):
    root = target_root()
    return _tree(root, root, depth, [500])


@router.get("/stats", response_model=StatsOut, tags=["system"])
def stats(session: Session = Depends(get_session)):
    root = target_root()
    loose = sum(1 for p in root.iterdir() if p.is_file() and not p.name.startswith("."))
    rows = session.execute(select(FileRecord.category, func.count()).group_by(FileRecord.category)).all()
    organized = session.scalar(select(func.count()).select_from(FileRecord).where(FileRecord.path_rel.contains("/")))
    last = session.scalar(select(Batch.id).order_by(Batch.id.desc()).limit(1))
    return StatsOut(target_dir=str(root), loose_files=loose, organized_files=organized or 0,
                    by_category={c: n for c, n in rows}, last_batch_id=last)


# ---------------------------------------------------------------------------
# 연습 폴더
# ---------------------------------------------------------------------------
@router.post("/demo/reset", tags=["demo"])
def demo_reset(session: Session = Depends(get_session)):
    """연습 폴더를 '정리 전' 상태로 되돌린다 (발표 리허설용). 진짜 폴더에서는 동작하지 않는다."""
    root = settings.target_dir.resolve()
    try:
        count = demo.reset_demo(root, settings.samples_dir)
    except demo.NotDemoFolder as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # 연습 폴더 기준의 기록은 의미가 없어지므로 비운다
    for model in (FileRecord, Batch, Plan):
        for row in session.scalars(select(model)).all():
            session.delete(row)
    session.commit()
    return {"copied": count}


app.include_router(router)
