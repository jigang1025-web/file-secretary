import hashlib

import pytest

from app import mover, planner
from app.db import get_app_settings


def snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_apply_and_undo_restores_everything(session, demo_target):
    before = snapshot(demo_target)
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    batch = mover.apply_plan(session, plan, demo_target)
    assert batch.moved == 26 and batch.skipped == 0
    loose = [p for p in demo_target.iterdir() if p.is_file() and not p.name.startswith(".")]
    assert loose == []
    assert sorted(before.values()) == sorted(snapshot(demo_target).values())  # 내용은 그대로, 위치만 바뀜

    mover.undo_batch(session, batch, demo_target)
    assert snapshot(demo_target) == before
    assert [p for p in demo_target.iterdir() if p.is_dir()] == []  # 만든 폴더도 정리


def test_skip_changed_file_and_excluded(session, app_env):
    (app_env / "a.txt").write_text("첫 내용", encoding="utf-8")
    (app_env / "b.txt").write_text("둘째 내용", encoding="utf-8")
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    items = {i.src_rel: i for i in plan.items}
    items["b.txt"].include = False
    session.commit()
    (app_env / "a.txt").write_text("계획을 만든 뒤 바뀐 내용입니다", encoding="utf-8")
    batch = mover.apply_plan(session, plan, app_env)
    assert batch.moved == 0 and batch.skipped == 1
    assert (app_env / "a.txt").exists() and (app_env / "b.txt").exists()


def test_never_overwrites(session, app_env):
    (app_env / "x.txt").write_text("메모 내용", encoding="utf-8")
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    item = plan.items[0]
    dest = app_env / item.dest_dir
    dest.mkdir(parents=True)
    (dest / item.new_name).write_text("원래 있던 파일", encoding="utf-8")
    batch = mover.apply_plan(session, plan, app_env)
    assert batch.moved == 1
    assert (dest / item.new_name).read_text(encoding="utf-8") == "원래 있던 파일"
    assert batch.moves[0].dst_rel.endswith(" (2).txt")


def test_apply_twice_rejected(session, app_env):
    (app_env / "x.txt").write_text("메모", encoding="utf-8")
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    batch = mover.apply_plan(session, plan, app_env)
    with pytest.raises(ValueError):
        mover.apply_plan(session, plan, app_env)
    mover.undo_batch(session, batch, app_env)
    with pytest.raises(ValueError):
        mover.undo_batch(session, batch, app_env)
