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


# ---------------------------------------------------------------------------
# 검색 결과 저장(캐시): 같은 질문은 Gemini를 다시 기다리지 않는다
# ---------------------------------------------------------------------------
def _index_demo(session, demo_target):
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    return plan


def test_search_cache_reuses_gemini_answer(session, demo_target, fake_gemini, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "llm_cache", True)
    _index_demo(session, demo_target)
    fake_gemini.requests.clear()
    target = session.query(FileRecord).filter(FileRecord.title == "AI 제목 0").first()
    fake_gemini.search_responder = lambda ids, body: {
        "answer": "이 파일입니다.", "results": [{"id": target.id, "reason": "제목이 같음"}]}

    first = search(session, "통장 AI 제목")
    assert first[2] == "gemini" and len(fake_gemini.requests) == 1

    second = search(session, "  통장   ai 제목 ")      # 공백·대소문자만 다른 같은 질문
    assert len(fake_gemini.requests) == 1              # Gemini를 다시 부르지 않음
    assert second[2] == "gemini" and second[0] == "이 파일입니다."
    assert second[1][0].record.id == target.id and second[1][0].reason == "제목이 같음"
    assert any(h.record.sensitive for h in second[1])  # 민감 파일은 이번에도 내 컴퓨터 점수로만 덧붙임


def test_search_cache_does_not_store_fallback(session, demo_target, fake_gemini, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "llm_cache", True)
    _index_demo(session, demo_target)
    fake_gemini.requests.clear()
    fake_gemini.fail_with = 400
    assert search(session, "기말 프로젝트 공지")[2] == "fallback"
    fake_gemini.fail_with = None
    n = len(fake_gemini.requests)
    assert search(session, "기말 프로젝트 공지")[2] == "gemini"   # 실패한 결과가 저장돼 있지 않아 다시 물어봄
    assert len(fake_gemini.requests) == n + 1


def test_search_cache_survives_move_but_not_content_change(session, demo_target, fake_gemini, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "llm_cache", True)
    plan = _index_demo(session, demo_target)
    fake_gemini.requests.clear()
    search(session, "기말 프로젝트 공지")
    assert len(fake_gemini.requests) == 1

    mover.apply_plan(session, plan, demo_target)       # 파일 위치만 바뀜 → 저장한 답을 그대로 쓰되 새 위치를 보여 줌
    _, hits, source = search(session, "기말 프로젝트 공지")
    assert len(fake_gemini.requests) == 1 and source == "gemini"
    assert all(h.record.path_rel for h in hits)

    rec = session.query(FileRecord).filter(FileRecord.sensitive.is_(False)).first()
    rec.summary = rec.summary + " (내용이 바뀜)"       # 파일 내용 정보가 바뀌면 다시 물어봄
    session.commit()
    search(session, "기말 프로젝트 공지")
    assert len(fake_gemini.requests) == 2
