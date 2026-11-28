"""파일 정리 비서 대시보드 (Streamlit).

API 서버(FastAPI)를 REST로 호출해서 화면에 보여 주는 '클라이언트'다.
실행: streamlit run app.py  →  http://localhost:8501
"""
from __future__ import annotations

import html
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")         # 컨테이너 안에서는 http://api:8000
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")  # 브라우저에서 여는 주소
API_KEY = os.getenv("SECRETARY_API_KEY", "")
KST = ZoneInfo("Asia/Seoul")

PATTERNS = {
    "date_course_title": "날짜_과목_제목  (2026-11-09_오픈소스프로그래밍_기말 프로젝트 안내.pdf)",
    "course_title_date": "과목_제목_날짜  (오픈소스프로그래밍_기말 프로젝트 안내_2026-11-09.pdf)",
    "title_date": "제목_날짜  (기말 프로젝트 안내_2026-11-09.pdf)",
    "title_only": "제목만  (기말 프로젝트 안내.pdf)",
}
SOURCE_LABEL = {"gemini": "AI", "mock": "기본 규칙", "fallback": "기본 규칙(대체)", "rule": "AI 안 씀"}
STATUS_LABEL = {"moved": "옮김", "skipped": "건너뜀", "undone": "되돌림", "undo_failed": "되돌리기 실패"}
EXT_LABEL = {"pdf": "PDF", "jpg": "IMG", "jpeg": "IMG", "png": "IMG", "gif": "IMG", "webp": "IMG", "heic": "IMG",
             "doc": "DOC", "docx": "DOC", "hwp": "HWP", "hwpx": "HWP", "txt": "TXT", "md": "TXT",
             "xls": "XLS", "xlsx": "XLS", "csv": "XLS", "ppt": "PPT", "pptx": "PPT",
             "zip": "ZIP", "7z": "ZIP", "rar": "ZIP", "exe": "EXE", "msi": "EXE", "dmg": "EXE",
             "mp3": "AUD", "m4a": "AUD", "wav": "AUD", "mp4": "VID", "mov": "VID"}

