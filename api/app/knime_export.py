"""KNIME(AutoML 강의)에서 쓸 데이터 만들기 — 정리 폴더의 파일마다 한 줄씩 CSV로.

두 가지 실험에 쓴다 (knime/README.md):
  A. 정확도 비교: 정답(true_category)과 규칙 기반(rule_category)·Gemini(ai_category)를 Scorer로 비교
  B. 분류 모델: 이름·확장자·크기만으로(내용을 읽기 전에) 분류를 맞히는 모델을 학습
     → 확실한 파일은 Gemini에 안 보내도 되는지 확인 (호출 수·대기 시간·전송 파일 줄이기)

- Gemini를 새로 부르지 않는다. AI 결과는 감시 데몬·살펴보기가 저장해 둔 analysis_cache에서만 가져온다.
- 민감 파일의 내용·제목은 넣지 않는다 (파일 이름과 '민감' 표시만).
- 정답표(demo/samples/answers.csv)가 있으면 이름이 같은 파일에 정답을 붙인다 (연습 폴더용).
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import analyzer
from .config import settings
from .db import AnalysisCache, AppSettings
from .planner import _cache_key, _collect, _extract_all, list_candidates

COLUMNS = ["file_name", "ext", "kind", "size_kb", "name_type", "name_has_date", "name_has_version",
           "name_length", "is_duplicate", "is_sensitive", "rule_category", "ai_category", "ai_course",
           "true_category", "true_course"]

NAME_TYPES = [
    ("kakaotalk", re.compile(r"^kakaotalk_", re.I)),
    ("screenshot", analyzer.SCREENSHOT_NAME),
    ("camera", re.compile(r"^(img|dsc|pxl|dcim)[_-]?\d", re.I)),
    ("installer", re.compile(r"setup|install|amd64|x64|win(32|64)", re.I)),
    ("generic", re.compile(r"다운로드|download|제목 없음|무제|untitled|^새 |^image ?\(\d+\)|^scan\d+", re.I)),
]
DATE_IN_NAME = re.compile(r"20\d{2}[-_.]?\d{2}[-_.]?\d{2}")
VERSION_MARK = re.compile(r"\(\d+\)|최종|final|v\d|수정|copy|사본", re.I)


def name_type(name: str) -> str:
    for label, pattern in NAME_TYPES:
        if pattern.search(name):
            return label
    return "other"


def load_answers(path: Path | None) -> dict[str, tuple[str, str]]:
    if not path or not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["file_name"]: (r["true_category"], r.get("true_course", "")) for r in csv.DictReader(f)}


def build_rows(session: Session, root: Path, cfg: AppSettings, answers: dict[str, tuple[str, str]]) -> list[dict]:
    root = root.resolve()
    works = _collect(session, root, list_candidates(root, settings.max_files_per_scan))
    want_image = settings.use_gemini and cfg.analyze_images
    _extract_all([w for w in works if not w.duplicate_of], cfg, want_image=False)  # 로컬 추출만 (OCR 포함)
    courses = analyzer.parse_courses(cfg.courses or [])
    keys = {w.rel: _cache_key(w.sha, cfg, want_image) for w in works}
    cached = {r.key: r.insight for r in session.scalars(
        select(AnalysisCache).where(AnalysisCache.key.in_(keys.values())))}
    rows = []
    for w in works:
        rule_cat = ai_cat = ai_course = ""
        if w.sensitive:
            rule_cat = "개인서류"           # 민감 파일은 어느 방식이든 내 컴퓨터에서 개인서류로 분류
        elif not w.duplicate_of and w.extracted is not None:
            ex = w.extracted
            inp = analyzer.AnalysisInput(index=0, name=w.path.name, ext=w.ext, kind=w.kind, size=w.size,
                                         date_hint="", text=w.masked_text, ocr_text=ex.ocr_text)
            rule_cat = analyzer.mock_insight(inp, courses).category
            hit = cached.get(keys[w.rel])
            if hit:
                ai_cat, ai_course = hit.get("category", ""), hit.get("course", "")
        true_cat, true_course = answers.get(w.path.name, ("", ""))
        rows.append({
            "file_name": w.path.name, "ext": w.ext or "(없음)", "kind": w.kind,
            "size_kb": round(w.size / 1024, 1), "name_type": name_type(w.path.name),
            "name_has_date": int(bool(DATE_IN_NAME.search(w.path.name))),
            "name_has_version": int(bool(VERSION_MARK.search(w.path.name))),
            "name_length": len(w.path.stem), "is_duplicate": int(bool(w.duplicate_of)),
            "is_sensitive": int(w.sensitive), "rule_category": rule_cat, "ai_category": ai_cat,
            "ai_course": ai_course, "true_category": true_cat, "true_course": true_course,
        })
    return rows


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return "﻿" + buf.getvalue()  # BOM: 엑셀·KNIME에서 한글이 깨지지 않도록
