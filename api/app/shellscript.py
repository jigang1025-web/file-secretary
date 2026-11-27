"""정리 계획·정리 기록을 리눅스 셸 스크립트로 바꾼다 (리눅스 강의의 mkdir -p, mv, 리다이렉션).

- 사용자가 '무엇이 어떻게 옮겨지는지'를 명령어 그대로 확인할 수 있다 (투명성).
- 스크립트를 내려받아 정리 폴더에서 직접 실행해도 같은 결과가 나온다:  bash 정리계획.sh
- 서비스와 같은 원칙: 지우는 명령(rm)은 쓰지 않고, mv -n 으로 같은 이름이 있으면 덮어쓰지 않는다.
"""
from __future__ import annotations

import shlex
from datetime import datetime

from .db import Batch, Plan

HEADER = """#!/bin/bash
# {title}
# 만든 시각: {when}
# 실행 방법: 정리 폴더에서  bash {filename}
#   - mkdir -p : 폴더가 없으면 중간 폴더까지 한 번에 만든다
#   - mv -n    : 옮기면서 이름을 바꾸고, 같은 이름의 파일이 이미 있으면 덮어쓰지 않는다
#   - 지우는 명령(rm)은 쓰지 않는다
set -u
LOG="정리기록.log"
echo "== $(date '+%F %T') {title} ==" >> "$LOG"
"""


def _q(path: str) -> str:
    return shlex.quote(path)


def _move_line(src: str, dst: str) -> str:
    # 성공하면 기록 파일에 덧붙이고(>>), 실패 메시지는 화면과 기록 파일 모두에 남긴다(2>&1 | tee -a)
    return (f"mv -n -- {_q(src)} {_q(dst)} && echo \"옮김: {src} -> {dst}\" >> \"$LOG\" "
            f"|| echo \"건너뜀: {src}\" | tee -a \"$LOG\"")


def plan_script(plan: Plan) -> str:
    items = [i for i in plan.items if i.include]
    lines = [HEADER.format(title=f"파일 정리 계획 #{plan.id} ({len(items)}개)",
                           when=datetime.now().strftime("%Y-%m-%d %H:%M"), filename=f"plan-{plan.id}.sh")]
    dirs = sorted({i.dest_dir for i in items if i.dest_dir})
    if dirs:
        lines.append("# 1) 폴더 만들기")
        lines.append("mkdir -p -- " + " ".join(_q(d) for d in dirs))
        lines.append("")
    lines.append("# 2) 옮기면서 이름 바꾸기")
    for i in items:
        dst = f"{i.dest_dir}/{i.new_name}" if i.dest_dir else i.new_name
        if i.sensitive:
            lines.append("# 🔒 민감 파일 (내용은 AI에 보내지 않음)")
        lines.append(_move_line(i.src_rel, dst))
    lines.append("")
    lines.append('echo "끝났습니다. 자세한 내용은 $LOG"')
    return "\n".join(lines) + "\n"


def undo_script(batch: Batch) -> str:
    moved = [m for m in batch.moves if m.status == "moved"]
    lines = [HEADER.format(title=f"정리 #{batch.id} 되돌리기 ({len(moved)}개)",
                           when=datetime.now().strftime("%Y-%m-%d %H:%M"), filename=f"undo-{batch.id}.sh")]
    lines.append("# 옮긴 순서의 반대로 원래 자리에 돌려놓는다")
    for m in reversed(moved):
        lines.append(_move_line(m.dst_rel, m.src_rel))
    lines.append("")
    lines.append("# 비어 있게 된 폴더만 정리 (rmdir은 빈 폴더만 지우므로 파일은 안전)")
    dirs = sorted({m.dst_rel.rsplit("/", 1)[0] for m in moved if "/" in m.dst_rel}, key=len, reverse=True)
    for d in dirs:
        lines.append(f"rmdir -p -- {_q(d)} 2>/dev/null")
    lines.append("")
    lines.append('echo "되돌렸습니다. 자세한 내용은 $LOG"')
    return "\n".join(lines) + "\n"
