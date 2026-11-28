import os
import time

import pytest

from app import planner
from app.db import get_app_settings


def test_sanitize_and_reserved_names():
    assert planner.sanitize_component('과제: 1/2 "최종"?') == "과제 1 2 최종"
    assert planner.sanitize_component("con") == "_con"
    assert planner.sanitize_component("  끝에 점.. ") == "끝에 점"


def test_build_name_patterns_and_course_strip():
    name = planner.build_name("date_title", "2026-11-09", "오픈소스프로그래밍",
                              "오픈소스 프로그래밍 기말 프로젝트 안내", ".PDF")
    assert name == "2026-11-09_기말 프로젝트 안내.pdf"
    assert planner.build_name("date_course_title", "2026-11-09", "", "공지", ".pdf") == "2026-11-09_공지.pdf"  # 예전 설정값
    assert planner.build_name("title_only", "2026-11-09", "", "카페 영수증", ".jpg") == "카페 영수증.jpg"
    assert planner.build_name("title_date", "2026-11-09", "기계학습", "과제 2", ".pdf") == "과제 2_2026-11-09.pdf"


def test_unique_name(tmp_path):
    (tmp_path / "a.pdf").write_text("x")
    taken: set[str] = set()
    assert planner.unique_name(tmp_path, "a.pdf", taken) == "a (2).pdf"
    assert planner.unique_name(tmp_path, "A.PDF", taken) == "A (3).PDF"  # 대소문자 무시 (Windows 기준)


def test_dates():
    assert planner.date_from_name("KakaoTalk_20261103_153201234.jpg") == "2026-11-03"
    assert planner.date_from_name("Screenshot_20261115-224512.png") == "2026-11-15"
    assert planner.date_from_name("IMG_20261399_1.jpg") == ""
    assert planner.date_from_text("제목\n공지일: 2026년 11월 9일\n본문") == "2026-11-09"
    body = "과제 양식\n" + "설명 " * 60 + "\n제출 기한: 2026년 11월 24일"
    assert planner.date_from_text(body) == ""  # 본문 뒤쪽의 마감일은 대표 날짜가 아님


def test_safe_join(tmp_path):
    with pytest.raises(ValueError):
        planner.safe_join(tmp_path, "../outside.txt")
    assert planner.safe_join(tmp_path, "수업/a.pdf") == (tmp_path / "수업" / "a.pdf").resolve()


def test_list_candidates_skips(tmp_path):
    for name in ["a.pdf", ".hidden", "~$temp.docx", "b.crdownload", "desktop.ini"]:
        (tmp_path / name).write_text("x")
    (tmp_path / "folder").mkdir()
    assert [p.name for p in planner.list_candidates(tmp_path, 50)] == ["a.pdf"]


def test_build_plan_on_demo_folder(session, demo_target):
    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    items = {i.src_rel: i for i in plan.items}
    assert plan.total == len(items) == 26

    notice = items["다운로드 (7).pdf"]
    assert notice.dest_dir == "수업/오픈소스프로그래밍"
    assert notice.new_name == "2026-11-09_기말 프로젝트 안내.pdf"

    dup = items["다운로드 (1).pdf"]
    assert dup.dest_dir == "중복 파일" and "중복" in dup.flags[0]
    assert items["다운로드.pdf"].dest_dir == "수업/기계학습"

    for name in ["통장사본.pdf", "scan0001.pdf", "신분증.jpg"]:
        item = items[name]
        assert item.sensitive and item.dest_dir == "개인서류" and item.source == "rule"
        assert item.preview == ""
    assert items["scan0001.pdf"].new_name.endswith("_가족관계증명서.pdf")

    assert items["ChromeSetup.exe"].new_name == "ChromeSetup.exe"
    assert any("설치 파일" in f for f in items["ChromeSetup.exe"].flags)
    assert not items["python-3.13.0-amd64.exe"].flags
    assert items["IMG_4821.JPG"].new_name.startswith("2026-10-18_")  # 촬영일(EXIF)
    assert items["새 한글 문서(2).hwp"].title == "안녕하세요."


def test_plan_detects_already_organized_twin(session, demo_target):
    from app import mover

    plan = planner.build_plan(session, demo_target, get_app_settings(session))
    mover.apply_plan(session, plan, demo_target)
    again = demo_target / "다시 받은 공지.pdf"
    again.write_bytes((demo_target / "수업" / "오픈소스프로그래밍" /
                       "2026-11-09_기말 프로젝트 안내.pdf").read_bytes())
    plan2 = planner.build_plan(session, demo_target, get_app_settings(session))
    item = plan2.items[0]
    assert item.dest_dir == "중복 파일" and "이미 정리된" in item.flags[0]


def test_mtime_used_when_no_other_date(session, app_env):
    p = app_env / "메모.txt"
    p.write_text("그냥 메모입니다", encoding="utf-8")
    t = time.mktime((2026, 3, 2, 12, 0, 0, 0, 0, -1))
    os.utime(p, (t, t))
    plan = planner.build_plan(session, app_env, get_app_settings(session))
    assert plan.items[0].new_name.startswith("2026-03-02_")


def test_name_is_meaningful():
    from app.analyzer import name_is_meaningful

    assert name_is_meaningful("한국근현대사 연표 양식.hwp")
    assert name_is_meaningful("1 2026학년도 2학기 부·복수전공 신청 안내.pdf")
    assert not name_is_meaningful("KakaoTalk_20261103_153201234.jpg")
    assert not name_is_meaningful("다운로드 (7).pdf")
    assert not name_is_meaningful("강의자료_week10.pdf")
    assert not name_is_meaningful("final_진짜최종(2).docx")


def test_keep_good_names_setting(session, app_env):
    good = app_env / "한국근현대사 연표 양식.txt"
    good.write_text("한국 근현대사 주요 사건 연표를 정리하는 양식입니다.", encoding="utf-8")
    vague = app_env / "새 텍스트 문서.txt"
    vague.write_text("스터디카페 와이파이 비밀번호 메모", encoding="utf-8")
    cfg = get_app_settings(session)

    plan = planner.build_plan(session, app_env, cfg)
    items = {i.src_rel: i for i in plan.items}
    assert items[good.name].new_name == good.name
    assert "그대로 둠" in " ".join(items[good.name].flags)
    assert items[vague.name].new_name != vague.name

    cfg.keep_good_names = False
    session.commit()
    plan = planner.build_plan(session, app_env, cfg)
    items = {i.src_rel: i for i in plan.items}
    assert items[good.name].new_name != good.name
