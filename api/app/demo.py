"""연습 폴더 초기화: 발표·연습 때마다 '지저분한 다운로드 폴더'를 다시 만든다.

안전장치: 표시 파일(.file-secretary-demo)이 있는 폴더이거나, 숨김 파일 말고는 비어 있는 폴더에서만 동작한다.
→ 실수로 진짜 다운로드 폴더를 연결해도 그 안의 파일을 지우지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .planner import MARKER


class NotDemoFolder(Exception):
    pass


def is_resettable(target: Path) -> bool:
    if (target / MARKER).exists():
        return True
    return target.is_dir() and all(p.name.startswith(".") for p in target.iterdir())


def reset_demo(target: Path, samples: Path) -> int:
    target = target.resolve()
    manifest_path = samples / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"샘플 목록이 없습니다: {manifest_path}")
    target.mkdir(parents=True, exist_ok=True)
    if not is_resettable(target):
        raise NotDemoFolder("연습 폴더가 아니어서 초기화하지 않았습니다 (진짜 폴더 보호).")

    for p in target.iterdir():  # 숨김 파일(.gitkeep, 표시 파일)은 남긴다
        if p.name.startswith("."):
            continue
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p)
        else:
            p.unlink()
    (target / MARKER).write_text("이 폴더는 파일 정리 비서의 연습 폴더입니다.\n", encoding="utf-8")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    now = time.time()
    count = 0
    for entry in manifest["files"]:
        src = samples / entry["sample"]
        dst = target / entry["name"]
        if not src.exists() or dst.exists():
            continue
        shutil.copyfile(src, dst)
        t = now - float(entry.get("days_ago", 0)) * 86400 - float(entry.get("minutes", 0)) * 60
        os.utime(dst, (t, t))
        count += 1
    return count
