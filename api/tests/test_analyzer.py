"""Gemini 경로 테스트 — 진짜 google-genai SDK가 로컬 가짜 서버(conftest.fake_gemini)로 요청한다."""
import json

from app import analyzer, planner
from app.config import settings
from app.db import get_app_settings


def all_request_text(fake) -> str:
    """실제로 보낸 파일 정보(input)만 모은다 (시스템 안내문 제외)."""
    return "\n".join(json.dumps(r["body"]["input"], ensure_ascii=False) for r in fake.requests)


def test_parse_and_match_courses():
    courses = analyzer.parse_courses(["기계학습: 머신러닝, ML", "자료구조", ""])
    assert courses["기계학습"] == ["기계학습", "머신러닝", "ML"]
    assert analyzer.match_course("머신러닝 과제 안내", courses) == "기계학습"
    assert analyzer.normalize_course("자료 구조", courses) == "자료구조"
    assert analyzer.normalize_course("없는 과목", courses, allow_new=False) == ""
    assert analyzer.normalize_course("한국근현대사", courses) == "한국근현대사"  # 처음 보는 과목은 AI가 지은 이름 그대로
    assert analyzer.normalize_course("확률", analyzer.parse_courses(["확률과통계"])) == "확률과통계"  # 이미 있는 폴더로


def test_gemini_request_format_and_privacy(session, demo_target, fake_gemini):
    settings.llm_batch_size = 6
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    items = {i.src_rel: i for i in plan.items}

    # 요청 형식: 공식 문서와 같은 interactions API + JSON 스키마 + 저장 안 함
    req = fake_gemini.requests[0]
    assert req["path"].endswith("/interactions") and req["key"] == "fake-key"
    body = req["body"]
    assert body["model"] == settings.gemini_model and body["store"] is False
    assert body["generation_config"]["thinking_level"] == "low"  # 빠른 응답을 위해 생각은 적게
    assert body["response_format"]["mime_type"] == "application/json"
    assert body["response_format"]["schema"]["properties"]["files"]["items"]["properties"]["category"]["enum"]

    # 민감 파일 3개 + 중복 2개는 보내지 않음 → 21개를 6개씩 = 4번 호출
    assert len(fake_gemini.requests) == 4
    sent = all_request_text(fake_gemini)
    for secret in ["통장사본", "scan0001", "신분증", "123-456-789012", "000101-3"]:
        assert secret not in sent
    kinds = [p["type"] for r in fake_gemini.requests for p in r["body"]["input"][0]["content"]]
    assert kinds.count("image") == 6  # 일반 이미지 6장 (신분증 사진 제외)

    assert items["다운로드 (7).pdf"].source == "gemini"
    assert items["통장사본.pdf"].source == "rule"


def test_images_not_sent_when_disabled(session, demo_target, fake_gemini):
    cfg = get_app_settings(session)
    cfg.analyze_images = False
    session.commit()
    planner.build_plan(session, demo_target, cfg)
    kinds = [p["type"] for r in fake_gemini.requests for p in r["body"]["input"][0]["content"]]
    assert "image" not in kinds


def test_gemini_output_is_validated(session, app_env, fake_gemini):
    (app_env / "notice.txt").write_text("오픈소스 프로그래밍 공지\n발표는 12월입니다.", encoding="utf-8")

    def responder(indexes, body):
        return {"files": [{"index": i, "category": "수업", "course": "오픈소스 프로그래밍",
                           "title": '기말/발표: "안내"', "date": "2026-13-40", "summary": "요약",
                           "keywords": ["발표", " "]} for i in indexes]}

    fake_gemini.file_responder = responder
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    item = next(i for i in plan.items if i.src_rel == "notice.txt")
    assert item.course == "오픈소스프로그래밍"  # 띄어쓰기가 달라도 내 과목 이름으로 맞춤
    assert item.dest_dir == "수업/오픈소스프로그래밍"
    assert "/" not in item.new_name and '"' not in item.new_name and ":" not in item.new_name
    assert item.date != "2026-13-40" and item.keywords == ["발표"]


def test_fallback_when_gemini_fails(session, demo_target, fake_gemini):
    fake_gemini.fail_with = 500
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    sources = {i.source for i in plan.items}
    assert "fallback" in sources and "gemini" not in sources
    assert plan.llm_source == "fallback"
    assert all(i.new_name for i in plan.items)  # 실패해도 정리 계획은 만들어짐


def test_sdk_retries_temporary_errors(session, app_env, fake_gemini):
    (app_env / "memo.txt").write_text("메모 내용", encoding="utf-8")
    settings.llm_retry_attempts = 2
    fake_gemini.fail_with = 503
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    assert len(fake_gemini.requests) == 2  # 처음 1번 + 다시 시도 1번
    assert plan.items[0].source == "fallback"


def test_missing_index_falls_back(session, app_env, fake_gemini):
    for n in range(3):
        (app_env / f"memo{n}.txt").write_text(f"메모 {n} 내용", encoding="utf-8")
    fake_gemini.file_responder = lambda idx, body: FakeFirstOnly.respond(idx)
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    sources = sorted(i.source for i in plan.items)
    assert sources == ["fallback", "fallback", "gemini"]


class FakeFirstOnly:
    @staticmethod
    def respond(indexes):
        i = indexes[0]
        return {"files": [{"index": i, "category": "문서", "course": "", "title": "첫 메모", "date": "",
                           "summary": "", "keywords": []}]}


