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


def test_open_file_with_signed_link(client, app_env):
    import time

    from app.main import app
    from app.security import file_link_signature

    client.post("/api/v1/demo/reset")
    client.post("/api/v1/plans", json={})
    rec = next(f for f in client.get("/api/v1/files").json() if f["path_rel"].endswith(".txt"))
    bare = TestClient(app)  # 브라우저처럼 X-API-Key 헤더 없이
    exp = int(time.time()) + 600
    ok = bare.get(f"/api/v1/files/{rec['id']}/open", params={"exp": exp, "sig": file_link_signature(rec["id"], exp)})
    assert ok.status_code == 200
    assert ok.headers["content-disposition"].startswith("inline")
    assert "charset=" in ok.headers["content-type"]
    charset = ok.headers["content-type"].split("charset=")[1]
    assert "STUDY" in ok.content.decode("cp949" if charset == "euc-kr" else charset)
    wrong = bare.get(f"/api/v1/files/{rec['id']}/open", params={"exp": exp, "sig": "0" * 64})
    assert wrong.status_code == 403
    other = bare.get(f"/api/v1/files/{rec['id'] + 1}/open", params={"exp": exp, "sig": file_link_signature(rec["id"], exp)})
    assert other.status_code == 403
    old = int(time.time()) - 10
    expired = bare.get(f"/api/v1/files/{rec['id']}/open", params={"exp": old, "sig": file_link_signature(rec["id"], old)})
    assert expired.status_code == 403


def test_settings_keep_good_names_roundtrip(client):
    got = client.get("/api/v1/settings").json()
    assert got["keep_good_names"] is True
    body = {k: got[k] for k in ("courses", "name_pattern", "analyze_images", "extra_sensitive_keywords")}
    off = client.put("/api/v1/settings", json={**body, "keep_good_names": False}).json()
    assert off["keep_good_names"] is False


def test_init_db_adds_missing_column(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text

    from app import db

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # 예전 버전의 표 (keep_good_names 열 없음)
        conn.execute(text("CREATE TABLE app_settings (id INTEGER PRIMARY KEY, courses JSON, name_pattern VARCHAR(32), "
                          "analyze_images BOOLEAN, extra_sensitive_keywords JSON, updated_at DATETIME)"))
        conn.execute(text("INSERT INTO app_settings (id, courses, name_pattern, analyze_images, extra_sensitive_keywords) "
                          "VALUES (1, '[]', 'date_course_title', 1, '[]')"))
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    assert "keep_good_names" in {c["name"] for c in inspect(engine).get_columns("app_settings")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT keep_good_names FROM app_settings WHERE id = 1")).scalar() in (1, True)