st.set_page_config(page_title="파일 정리 비서", page_icon="🗂️", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------------------------------------------------------
# 디자인 (앰버 + 크림). 색은 여기 :root 변수만 바꾸면 전체가 바뀐다.
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css");
:root {
  --bg: #FBF6EE; --card: #FFFDF9; --ink: #292524; --sub: #857A6E; --line: #EDE3D3;
  --acc: #D97706; --acc-hover: #B45309; --acc-soft: #FEF3C7; --acc-ink: #92400E;
  --done: #78350F; --done-soft: #F5E6D3; --muted-soft: #F5EEE2; --warn: #9A3412; --warn-soft: #FFEDD5;
}
html {font-size: 16px;}
html, body, .stApp, .stApp button, .stApp input, .stApp textarea {
  font-family: "Pretendard Variable", "Pretendard", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;
  letter-spacing: -0.01em;}
.stApp {background: var(--bg); color: var(--ink);}
header[data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
[data-testid="stHeaderActionElements"] {display: none !important;}
.block-container {padding: 0 2.25rem 3rem; max-width: 1400px;}
h1, h2, h3, h4, h5 {color: var(--ink); letter-spacing: -0.02em;}
.stApp a {color: var(--acc-ink);}

/* ---- 상단 바: 로고 + (탭 메뉴가 가운데로 올라옴) + 상태 알약 ---- */
.fs-top {position: relative; left: 50%; width: 100vw; margin-left: -50vw; background: var(--card);
         border-bottom: 1px solid var(--line); height: 64px; margin: -1rem 0 26px -50vw;}
.fs-top .in {max-width: 1400px; margin: 0 auto; padding: 0 2.25rem; height: 64px; display: flex; align-items: center;}
.fs-brand {display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 1.15rem; white-space: nowrap;}
.fs-logo {width: 30px; height: 30px; border-radius: 9px; background: var(--acc); color: #fff; display: grid;
          place-items: center; font-size: .95rem; font-weight: 800;}
.fs-pills {margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end;}
.fs-pill {display: flex; align-items: center; gap: 7px; border: 1px solid var(--line); background: var(--bg);
          border-radius: 999px; padding: 6px 12px; font-size: .8rem; color: #57534E; font-weight: 600; white-space: nowrap;}
.fs-dot {width: 8px; height: 8px; border-radius: 50%; background: var(--acc);}
.fs-dot.off {background: #C9BFB2;}
.fs-dot.busy {background: var(--acc); animation: fs-blink 1.2s infinite;}
@keyframes fs-blink {50% {opacity: .25;}}

div[data-testid="stTabs"] [role="tablist"] {gap: 4px; background: transparent; border: 0 !important; box-shadow: none !important;
  position: relative; z-index: 5; width: fit-content; margin: -76px 0 24px 210px;}
div[data-testid="stTabs"] [role="tablist"]::before, div[data-testid="stTabs"] [role="tablist"]::after {display: none !important;}
div[data-testid="stTabs"] > div > div:first-child {border: 0 !important; box-shadow: none !important;}
div[data-testid="stTabs"] .react-aria-SelectionIndicator {display: none !important;}
div[data-testid="stTab"] {padding: 8px 14px !important; border-radius: 9px; height: auto; background: transparent; margin: 0 !important;}
div[data-testid="stTab"] p {font-size: .95rem !important; font-weight: 600; color: var(--sub);}
div[data-testid="stTab"]:hover p {color: var(--ink);}
div[data-testid="stTab"][aria-selected="true"] {background: var(--acc-soft);}
div[data-testid="stTab"][aria-selected="true"] p {color: var(--acc-ink);}
@media (max-width: 1180px) {
  .fs-top {height: auto;} .fs-top .in {height: auto; flex-wrap: wrap; padding-top: 12px; padding-bottom: 12px; gap: 10px;}
  .fs-pills {margin-left: 0; justify-content: flex-start;}
  div[data-testid="stTabs"] [role="tablist"] {margin: -12px 0 22px 0;}
}

/* ---- 버튼 ---- */
.stApp button[kind="primary"], .stApp button[kind="primaryFormSubmit"], .stApp button[data-testid^="stBaseButton-primary"] {
  background: var(--acc); border-color: var(--acc); color: #fff; font-weight: 700; border-radius: 11px;
  box-shadow: 0 4px 14px rgba(217, 119, 6, .28);}
.stApp button[kind="primary"]:hover, .stApp button[kind="primaryFormSubmit"]:hover {background: var(--acc-hover); border-color: var(--acc-hover); color: #fff;}
.stApp button[kind="secondary"], .stApp button[kind="secondaryFormSubmit"], .stApp [data-testid="stDownloadButton"] button {
  background: var(--card); border: 1px solid var(--line); color: #44403C; font-weight: 700; border-radius: 11px;}
.stApp button[kind="secondary"]:hover, .stApp [data-testid="stDownloadButton"] button:hover {border-color: var(--acc); color: var(--acc-ink);}
.stApp button p {font-weight: 700;}

/* ---- 카드·입력·표 ---- */
.stApp [class*="st-key-card"] {background: var(--card); border-radius: 16px !important; border-color: var(--line) !important;}
div[data-testid="stExpander"] details {border: 1px solid var(--line); border-radius: 14px; background: var(--card);}
div[data-testid="stExpander"] summary p {font-weight: 600;}
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {border: 1px solid var(--line); border-radius: 14px; overflow: hidden; background: var(--card);}
.stApp input, .stApp textarea {border-radius: 10px !important;}
div[data-testid="stCode"] pre {border-radius: 12px;}

/* ---- 진행 단계 ---- */
.fs-steps {display: flex; gap: 10px; margin-bottom: 24px;}
.fs-step {flex: 1; display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-radius: 14px;
          border: 1px solid var(--line); background: var(--card); color: var(--sub); font-weight: 600;}
.fs-step .n {width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-size: .8rem;
             background: var(--muted-soft); color: var(--sub); font-weight: 700; flex: none;}
.fs-step.done {color: #44403C;} .fs-step.done .n {background: var(--done); color: #fff;}
.fs-step.on {border-color: #F59E0B; background: var(--acc-soft); color: var(--acc-ink);}
.fs-step.on .n {background: var(--acc); color: #fff;}
.fs-h {font-size: 1.45rem; font-weight: 800; margin: 0 0 4px; letter-spacing: -0.02em;}
.fs-lead {color: var(--sub); margin: 0 0 20px;}
.fs-lead b {color: var(--ink);}

/* ---- 숫자 카드 ---- */
.fs-kpis {display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 22px;}
.fs-kpi {background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px;}
.fs-kpi small {color: var(--sub); font-weight: 600; font-size: .82rem;}
.fs-kpi b {display: block; font-size: 1.9rem; margin-top: 2px; letter-spacing: -0.03em; color: var(--ink);}
.fs-kpi.hl {background: var(--acc-soft); border-color: #FCD34D;} .fs-kpi.hl small {color: var(--acc-ink);}
.fs-kpi.hl b {color: var(--acc-hover);}

/* ---- 폴더 나무 ---- */
.fs-cmp {display: grid; grid-template-columns: 1fr 40px 1fr; margin-bottom: 22px;}
.fs-arrow {display: grid; place-items: center; color: #B8AC9C; font-size: 1.4rem;}
.fs-panel {background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px; min-width: 0;}
.fs-ph {margin: 0 0 12px; font-size: .88rem; color: var(--sub); font-weight: 700; display: flex; justify-content: space-between;}
@media (max-width: 900px) {.fs-cmp {grid-template-columns: 1fr;} .fs-arrow {transform: rotate(90deg); height: 36px;}}
.fs-tree {font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .84rem; line-height: 1.75;
          white-space: pre; overflow-x: auto; max-height: 460px; overflow-y: auto; color: #44403C;}
.fs-tree .dir {color: var(--acc-ink); font-weight: 700;}
.fs-tree .muted {color: #B0A595;}

/* ---- 알림 상자 (초록·파랑 기본 알림 대신) ---- */
.fs-note {border-radius: 14px; padding: 14px 18px; margin: 0 0 16px; border: 1px solid var(--line); background: var(--card);
          font-size: .95rem;}
.fs-note.acc {background: var(--acc-soft); border-color: #FCD34D; color: #78350F;}
.fs-note.done {background: var(--done-soft); border-color: #E7CFAF; color: var(--done);}
.fs-note.warn {background: var(--warn-soft); border-color: #FDBA74; color: var(--warn);}

/* ---- 칩 ---- */
.fs-chip {display: inline-block; border-radius: 999px; padding: 2px 10px; font-size: .76rem; font-weight: 700;
          background: var(--acc-soft); color: var(--acc-ink); margin-right: 5px;}
.fs-chip.g {background: var(--muted-soft); color: #57534E;}
.fs-chip.src {background: var(--done-soft); color: var(--done);}
.fs-chip.lock {background: #44403C; color: #fff;}

/* ---- 하단 고정 버튼 줄 ---- */
[data-testid="stLayoutWrapper"]:has(> .st-key-actionbar) {position: sticky; bottom: 12px; z-index: 20;}
.st-key-actionbar {background: rgba(255, 253, 249, .96);
  backdrop-filter: blur(8px); border: 1px solid var(--line); border-radius: 16px; padding: 12px 16px;
  box-shadow: 0 -6px 24px rgba(41, 37, 36, .06); margin-top: 14px;}
.fs-barnote {color: var(--sub); font-size: .92rem;}
.fs-barnote b {color: var(--ink);}

/* ---- 찾기 ---- */
.st-key-searchbox {background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 10px 12px 2px;
  box-shadow: 0 1px 2px rgba(41, 37, 36, .04);}
.st-key-searchbox input {font-size: 1.05rem; background: var(--bg) !important; border: 0 !important; padding: 12px 14px !important;}
.st-key-searchbox [data-baseweb="input"] {border: 0 !important; background: var(--bg) !important; border-radius: 11px !important;}
.st-key-searchbox button {height: 46px;}
.stApp [data-testid="stButtonGroup"] button {border-radius: 999px; border: 1px solid var(--line);
  background: var(--card); font-weight: 600;}
.fs-answer {background: var(--card); border: 1px solid var(--line); border-left: 4px solid var(--acc); border-radius: 16px;
            padding: 16px 18px; margin: 12px 0 14px; display: flex; gap: 14px; align-items: flex-start;}
.fs-answer .ai {width: 34px; height: 34px; border-radius: 10px; background: var(--acc); color: #fff; display: grid;
                place-items: center; font-weight: 800; flex: none; font-size: .85rem;}
.fs-answer .a {font-weight: 700; font-size: 1.02rem;}
.fs-answer .meta {color: var(--sub); margin-top: 6px; font-size: .8rem;}
.fs-res {margin-bottom: 6px; background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px;
         display: grid; grid-template-columns: 44px 1fr; gap: 14px; align-items: start;}
.fs-ico {width: 44px; height: 44px; border-radius: 12px; background: var(--acc-soft); color: var(--acc-ink);
         display: grid; place-items: center; font-weight: 800; font-size: .72rem;}
.fs-res .t {font-weight: 700; font-size: 1.02rem;}
.fs-res .p {color: var(--sub); font-size: .8rem; margin: 2px 0 8px; font-family: ui-monospace, Menlo, Consolas, monospace;
            word-break: break-all;}
.fs-res .s {color: #44403C; margin-top: 8px; font-size: .92rem;}
.fs-res .r {color: var(--sub); margin-top: 4px; font-size: .82rem;}
.fs-sec {font-size: 1.05rem; font-weight: 800; margin: 6px 0 10px;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# API 호출
# ---------------------------------------------------------------------------
def api(method: str, path: str, timeout: int = 60, **kwargs):
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    try:
        r = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException:
        st.error(f"서비스에 연결할 수 없어요. Docker Desktop이 켜져 있는지 확인해 주세요. ({API_URL})")
        st.stop()
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        st.error(f"요청을 처리하지 못했어요 ({r.status_code}): {detail}")
        return None
    if r.status_code == 204 or not r.content:
        return {}
    if "application/json" in r.headers.get("content-type", ""):
        return r.json()
    return r.content


def kst(iso: str | None) -> str:
    if not iso:
        return ""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:  # SQLite는 시간대 없이 UTC로 저장한다
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST).strftime("%m/%d %H:%M")


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{n}B"


def esc(s) -> str:
    return html.escape(str(s or ""))


def note(text: str, kind: str = "") -> None:
    """초록·파랑 기본 알림 대신 쓰는 알림 상자. text 안의 HTML은 그대로 쓴다."""
    st.markdown(f'<div class="fs-note {kind}">{text}</div>', unsafe_allow_html=True)


def steps(current: int) -> None:
    labels = ["폴더 살펴보기", "정리안 확인", "정리 완료"]
    out = []
    for i, label in enumerate(labels, 1):
        cls, mark = ("done", "✓") if i < current else (("on", str(i)) if i == current else ("", str(i)))
        out.append(f'<div class="fs-step {cls}"><span class="n">{mark}</span>{label}</div>')
    st.markdown('<div class="fs-steps">' + "".join(out) + "</div>", unsafe_allow_html=True)


def heading(title: str, lead: str = "") -> None:
    st.markdown(f'<div class="fs-h">{title}</div>' + (f'<p class="fs-lead">{lead}</p>' if lead else ""),
                unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# 폴더 나무 그리기
# ---------------------------------------------------------------------------
def tree_from_paths(paths: list[str]) -> dict:
    root: dict = {}
    for p in paths:
        node = root
        parts = p.split("/")
        for d in parts[:-1]:
            node = node.setdefault(d + "/", {})
        node.setdefault(parts[-1], None)
    return root


def tree_from_api(node: dict) -> dict:
    out: dict = {}
    for ch in node.get("children", []):
        out[ch["name"] + ("/" if ch["is_dir"] else "")] = tree_from_api(ch) if ch["is_dir"] else None
    return out


def count_files(node: dict) -> int:
    return sum(count_files(v) if k.endswith("/") else 1 for k, v in node.items())


def render_tree(tree: dict, title: str, max_files: int = 6, files: bool = True) -> str:
    """폴더 나무를 HTML로. files=False면 폴더와 파일 개수만 보여 준다."""
    lines = [f'<span class="dir">{esc(title)}</span>']

    def walk(node: dict, prefix: str, top: bool) -> None:
        dirs = sorted(k for k in node if k.endswith("/"))
        names = sorted(k for k in node if not k.endswith("/"))
        if files:
            entries, hidden = dirs + names[:max_files], len(names) - min(len(names), max_files)
            rest = f"… 외 {hidden}개" if hidden else ""
        else:
            entries, rest = dirs, (f"그대로 둘 파일 {len(names)}개" if top and names else "")
        for i, key in enumerate(entries):
            last = i == len(entries) - 1 and not rest
            branch = "└─ " if last else "├─ "
            if key.endswith("/"):
                count = "" if files else f'  <span class="muted">{count_files(node[key])}</span>'
                lines.append(f'{prefix}{branch}<span class="dir">{esc(key[:-1])}</span>{count}')
                walk(node[key], prefix + ("   " if last else "│  "), False)
            else:
                lines.append(f"{prefix}{branch}{esc(key)}")
        if rest:
            lines.append(f'{prefix}└─ <span class="muted">{rest}</span>')

    walk(tree, "", True)
    return '<div class="fs-tree">' + "\n".join(lines) + "</div>"


def panel(title: str, right: str, body: str) -> str:
    return f'<div class="fs-panel"><div class="fs-ph"><span>{title}</span><span>{right}</span></div>{body}</div>'


# ---------------------------------------------------------------------------
# 상단 바
# ---------------------------------------------------------------------------
health = api("GET", "/health") or {}
cfg = api("GET", "/api/v1/settings") or {}
is_gemini = cfg.get("llm_mode") == "gemini"


def pill(text: str, dot: str = "", title: str = "") -> str:
    return f'<div class="fs-pill" title="{esc(title)}"><span class="fs-dot {dot}"></span>{esc(text)}</div>'


def watcher_pill(w: dict) -> str:
    if not w.get("running"):
        return pill("폴더 감시 데몬 · 꺼짐", "off")
    total, ready = w.get("loose", 0), w.get("ready", 0)
    if w.get("state") == "analyzing":
        if w.get("message", "").startswith("자주 쓰는 검색"):
            return pill("폴더 감시 데몬 · 검색 미리 준비 중", "busy", w.get("message", ""))
        return pill(f"폴더 감시 데몬 · 미리 분석 중 {ready}/{total}", "busy", w.get("message", ""))
    if total:
        return pill(f"폴더 감시 데몬 · {ready}/{total} 준비됨", "", w.get("message", ""))
    return pill("폴더 감시 데몬 · 켜짐", "", w.get("message", ""))


LIVE_SECONDS = 4  # 시작 화면과 개발자용 상태를 몇 초마다 저절로 새로 고칠지


def top_bar() -> None:
    """상단 바: 로고와 메뉴만. AI·폴더 감시·OCR 상태는 사용자가 알 필요가 없어 설정 탭의 개발자 정보로 옮겼다."""
    st.markdown('<div class="fs-top"><div class="in"><div class="fs-brand"><div class="fs-logo">F</div>파일 정리 비서</div>'
                '</div></div>', unsafe_allow_html=True)


top_bar()
tab_clean, tab_find, tab_log, tab_cfg = st.tabs(["정리하기", "찾기", "정리 기록", "설정"])


# ---------------------------------------------------------------------------
# 1. 정리하기
# ---------------------------------------------------------------------------
def start_scan() -> None:
    with st.spinner("AI가 파일을 읽고 있어요… 파일이 많으면 조금 걸릴 수 있어요."):
        plan = api("POST", "/api/v1/plans", json={}, timeout=900)
    if plan is not None:
        st.session_state["plan"] = plan
        st.session_state.pop("batch", None)
        st.rerun()


def item_note(it: dict) -> str:
    notes = []
    if it["sensitive"]:
        notes.append(f"AI에 안 보여 줌 ({it['sensitive_reason']})")
    notes += it["flags"]
    if it.get("error"):
        notes.append(f"문제: {it['error']}")
    return " · ".join(notes)


@st.fragment(run_every=LIVE_SECONDS)
def start_view() -> None:
    """1단계 시작 화면. 새 파일이 들어오거나 미리 읽기가 끝나면 저절로 바뀐다."""
    steps(1)
    live_stats = api("GET", "/api/v1/stats") or {}
    loose = live_stats.get("loose_files", 0)
    heading(f"정리가 필요한 파일이 {loose}개 있어요",
            "AI가 파일을 열어 보고 알아보기 쉬운 이름과 폴더를 골라 드려요. <b>확인을 누르기 전에는 아무것도 옮기지 않아요.</b>")
    st.markdown(
        '<div class="fs-kpis">'
        f'<div class="fs-kpi hl"><small>정리할 파일</small><b>{loose}</b></div>'
        f'<div class="fs-kpi"><small>정리된 파일</small><b>{live_stats.get("organized_files", 0)}</b></div>'
        '</div>', unsafe_allow_html=True)
    left, right = st.columns([2, 3], gap="large")
    with left:
        with st.container(border=True, key="card-2"):
            st.markdown('<div class="fs-sec">폴더 살펴보기</div>', unsafe_allow_html=True)
            st.write("누르면 AI가 문서와 사진 내용을 읽고 **새 이름 → 종류 → 넣을 폴더**를 한 번에 정해 드려요. "
                     "신분증·통장 같은 개인 서류는 AI에게 보여 주지 않아요.")
            if st.button("폴더 살펴보기", type="primary", disabled=loose == 0, use_container_width=True):
                start_scan()
            if loose == 0:
                st.caption("정리할 파일이 없어요. 설정 탭에서 '연습 폴더 초기화'를 누르면 연습용 파일이 들어와요.")
    with right:
        tree = api("GET", "/api/v1/tree", params={"depth": 1}) or {}
        st.markdown(panel("정리 전", f"{loose}개", render_tree(tree_from_api(tree), "정리 폴더", max_files=12)),
                    unsafe_allow_html=True)


@st.fragment(run_every=LIVE_SECONDS)
def dev_status() -> None:
    """개발자용 서비스 상태 (사용자 화면에는 보이지 않고 설정 탭에만). 몇 초마다 저절로 갱신."""
    w = api("GET", "/api/v1/watcher") or {}
    with st.container(border=True, key="card-dev"):
        st.markdown('<div class="fs-sec">서비스 상태 (개발자용)</div>'
                    '<div class="fs-pills" style="margin:0 0 10px 0;justify-content:flex-start">'
                    + pill(f"Gemini · {cfg.get('gemini_model', '')}" if is_gemini else "AI 꺼짐 · 규칙 기반", "" if is_gemini else "off")
                    + watcher_pill(w)
                    + pill("OCR " + ("켜짐" if cfg.get("ocr_enabled") else "꺼짐"), "" if cfg.get("ocr_enabled") else "off")
                    + "</div>", unsafe_allow_html=True)


with tab_clean:
    plan = st.session_state.get("plan")
    batch = st.session_state.get("batch")

    if batch:  # ---- 3단계: 정리 직후 ----
        steps(3)
        heading(f"파일 {batch['moved']}개를 정리했어요",
                "잘못 옮겨졌다면 <b>되돌리기</b>를 누르세요. 모두 원래 자리로 돌아가요."
                + (f" (옮기지 못한 파일 {batch['skipped']}개)" if batch["skipped"] else ""))
        skipped = [m for m in batch["moves"] if m["status"] == "skipped"]
        tree = api("GET", "/api/v1/tree", params={"depth": 3}) or {}
        left, right = st.columns([3, 2], gap="large")
        with left:
            t = tree_from_api(tree)
            st.markdown(panel("지금 폴더 모습", f"{count_files(t)}개", render_tree(t, "정리 폴더", files=False)),
                        unsafe_allow_html=True)
        with right:
            with st.container(border=True, key="card-1"):
                st.markdown('<div class="fs-sec">다음 할 일</div>', unsafe_allow_html=True)
                note("이제 <b>찾기</b> 탭에서 '기말 프로젝트 공지'처럼 말로 찾아보세요.", "acc")
                if st.button("방금 정리 되돌리기", type="primary", use_container_width=True):
                    res = api("POST", f"/api/v1/batches/{batch['id']}/undo")
                    if res is not None:
                        st.session_state.pop("batch", None)
                        st.session_state.pop("plan", None)
                        st.toast("원래대로 되돌렸어요.")
                        st.rerun()
                if st.button("다시 살펴보기", use_container_width=True):
                    start_scan()
            if skipped:
                with st.expander(f"옮기지 못한 파일 {len(skipped)}개"):
                    for m in skipped:
                        st.write(f"- `{m['src_rel']}` — {m['error']}")
            with st.expander("되돌리기를 리눅스 명령어로 보기"):
                undo = api("GET", f"/api/v1/batches/{batch['id']}/script")
                if isinstance(undo, (bytes, bytearray)):
                    st.code(undo.decode("utf-8"), language="bash")

    elif not plan:  # ---- 1단계: 시작 화면 (실시간) ----
        start_view()

    else:  # ---- 2단계: 미리보기 ----
        steps(2)
        items = plan["items"]
        n_sensitive = sum(i["sensitive"] for i in items)
        n_dup = sum(i["dest_dir"] == "중복 파일" for i in items)
        n_old = sum(any("설치 파일" in f for f in i["flags"]) for i in items)
        n_ai = sum(i["source"] == "gemini" for i in items)
        heading("AI가 정리 방법을 골랐어요",
                "<b>확인을 누르기 전에는 아무것도 옮기지 않아요.</b> 이름이나 폴더가 마음에 안 들면 아래 표에서 바로 고칠 수 있어요.")
        st.markdown(
            '<div class="fs-kpis">'
            f'<div class="fs-kpi"><small>살펴본 파일</small><b>{len(items)}</b></div>'
            f'<div class="fs-kpi hl"><small>AI가 내용을 읽은 파일</small><b>{n_ai if is_gemini else "-"}</b></div>'
            f'<div class="fs-kpi"><small>개인 서류 (AI에 안 보여 줌)</small><b>{n_sensitive}</b></div>'
            f'<div class="fs-kpi"><small>똑같은 파일</small><b>{n_dup}</b></div>'
            f'<div class="fs-kpi"><small>오래된 설치 파일</small><b>{n_old}</b></div>'
            '</div>', unsafe_allow_html=True)
        if plan["llm_source"] == "fallback":
            note("AI 연결이 잠깐 불안정해서 일부 파일은 <b>기본 규칙</b>으로 분류했어요. (표의 '분류 방법' 칸 참고)", "warn")

        before_t = tree_from_paths([i["src_rel"] for i in items])
        after_t = tree_from_paths([f"{i['dest_dir']}/{i['new_name']}" if i["include"] else i["src_rel"] for i in items])
        n_dirs = sum(1 for k in after_t if k.endswith("/"))
        st.markdown(
            '<div class="fs-cmp">'
            + panel("정리 전", f"{len(items)}개", render_tree(before_t, "정리 폴더", max_files=12))
            + '<div class="fs-arrow">→</div>'
            + panel("정리 후 (미리보기)", f"폴더 {n_dirs}개", render_tree(after_t, "정리 폴더", files=False))
            + "</div>", unsafe_allow_html=True)

        st.markdown('<div class="fs-sec">정리안 확인·수정</div>', unsafe_allow_html=True)
        st.caption("칸을 눌러 새 이름과 넣을 폴더를 바꿀 수 있어요. 옮기고 싶지 않은 파일은 '포함' 체크를 빼세요.")
        df = pd.DataFrame([{
            "포함": i["include"], "새 이름": i["new_name"], "원래 이름": i["src_rel"], "넣을 폴더": i["dest_dir"],
            "분류": i["category"], "분류 방법": SOURCE_LABEL.get(i["source"], i["source"]), "요약": i["summary"],
            "알림": item_note(i), "id": i["id"],
        } for i in items])
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True, height=min(560, 38 + 35 * len(df)),
            disabled=["원래 이름", "분류", "요약", "알림", "분류 방법", "id"],
            column_order=["포함", "새 이름", "원래 이름", "넣을 폴더", "분류", "분류 방법", "요약", "알림"],
            column_config={
                "포함": st.column_config.CheckboxColumn(width="small"),
                "새 이름": st.column_config.TextColumn(width="large"),
                "원래 이름": st.column_config.TextColumn(width="medium"),
                "넣을 폴더": st.column_config.TextColumn(width="medium"),
                "분류": st.column_config.TextColumn(width="small"),
                "분류 방법": st.column_config.TextColumn(width="small"),
                "요약": st.column_config.TextColumn(width="large"),
                "알림": st.column_config.TextColumn(width="medium"),
            }, key=f"editor-{plan['id']}")

        with st.expander("이 정리를 리눅스 명령어로 보기"):
            st.caption("이 서비스가 하는 일은 사실 두 가지 명령이에요. `mkdir -p`(폴더 만들기)와 `mv -n`(이름 바꿔 옮기기, 같은 이름이 있으면 덮어쓰지 않음). "
                       "파일을 지우는 명령은 없어요. 내려받아 정리 폴더에서 `bash plan.sh`로 직접 실행해도 결과가 같아요. "
                       "(표에서 고친 내용은 '정리하기'를 누를 때 반영돼요. 아래는 AI가 처음 고른 정리안이에요.)")
            script = api("GET", f"/api/v1/plans/{plan['id']}/script")
            if isinstance(script, (bytes, bytearray)):
                text = script.decode("utf-8")
                st.code(text, language="bash")
                st.download_button("셸 스크립트 내려받기", data=text.encode("utf-8"),
                                   file_name=f"plan-{plan['id']}.sh", mime="text/x-shellscript")

        count = int(edited["포함"].sum())
        with st.container(key="actionbar"):
            c0, c1, c2, c3 = st.columns([5, 1.4, 1, 1.6], vertical_alignment="center")
            c0.markdown(f'<div class="fs-barnote">선택한 <b>{count}개</b> 파일을 정리해요 · 언제든 되돌릴 수 있어요</div>',
                        unsafe_allow_html=True)
            rescan = c1.button("다시 살펴보기", use_container_width=True)
            cancel = c2.button("취소", use_container_width=True)
            apply = c3.button(f"{count}개 정리하기", type="primary", use_container_width=True, disabled=count == 0)
        if apply:
            original = {i["id"]: i for i in items}
            for row in edited.to_dict("records"):
                old = original[int(row["id"])]
                patch = {}
                if row["새 이름"] != old["new_name"]:
                    patch["new_name"] = row["새 이름"]
                if row["넣을 폴더"] != old["dest_dir"]:
                    patch["dest_dir"] = row["넣을 폴더"]
                if bool(row["포함"]) != old["include"]:
                    patch["include"] = bool(row["포함"])
                if patch:
                    api("PATCH", f"/api/v1/plans/{plan['id']}/items/{old['id']}", json=patch)
            result = api("POST", f"/api/v1/plans/{plan['id']}/apply", timeout=300)
            if result is not None:
                st.session_state["batch"] = result
                st.session_state.pop("plan", None)
                st.rerun()
        if rescan:
            start_scan()
        if cancel:
            api("DELETE", f"/api/v1/plans/{plan['id']}")
            st.session_state.pop("plan", None)
            st.rerun()


# ---------------------------------------------------------------------------
# 2. 찾기
# ---------------------------------------------------------------------------
EXAMPLES = ["기말 프로젝트 공지", "카페 와이파이 비밀번호", "이번 달 영수증", "자료구조 시험 범위"]


def use_example() -> None:
    """예시 질문을 누르면 검색창에 넣는다 (같은 예시를 다시 누를 수 있게 선택은 바로 지운다)."""
    picked = st.session_state.get("example")
    if picked:
        st.session_state["query"] = picked
        st.session_state["example"] = None


def file_icon(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return EXT_LABEL.get(ext, (ext[:3] or "FILE").upper())


with tab_find:
    _, mid, _ = st.columns([1, 6, 1])
    with mid:
        heading("무엇을 찾을까요?", "말하듯 적어 보세요. 파일 이름이 아니라 <b>내용</b>으로 찾아 드려요.")
        with st.container(key="searchbox"):
            with st.form("search-form", border=False):
                c1, c2 = st.columns([6, 1], vertical_alignment="center")
                q = c1.text_input("검색어", key="query", label_visibility="collapsed",
                                  placeholder="예: 교수님이 보낸 기말 프로젝트 공지 찾아줘")
                submitted = c2.form_submit_button("찾기", type="primary", use_container_width=True)
        st.pills("예시 질문", EXAMPLES, key="example", on_change=use_example, label_visibility="collapsed")

        if (submitted or st.session_state.get("query")) and q.strip():
            if submitted or st.session_state.get("search", {}).get("query") != q:
                with st.spinner("찾는 중…"):
                    started = time.perf_counter()
                    st.session_state["search"] = api("GET", "/api/v1/search", params={"q": q}, timeout=120) or {}
                    st.session_state["search_secs"] = time.perf_counter() - started
            res = st.session_state.get("search") or {}
            if res:
                secs = st.session_state.get("search_secs", 0)
                st.markdown(
                    f'<div class="fs-answer"><div class="ai">AI</div><div><div class="a">{esc(res["answer"])}</div>'
                    f'<div class="meta"><span class="fs-chip src">{SOURCE_LABEL.get(res["source"], res["source"])}</span>'
                    f'결과 {len(res["results"])}개 · {secs:.1f}초</div></div></div>', unsafe_allow_html=True)
                for n, hit in enumerate(res["results"]):
                    f = hit["file"]
                    chips = f'<span class="fs-chip">{esc(f["category"])}</span>'
                    if f["course"]:
                        chips += f'<span class="fs-chip g">{esc(f["course"])}</span>'
                    if f["date"]:
                        chips += f'<span class="fs-chip g">{esc(f["date"])}</span>'
                    if f["sensitive"]:
                        chips += '<span class="fs-chip lock">개인 서류 · AI에 안 보여 줌</span>'
                    card, btn = st.columns([6, 1], vertical_alignment="center")
                    card.markdown(
                        f'<div class="fs-res"><div class="fs-ico">{file_icon(f["path_rel"])}</div><div>'
                        f'<div class="t">{esc(f["title"] or f["original_name"])}</div>'
                        f'<div class="p">{esc(f["path_rel"])}</div>{chips}'
                        f'<div class="s">{esc(f["summary"])}</div>'
                        f'<div class="r">→ {esc(hit["reason"])}</div></div></div>', unsafe_allow_html=True)
                    if n < 5 and f["size"] <= 20 * 1024 * 1024:
                        data = api("GET", f"/api/v1/files/{f['id']}/content")
                        if isinstance(data, bytes):
                            btn.download_button(f"열기 · {human(f['size'])}", data=data, use_container_width=True,
                                                file_name=f["path_rel"].rsplit("/", 1)[-1], key=f"dl-{f['id']}")


# ---------------------------------------------------------------------------
# 3. 정리 기록
# ---------------------------------------------------------------------------
with tab_log:
    heading("정리 기록", "언제 어떤 파일을 옮겼는지 모두 남아 있어요. 어느 기록이든 되돌릴 수 있어요.")
    batches = api("GET", "/api/v1/batches") or []
    if not batches:
        note("아직 정리한 기록이 없어요.")
    for b in batches:
        state = f"되돌림 ({kst(b['undone_at'])})" if b["undone_at"] else "정리됨"
        with st.expander(f"#{b['id']}  ·  {kst(b['created_at'])}  ·  {b['moved']}개 정리  ·  {state}"):
            st.dataframe(pd.DataFrame([{"원래 위치": m["src_rel"], "정리된 위치": m["dst_rel"],
                                        "상태": STATUS_LABEL.get(m["status"], m["status"]), "메모": m["error"] or ""} for m in b["moves"]]),
                         hide_index=True, use_container_width=True)
            if not b["undone_at"] and st.button("이 정리 되돌리기", key=f"undo-{b['id']}"):
                if api("POST", f"/api/v1/batches/{b['id']}/undo") is not None:
                    st.session_state.pop("batch", None)
                    st.toast("되돌렸어요.")
                    st.rerun()


# ---------------------------------------------------------------------------
# 4. 설정
# ---------------------------------------------------------------------------
with tab_cfg:
    heading("설정", "바꾼 내용은 다음에 '폴더 살펴보기'를 누를 때부터 적용돼요.")
    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.form("settings-form"):
            st.markdown('<div class="fs-sec">내 과목 목록</div>', unsafe_allow_html=True)
            courses = st.text_area(
                "한 줄에 한 과목씩 적어 주세요. 다르게 부르는 이름은 콜론 뒤에 쉼표로 (예: 기계학습: 머신러닝, ML)",
                value="\n".join(cfg.get("courses", [])), height=150)
            st.markdown('<div class="fs-sec">새 이름 규칙</div>', unsafe_allow_html=True)
            keys = list(PATTERNS)
            pattern = st.radio("이름 규칙", keys, index=keys.index(cfg.get("name_pattern", keys[0])),
                               format_func=PATTERNS.get, label_visibility="collapsed")
            st.markdown('<div class="fs-sec">개인정보</div>', unsafe_allow_html=True)
            analyze_images = st.toggle("사진 내용도 AI에게 보여 주기", value=cfg.get("analyze_images", True),
                                       help="끄면 사진은 파일 이름과 내 컴퓨터 안에서 읽은 글자로만 분류해요.")
            extra = st.text_area("이 단어가 들어간 파일은 AI에게 보여 주지 않기 (한 줄에 하나)",
                                 value="\n".join(cfg.get("extra_sensitive_keywords", [])), height=80,
                                 placeholder="예: 성적증명서")
            if st.form_submit_button("저장", type="primary"):
                body = {"courses": [c for c in courses.splitlines() if c.strip()], "name_pattern": pattern,
                        "analyze_images": analyze_images,
                        "extra_sensitive_keywords": [k for k in extra.splitlines() if k.strip()]}
                if api("PUT", "/api/v1/settings", json=body) is not None:
                    st.toast("저장했어요. 다음 '폴더 살펴보기'부터 적용돼요.")
                    st.rerun()
    with right:
        dev_status()
        with st.container(border=True, key="card-3"):
            st.markdown('<div class="fs-sec">정리 폴더</div>', unsafe_allow_html=True)
            st.code(cfg.get("target_dir", "?"), language=None)
            st.caption("다른 폴더를 정리하려면 설정 파일(`.env`)의 `HOST_TARGET_DIR`를 고친 뒤 `docker compose up -d`로 다시 시작해 주세요. "
                       "(Windows 예: `HOST_TARGET_DIR=C:/Users/내아이디/Downloads`)")
        if cfg.get("demo_reset_available"):
            with st.container(border=True, key="card-4"):
                st.markdown('<div class="fs-sec">연습 폴더</div>', unsafe_allow_html=True)
                st.caption("연습용 파일을 처음 상태로 되돌려요.")
                if st.button("연습 폴더 초기화", use_container_width=True):
                    res = api("POST", "/api/v1/demo/reset", timeout=120)
                    if res is not None:
                        for key in ("plan", "batch", "search"):
                            st.session_state.pop(key, None)
                        st.toast(f"연습용 파일 {res.get('copied', 0)}개를 다시 넣었어요.")
                        st.rerun()
        with st.container(border=True, key="card-5"):
            st.markdown('<div class="fs-sec">KNIME 실습용 데이터</div>', unsafe_allow_html=True)
            st.caption("파일 정보와 분류 결과를 표(CSV)로 내려받아요. KNIME 실습에 쓸 수 있고, AI를 새로 부르지 않아요. "
                       "사용법은 `knime/README.md`에 있어요.")
            if st.button("CSV 만들기", use_container_width=True):
                with st.spinner("파일을 읽는 중이에요… 사진이 많으면 조금 걸려요."):
                    data = api("GET", "/api/v1/export/knime.csv", timeout=300)
                if isinstance(data, (bytes, bytearray)):
                    st.session_state["knime_csv"] = bytes(data)
            if st.session_state.get("knime_csv"):
                st.download_button("knime_files.csv 내려받기", data=st.session_state["knime_csv"],
                                   file_name="knime_files.csv", mime="text/csv", use_container_width=True)
        st.markdown(f'<p class="fs-lead" style="margin-top:8px">개발자용: <a href="{PUBLIC_API_URL}/docs" '
                    f'target="_blank">API 문서 (/docs)</a></p>', unsafe_allow_html=True)
