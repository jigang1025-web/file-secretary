from fastapi.testclient import TestClient

from app.db import FileRecord


def test_health_without_key_and_auth_required(client):
    from app.main import app

    bare = TestClient(app)
    assert bare.get("/health").json()["status"] == "ok"
    assert bare.get("/api/v1/settings").status_code == 401
    assert bare.get("/api/v1/settings", headers={"X-API-Key": "wrong"}).status_code == 401


def test_settings_put_replaces(client):
    got = client.get("/api/v1/settings").json()
    assert "오픈소스프로그래밍" in got["courses"] and got["llm_mode"] == "mock"
    body = {"courses": ["캡스톤디자인", " "], "name_pattern": "title_date", "analyze_images": False,
            "extra_sensitive_keywords": ["성적증명서"]}
    first = client.put("/api/v1/settings", json=body).json()
    second = client.put("/api/v1/settings", json=body).json()
    assert first == second and first["courses"] == ["캡스톤디자인"] and first["name_pattern"] == "title_date"
    assert client.put("/api/v1/settings", json={**body, "name_pattern": "bad"}).status_code == 422


def test_full_flow(client, app_env):
    assert client.post("/api/v1/demo/reset").json()["copied"] == 26
    plan = client.post("/api/v1/plans", json={}).json()
    assert plan["status"] == "draft" and plan["total"] == 26
    items = {i["src_rel"]: i for i in plan["items"]}

    memo = items["새 텍스트 문서.txt"]
    r = client.patch(f"/api/v1/plans/{plan['id']}/items/{memo['id']}",
                     json={"new_name": "카페 와이파이", "dest_dir": "문서/메모/../메모"})
    assert r.status_code == 200
    assert r.json()["new_name"] == "카페 와이파이.txt" and r.json()["dest_dir"] == "문서/메모/메모"
    photo = items["IMG_4821.JPG"]
    client.patch(f"/api/v1/plans/{plan['id']}/items/{photo['id']}", json={"include": False})

    batch = client.post(f"/api/v1/plans/{plan['id']}/apply").json()
    assert batch["moved"] == 25
    assert (app_env / "문서" / "메모" / "메모" / "카페 와이파이.txt").exists()
    assert (app_env / "IMG_4821.JPG").exists()
    assert client.patch(f"/api/v1/plans/{plan['id']}/items/{memo['id']}", json={"include": False}).status_code == 409

    hits = client.get("/api/v1/search", params={"q": "기말 프로젝트 공지"}).json()["results"]
    top = hits[0]["file"]
    assert top["path_rel"].startswith("수업/오픈소스프로그래밍/")
    content = client.get(f"/api/v1/files/{top['id']}/content")
    assert content.status_code == 200 and content.content[:4] == b"%PDF"

    tree = client.get("/api/v1/tree").json()
    assert "수업" in [c["name"] for c in tree["children"]]
    stats = client.get("/api/v1/stats").json()
    assert stats["loose_files"] == 1 and stats["organized_files"] == 25

    undone = client.post(f"/api/v1/batches/{batch['id']}/undo").json()
    assert undone["undone_at"] and (app_env / "새 텍스트 문서.txt").exists()
    assert client.post(f"/api/v1/batches/{batch['id']}/undo").status_code == 409


def test_new_plan_cancels_old_draft(client, app_env):
    (app_env / "a.txt").write_text("메모", encoding="utf-8")
    first = client.post("/api/v1/plans").json()
    client.post("/api/v1/plans")
    assert client.get(f"/api/v1/plans/{first['id']}").json()["status"] == "cancelled"
    assert client.post(f"/api/v1/plans/{first['id']}/apply").status_code == 409


def test_download_blocks_path_traversal(client, session):
    rec = FileRecord(path_rel="../../etc/passwd", original_name="passwd")
    session.add(rec)
    session.commit()
    assert client.get(f"/api/v1/files/{rec.id}/content").status_code == 400


def test_demo_reset_protects_real_folder(client, app_env):
    (app_env / "내 소중한 파일.docx").write_text("진짜 파일", encoding="utf-8")
    assert client.post("/api/v1/demo/reset").status_code == 409
    assert (app_env / "내 소중한 파일.docx").exists()
    assert client.get("/api/v1/settings").json()["demo_reset_available"] is False
