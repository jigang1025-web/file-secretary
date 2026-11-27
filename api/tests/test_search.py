import json

from app import mover, planner
from app.db import FileRecord, get_app_settings
from app.search import keyword_score, search, tokens, variants


def test_tokens_drop_particles_and_stopwords():
    assert tokens("교수님이 보낸 기말 공지 찾아줘") == ["교수님이", "기말", "공지"]
    assert tokens("도서관에서 받은 와이파이 비번") == ["도서관", "와이파이", "비번"]
    assert variants("교수님이") == ["교수님이", "교수님"]
    assert variants("와이파이")[0] == "와이파이"


def test_keyword_score_prefers_title():
    a = FileRecord(path_rel="a", title="기말 프로젝트 안내", keywords=[], summary="", category="수업", course="")
    b = FileRecord(path_rel="b", title="카페 영수증", keywords=[], summary="기말 이후 모임", category="영수증·결제",
                   course="")
    toks = tokens("기말 프로젝트")
    assert keyword_score(toks, a) > keyword_score(toks, b) > 0


def test_local_search_after_apply(session, demo_target):
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    mover.apply_plan(session, plan, demo_target)
    answer, hits, source = search(session, "기말 프로젝트 공지 찾아줘")
    assert source == "mock"
    assert hits[0].record.path_rel.startswith("수업/오픈소스프로그래밍/")
    _, hits, _ = search(session, "와이파이 비밀번호")
    assert hits and hits[0].record.title == "스터디카페 2층 와이파이"
    _, hits, _ = search(session, "전혀없는단어조합")
    assert hits == []


def test_gemini_rerank_excludes_sensitive(session, demo_target, fake_gemini):
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    mover.apply_plan(session, plan, demo_target)
    fake_gemini.requests.clear()
    target = session.query(FileRecord).filter(FileRecord.title == "AI 제목 0").first()

    def responder(ids, body):
        return {"answer": "이 파일입니다.", "results": [{"id": 99999, "reason": "없는 id"},
                                                     {"id": target.id, "reason": "제목이 같음"}]}

    fake_gemini.search_responder = responder
    answer, hits, source = search(session, "통장 AI 제목")
    assert source == "gemini" and answer == "이 파일입니다."
    assert hits[0].record.id == target.id  # 지어낸 id(99999)는 버림
    sent = json.dumps(fake_gemini.requests[-1]["body"], ensure_ascii=False)
    assert "통장사본" not in sent and "개인서류" not in sent
    assert any(h.record.sensitive for h in hits)  # 민감 파일은 내 컴퓨터 점수로만 덧붙임
