"""정리 계획 → 리눅스 셸 스크립트. 스크립트를 실제로 bash로 실행해 서비스와 같은 결과가 나오는지 확인한다."""
import shutil
import subprocess

import pytest


BASH = shutil.which("bash")


def _scan(client):
    res = client.post("/api/v1/plans", json={})
    assert res.status_code == 201
    return res.json()


def test_plan_script_content(client, demo_target):
    plan = _scan(client)
    res = client.get(f"/api/v1/plans/{plan['id']}/script")
    assert res.status_code == 200 and res.text.startswith("#!/bin/bash")
    text = res.text
    assert "mkdir -p --" in text and "mv -n --" in text
    assert "\nrm " not in text and " rm -" not in text   # 지우는 명령은 없다
    assert ">> \"$LOG\"" in text                          # 리다이렉션으로 기록
    assert "'다운로드 (7).pdf'" in text                    # 띄어쓰기가 있는 이름은 따옴표로 감싼다


@pytest.mark.skipif(BASH is None, reason="bash 없음")
def test_plan_script_runs_like_the_service(client, demo_target, tmp_path):
    plan = _scan(client)
    script = client.get(f"/api/v1/plans/{plan['id']}/script").text
    copy = tmp_path / "copy"
    shutil.copytree(demo_target, copy)
    (copy / "plan.sh").write_text(script, encoding="utf-8")
    subprocess.run([BASH, "plan.sh"], cwd=copy, check=True, capture_output=True)
    for item in plan["items"]:
        if not item["include"]:
            continue
        dst = f"{item['dest_dir']}/{item['new_name']}" if item["dest_dir"] else item["new_name"]
        assert (copy / dst).is_file(), dst
        assert not (copy / item["src_rel"]).exists() or item["src_rel"] == dst


@pytest.mark.skipif(BASH is None, reason="bash 없음")
def test_undo_script_restores_files(client, demo_target):
    before = sorted(p.name for p in demo_target.iterdir() if p.is_file())
    plan = _scan(client)
    batch = client.post(f"/api/v1/plans/{plan['id']}/apply").json()
    script = client.get(f"/api/v1/batches/{batch['id']}/script").text
    (demo_target / ".undo.sh").write_text(script, encoding="utf-8")
    subprocess.run([BASH, ".undo.sh"], cwd=demo_target, check=True, capture_output=True)
    after = sorted(p.name for p in demo_target.iterdir() if p.is_file() and p.name not in (".undo.sh", "정리기록.log"))
    assert after == before
    assert not any(p.is_dir() for p in demo_target.iterdir())  # 비게 된 폴더도 정리됨


def test_script_404(client):
    assert client.get("/api/v1/plans/999/script").status_code == 404
    assert client.get("/api/v1/batches/999/script").status_code == 404
