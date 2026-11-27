"""정리 계획을 실제로 적용(파일 이동)하고, 되돌리는 부분.

안전 원칙
- 사용자가 '포함'으로 남긴 항목만 옮긴다. 파일을 지우는 기능은 없다.
- 이미 같은 이름이 있으면 덮어쓰지 않고 번호를 붙인다.
- 계획을 만든 뒤 파일이 바뀌었거나(크기·수정 시각) 사라졌으면 건너뛴다.
- 모든 이동을 기록해 두었다가 '되돌리기'에서 반대로 옮긴다.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Batch, FileRecord, Move, Plan
from .planner import rel, safe_join, unique_name


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError(str(dst))
    try:
        os.rename(src, dst)
    except OSError:
        shutil.move(str(src), str(dst))  # 다른 드라이브로 옮길 때


def _update_record_path(session: Session, old_rel: str, new_rel: str) -> None:
    rec = session.scalars(select(FileRecord).where(FileRecord.path_rel == old_rel)).first()
    if rec is None:
        return
    clash = session.scalars(select(FileRecord).where(FileRecord.path_rel == new_rel)).first()
    if clash is not None and clash.id != rec.id:
        session.delete(clash)
        session.flush()
    rec.path_rel = new_rel


def apply_plan(session: Session, plan: Plan, root: Path) -> Batch:
    if plan.status != "draft":
        raise ValueError(f"이미 처리된 계획입니다 (상태: {plan.status}).")
    root = root.resolve()
    batch = Batch(plan_id=plan.id, moved=0, skipped=0)
    session.add(batch)
    taken: set[str] = set()
    for item in plan.items:
        if not item.include:
            continue
        src = safe_join(root, item.src_rel)
        dest_dir = safe_join(root, item.dest_dir) if item.dest_dir else root
        move = Move(item_id=item.id, src_rel=item.src_rel, dst_rel="")
        batch.moves.append(move)
        if not src.exists():
            move.status, move.error = "skipped", "파일이 없어졌습니다."
            batch.skipped += 1
            continue
        st = src.stat()
        if st.st_size != item.size or abs(st.st_mtime - item.mtime) > 2:
            move.status, move.error = "skipped", "계획을 만든 뒤 파일이 바뀌었습니다. 다시 살펴보기를 해 주세요."
            batch.skipped += 1
            continue
        name = unique_name(dest_dir, item.new_name or src.name, taken)
        dst = dest_dir / name
        if dst == src:
            move.status, move.error = "skipped", "이미 같은 위치·이름입니다."
            batch.skipped += 1
            continue
        try:
            _move(src, dst)
        except OSError as exc:
            move.status, move.error = "skipped", f"옮기지 못함: {type(exc).__name__}"
            batch.skipped += 1
            continue
        move.dst_rel = rel(root, dst)
        move.status = "moved"
        batch.moved += 1
        _update_record_path(session, item.src_rel, move.dst_rel)
    plan.status = "applied"
    session.commit()
    session.refresh(batch)
    return batch


def _remove_empty_dirs(start: Path, root: Path) -> None:
    """되돌린 뒤 비어 버린 폴더를 정리 폴더 바로 아래까지 지운다 (빈 폴더만)."""
    current = start
    while current != root and current.is_relative_to(root):
        try:
            current.rmdir()  # 비어 있지 않으면 OSError → 멈춤
        except OSError:
            break
        current = current.parent


def undo_batch(session: Session, batch: Batch, root: Path) -> Batch:
    if batch.undone_at is not None:
        raise ValueError("이미 되돌린 기록입니다.")
    root = root.resolve()
    for move in reversed(batch.moves):
        if move.status != "moved":
            continue
        src = safe_join(root, move.src_rel)
        dst = safe_join(root, move.dst_rel)
        if not dst.exists():
            move.status, move.error = "undo_failed", "정리된 파일을 찾을 수 없습니다 (옮기거나 지웠나요?)."
            continue
        if src.exists():
            move.status, move.error = "undo_failed", "원래 자리에 같은 이름의 파일이 생겼습니다."
            continue
        try:
            _move(dst, src)
        except OSError as exc:
            move.status, move.error = "undo_failed", f"되돌리지 못함: {type(exc).__name__}"
            continue
        move.status = "undone"
        _update_record_path(session, move.dst_rel, move.src_rel)
        _remove_empty_dirs(dst.parent, root)
    batch.undone_at = datetime.now(timezone.utc)
    plan = session.get(Plan, batch.plan_id)
    if plan is not None:
        plan.status = "undone"
    session.commit()
    session.refresh(batch)
    return batch