def test_fallback_model_when_primary_busy(session, demo_target, fake_gemini):
    """기본 모델이 503(혼잡)이면 예비 모델로 넘어가고, 다음 묶음부터는 예비 모델로 바로 보낸다."""
    settings.gemini_fallback_models = ["backup-flash"]
    fake_gemini.fail_models = {settings.gemini_model: 503}
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    items = {i.src_rel: i for i in plan.items}
    assert items["다운로드 (7).pdf"].source == "gemini"
    models = [r["body"]["model"] for r in fake_gemini.requests]
    assert models[0] == settings.gemini_model and models[1] == "backup-flash"
    assert models.count(settings.gemini_model) == 1  # 첫 실패 뒤로는 기본 모델을 다시 두드리지 않음


def test_no_fallback_on_auth_error(session, app_env, fake_gemini):
    """키 오류(403)는 다른 모델로 바꿔도 안 되므로 예비 모델을 시도하지 않는다."""
    (app_env / "a.txt").write_text("메모", encoding="utf-8")
    settings.gemini_fallback_models = ["backup-flash"]
    fake_gemini.fail_with = 403
    planner.build_plan(session, app_env, get_app_settings(session))
    assert [r["body"]["model"] for r in fake_gemini.requests] == [settings.gemini_model]


def test_batches_sent_concurrently(session, demo_target, fake_gemini):
    """묶음을 동시에 보내도 모든 파일이 빠짐없이 Gemini 결과로 채워진다."""
    settings.llm_concurrency = 4
    settings.llm_batch_size = 4
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    assert len(fake_gemini.requests) >= 5
    sent = [i for i in plan.items if i.source == "gemini"]
    assert len(sent) == 21 and len({i.new_name for i in sent}) == len(sent)


def test_cache_reuses_gemini_results(session, demo_target, fake_gemini):
    """같은 파일을 다시 살펴보면 Gemini를 다시 부르지 않고 저장된 결과를 쓴다."""
    settings.llm_cache = True
    first = planner.build_plan(session, demo_target, get_app_settings(session))
    calls = len(fake_gemini.requests)
    assert calls > 0
    second = planner.build_plan(session, demo_target, get_app_settings(session))
    assert len(fake_gemini.requests) == calls  # 추가 호출 없음
    a = {i.src_rel: (i.new_name, i.source) for i in first.items}
    b = {i.src_rel: (i.new_name, i.source) for i in second.items}
    assert a == b


def test_cache_skips_failed_results(session, app_env, fake_gemini):
    """실패해서 규칙 기반으로 대신한 결과는 저장하지 않고, 다음에 다시 Gemini에 묻는다."""
    (app_env / "memo.txt").write_text("오픈소스 과제 메모", encoding="utf-8")
    settings.llm_cache = True
    fake_gemini.fail_with = 503
    planner.build_plan(session, app_env, get_app_settings(session))
    fake_gemini.fail_with = None
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    assert plan.items[0].source == "gemini" and len(fake_gemini.requests) == 2


def test_time_budget_stops_waiting(session, app_env, fake_gemini, monkeypatch):
    """AI 분석 시간 예산을 넘기면 더 기다리지 않고 규칙 기반으로 마무리한다."""
    (app_env / "memo.txt").write_text("메모", encoding="utf-8")
    settings.gemini_fallback_models = ["b1", "b2", "b3"]
    settings.llm_total_budget_seconds = 0  # 예산 0초 → 바로 포기
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    assert plan.items[0].source == "fallback" and fake_gemini.requests == []


def test_hard_limit_when_call_hangs(session, app_env, fake_gemini, monkeypatch):
    """SDK 안에서 시간 제한이 안 먹히고 멈춰도, 정한 시간이 지나면 규칙 기반으로 끝낸다."""
    import time as _time

    (app_env / "memo.txt").write_text("메모", encoding="utf-8")
    settings.llm_total_budget_seconds = 1
    monkeypatch.setattr(analyzer, "_call_gemini", lambda *a, **k: _time.sleep(30))
    started = _time.monotonic()
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    assert _time.monotonic() - started < 15
    assert plan.items[0].source == "fallback"


def test_ai_names_new_course_and_reuses_existing_folder(session, app_env, fake_gemini):
    from app import planner
    from app.db import get_app_settings

    (app_env / "수업" / "한국근현대사").mkdir(parents=True)  # 사용자가 이미 만든 과목 폴더
    (app_env / "연표.txt").write_text("갑오개혁 연표 과제", encoding="utf-8")
    (app_env / "확률과제.txt").write_text("조건부확률 과제", encoding="utf-8")
    names = {}

    def responder(indexes, body):
        text = fake_gemini.texts(body)
        names["prompt"] = text
        out = []
        for i in indexes:
            course = "한국 근현대사" if "연표" in text.split(f"[파일 index={i}]")[1][:60] else "확률론"
            out.append({"index": i, "category": "수업", "course": course, "title": f"제목 {i}", "date": "",
                        "summary": "요약", "keywords": [], "name_ok": False})
        return {"files": out}

    fake_gemini.file_responder = responder
    cfg = get_app_settings(session)
    cfg.courses = []
    session.commit()
    plan = planner.build_plan(session, app_env, cfg)
    dest = {i.src_rel: i.dest_dir for i in plan.items}
    assert dest["연표.txt"] == "수업/한국근현대사"        # '한국 근현대사' → 이미 있는 폴더 이름으로 맞춤
    assert dest["확률과제.txt"] == "수업/확률론"          # 처음 보는 과목은 AI가 지은 이름으로 새 폴더
    assert "기존 과목 폴더: 한국근현대사" in names["prompt"]
