"""파일 정리 비서 대시보드 (Streamlit).

API 서버(FastAPI)를 REST로 호출해서 화면에 보여 주는 '클라이언트'다.
실행: streamlit run app.py  →  http://localhost:8501
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")         # 컨테이너 안에서는 http://api:8000
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://localhost:8000").rstrip("/")  # 브라우저에서 여는 주소
API_KEY = os.getenv("SECRETARY_API_KEY", "")
KST = ZoneInfo("Asia/Seoul")

CATEGORY_ICON = {"수업": "📚", "문서": "📄", "개인서류": "🔒", "영수증·결제": "🧾", "사진": "🖼️",
                 "스크린샷": "📱", "영상·음성": "🎧", "설치파일": "💿", "압축파일": "🗜️", "기타": "📦",
                 "중복 파일": "🧺"}
PATTERNS = {
    "date_course_title": "날짜_과목_제목  (2026-11-09_오픈소스프로그래밍_기말 프로젝트 안내.pdf)",
    "course_title_date": "과목_제목_날짜  (오픈소스프로그래밍_기말 프로젝트 안내_2026-11-09.pdf)",
    "title_date": "제목_날짜  (기말 프로젝트 안내_2026-11-09.pdf)",
    "title_only": "제목만  (기말 프로젝트 안내.pdf)",
}
SOURCE_LABEL = {"gemini": "Gemini", "mock": "규칙", "fallback": "규칙(대체)", "rule": "보호·중복"}

st.set_page_config(page_title="파일 정리 비서", page_icon="🗂️", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
/* 글자를 키우고(발표·확대 화면에서도 읽히게) 폭을 넓힌다 */
html {font-size: 17px;}
html, body, .stApp {font-family: "Pretendard", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif;}
.block-container {padding-top: 2rem; padding-left: 3rem; padding-right: 3rem; max-width: 1560px;}
[data-testid="stHeaderActionElements"] {display: none;}
button[data-baseweb="tab"] p {font-size: 1.08rem; font-weight: 600;}
div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button {border-radius: 10px;}

.fs-hero {background: linear-gradient(135deg, #1E1B4B 0%, #3730A3 55%, #4F46E5 100%); color: #fff;
          border-radius: 20px; padding: 28px 34px; margin-bottom: 16px;}
.fs-hero h1 {color: #fff; font-size: 2.3rem; margin: 0 0 6px 0; padding: 0; letter-spacing: -0.02em;}
.fs-hero p {margin: 0; opacity: .92; font-size: 1.08rem;}

.fs-status {display: flex; flex-wrap: wrap; gap: 10px; margin: 0 0 22px 0;}
.fs-chip {background: #fff; border: 1px solid #E2E4F0; border-radius: 14px; padding: 10px 16px;
          font-size: .98rem; line-height: 1.3; min-width: 150px;}
.fs-chip small {display: block; font-size: .78rem; color: #6B7280; font-weight: 600; margin-bottom: 3px;}
.fs-chip.ok {background: #EEF2FF; border-color: #C7D2FE;}
.fs-chip.warn {background: #FFF7ED; border-color: #FED7AA;}
.fs-chip .num {font-size: 1.5rem; font-weight: 700; color: #3730A3;}

.fs-tree {background: #F7F8FC; border: 1px solid #E2E4F0; border-radius: 14px; padding: 16px 18px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .92rem;
          line-height: 1.6; white-space: pre; overflow-x: auto; max-height: 520px; overflow-y: auto;}
.fs-tree .dir {color: #3730A3; font-weight: 700;}
.fs-tree .muted {color: #8A94A0;}
.fs-card {border: 1px solid #E2E4F0; border-radius: 16px; padding: 16px 20px; margin-bottom: 12px; background: #fff;
          box-shadow: 0 1px 2px rgba(30, 27, 75, .04);}
.fs-card .title {font-weight: 700; font-size: 1.12rem;}
.fs-card .path {font-family: ui-monospace, Menlo, Consolas, monospace; color: #57606A; font-size: .88rem;}
.fs-badge {display: inline-block; background: #EEF2FF; color: #3730A3; border-radius: 999px; padding: 2px 12px;
           font-size: .84rem; margin-right: 6px;}
.fs-badge.warn {background: #FFF4E5; color: #9A5B00;}
.fs-badge.lock {background: #FDECEC; color: #B42318;}
.fs-answer {background: #EEF2FF; border-left: 4px solid #4F46E5; padding: 12px 16px; border-radius: 10px;
            margin: 6px 0 16px 0; font-size: 1.02rem;}
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
        st.error(f"API 서버({API_URL})에 연결할 수 없습니다. 서버가 켜져 있는지 확인해 주세요.")
        st.stop()
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        st.error(f"요청 실패 ({r.status_code}): {detail}")
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


def render_tree(tree: dict, title: str, max_files: int = 6) -> str:
    lines = [f'<span class="dir">📂 {html.escape(title)}</span>']

    def walk(node: dict, prefix: str) -> None:
        dirs = sorted(k for k in node if k.endswith("/"))
        files = sorted(k for k in node if not k.endswith("/"))
        entries = dirs + files[:max_files]
        hidden = len(files) - min(len(files), max_files)
        for i, key in enumerate(entries):
            last = i == len(entries) - 1 and hidden == 0
            branch = "└─ " if last else "├─ "
            if key.endswith("/"):
                name = key[:-1]
                icon = CATEGORY_ICON.get(name, "📁")
                lines.append(f'{prefix}{branch}<span class="dir">{icon} {html.escape(name)}</span>')
                walk(node[key], prefix + ("   " if last else "│  "))
            else:
                lines.append(f"{prefix}{branch}{html.escape(key)}")
        if hidden:
            lines.append(f'{prefix}└─ <span class="muted">… 외 {hidden}개</span>')

    walk(tree, "")
    return '<div class="fs-tree">' + "\n".join(lines) + "</div>"


# ---------------------------------------------------------------------------
# 머리말·사이드바
# ---------------------------------------------------------------------------
health = api("GET", "/health") or {}
cfg = api("GET", "/api/v1/settings") or {}
stats = api("GET", "/api/v1/stats") or {}
watcher = api("GET", "/api/v1/watcher") or {}


def watcher_line(w: dict) -> str:
    """폴더 감시 데몬 상태 한 줄."""
    if not w.get("running"):
        return "🛰️ 폴더 감시: 꺼짐"
    total, ready = w.get("loose", 0), w.get("ready", 0)
    icon = "⏳" if w.get("state") == "analyzing" else ("✅" if total and ready >= total else "🛰️")
    count = f" ({ready}/{total})" if total else ""
    return f"{icon} 폴더 감시: {w.get('message', '')}{count}"

st.markdown('<div class="fs-hero"><h1>🗂️ 파일 정리 비서</h1>'
            '<p>생성 AI가 파일 내용을 읽고 → 알아보기 쉬운 이름을 짓고 → 폴더별로 정리하고 → 말로 찾아 드립니다.</p></div>',
            unsafe_allow_html=True)


def chip(label: str, value: str, kind: str = "", num: bool = False) -> str:
    body = f'<span class="num">{html.escape(value)}</span>' if num else html.escape(value)
    return f'<div class="fs-chip {kind}"><small>{html.escape(label)}</small>{body}</div>'


# 핵심 상태는 본문 맨 위에 둔다 (화면을 확대해서 사이드바가 접혀도 보이도록)
is_gemini = cfg.get("llm_mode") == "gemini"
watch_text = watcher_line(watcher).replace("폴더 감시: ", "", 1)
st.markdown(
    '<div class="fs-status">'
    + chip("AI 분석", f"Gemini · {cfg.get('gemini_model', '')}" if is_gemini else "규칙 기반", "ok" if is_gemini else "warn")
    + chip("이미지 속 민감 정보 확인(OCR)", "켜짐" if cfg.get("ocr_enabled") else "꺼짐")
    + chip("폴더 감시", watch_text, "ok" if watcher.get("running") else "warn")
    + chip("흩어진 파일", str(stats.get("loose_files", 0)), num=True)
    + chip("정리된 파일", str(stats.get("organized_files", 0)), num=True)
    + "</div>", unsafe_allow_html=True)
if not is_gemini:
    st.warning("AI 분석이 **규칙 기반**입니다. `.env`에 `GEMINI_API_KEY`를 넣으면 AI가 파일 내용을 읽습니다.")

with st.sidebar:
    st.subheader("정리 폴더")
    st.code(cfg.get("target_dir", "?"), language=None)
    if cfg.get("demo_reset_available"):
        st.divider()
        st.caption("연습 폴더를 '정리 전' 상태로 되돌립니다 (발표 리허설용).")
        if st.button("🔁 연습 폴더 초기화", use_container_width=True):
            res = api("POST", "/api/v1/demo/reset", timeout=120)
            if res is not None:
                for key in ("plan", "batch", "search"):
                    st.session_state.pop(key, None)
                st.toast(f"샘플 파일 {res.get('copied', 0)}개를 다시 넣었습니다.", icon="🔁")
                st.rerun()
    st.divider()
    st.markdown(f"[📘 API 문서 (/docs)]({PUBLIC_API_URL}/docs)")


tab_clean, tab_find, tab_log, tab_cfg = st.tabs(["🧹 정리하기", "🔍 찾기", "🗂️ 정리 기록", "⚙️ 설정"])


# ---------------------------------------------------------------------------
# 1. 정리하기
# ---------------------------------------------------------------------------
def start_scan() -> None:
    with st.spinner("AI가 파일 내용을 읽고 있습니다… (파일 수와 이미지 개수에 따라 수십 초 걸릴 수 있어요)"):
        plan = api("POST", "/api/v1/plans", json={}, timeout=900)
    if plan is not None:
        st.session_state["plan"] = plan
        st.session_state.pop("batch", None)
        st.rerun()


def item_note(it: dict) -> str:
    notes = []
    if it["sensitive"]:
        notes.append(f"🔒 AI에 안 보냄 ({it['sensitive_reason']})")
    notes += it["flags"]
    if it.get("error"):
        notes.append(f"⚠️ {it['error']}")
    return " · ".join(notes)


with tab_clean:
    plan = st.session_state.get("plan")
    batch = st.session_state.get("batch")

    if batch:  # ---- 정리 직후 ----
        st.success(f"✅ 파일 {batch['moved']}개를 정리했습니다." +
                   (f" (건너뜀 {batch['skipped']}개)" if batch["skipped"] else ""))
        skipped = [m for m in batch["moves"] if m["status"] == "skipped"]
        if skipped:
            with st.expander(f"건너뛴 파일 {len(skipped)}개"):
                for m in skipped:
                    st.write(f"- `{m['src_rel']}` — {m['error']}")
        tree = api("GET", "/api/v1/tree", params={"depth": 3}) or {}
        left, right = st.columns([3, 2])
        with left:
            st.markdown("##### 📂 지금 폴더 모습")
            st.markdown(render_tree(tree_from_api(tree), "정리 폴더", max_files=4), unsafe_allow_html=True)
        with right:
            st.markdown("##### 다음 할 일")
            st.info("**🔍 찾기** 탭에서 '기말 프로젝트 공지'처럼 말로 검색해 보세요.")
            if st.button("↩️ 방금 정리 되돌리기", use_container_width=True):
                res = api("POST", f"/api/v1/batches/{batch['id']}/undo")
                if res is not None:
                    st.session_state.pop("batch", None)
                    st.session_state.pop("plan", None)
                    st.toast("원래대로 되돌렸습니다.", icon="↩️")
                    st.rerun()
            if st.button("📂 다시 살펴보기", use_container_width=True):
                start_scan()
            with st.expander("🐧 되돌리기 명령어"):
                undo = api("GET", f"/api/v1/batches/{batch['id']}/script")
                if isinstance(undo, (bytes, bytearray)):
                    st.code(undo.decode("utf-8"), language="bash")

    elif not plan:  # ---- 시작 화면 ----
        loose = stats.get("loose_files", 0)
        left, right = st.columns([3, 2])
        with left:
            st.markdown(f"#### 정리 폴더에 흩어진 파일 **{loose}개**")
            st.write("**폴더 살펴보기**를 누르면 AI가 파일 내용을 읽고 새 이름과 폴더를 제안합니다. "
                     "파일은 **확인을 누르기 전까지 옮기지 않습니다.**")
            if watcher.get("running") and loose:
                ready, total = watcher.get("ready", 0), watcher.get("loose", 0)
                if total and ready >= total:
                    st.success("✅ 폴더 감시 데몬이 새 파일을 모두 미리 읽어 두었습니다. 살펴보기가 바로 끝납니다.")
                else:
                    st.info(f"🛰️ 폴더 감시 데몬이 새 파일을 미리 읽는 중입니다 ({ready}/{total}). "
                            "끝난 뒤에 누르면 기다리지 않습니다. 새로고침하면 진행 상황이 바뀝니다.")
            if st.button("📂 폴더 살펴보기", type="primary", disabled=loose == 0):
                start_scan()
            if loose == 0:
                st.caption("정리할 파일이 없습니다. 사이드바의 '연습 폴더 초기화'로 샘플을 넣어 보세요.")
        with right:
            tree = api("GET", "/api/v1/tree", params={"depth": 1}) or {}
            st.markdown(render_tree(tree_from_api(tree), "정리 전", max_files=12), unsafe_allow_html=True)

    else:  # ---- 미리보기 ----
        items = plan["items"]
        n_sensitive = sum(i["sensitive"] for i in items)
        n_dup = sum(i["dest_dir"] == "중복 파일" for i in items)
        n_old = sum(any("설치 파일" in f for f in i["flags"]) for i in items)
        n_ai = sum(i["source"] == "gemini" for i in items)
        m = st.columns(5)
        m[0].metric("살펴본 파일", len(items))
        m[1].metric("AI가 읽은 파일", n_ai if cfg.get("llm_mode") == "gemini" else "규칙 기반")
        m[2].metric("🔒 민감 파일", n_sensitive, help="내용을 AI에 보내지 않고 '개인서류'로만 정리")
        m[3].metric("🧺 중복 파일", n_dup)
        m[4].metric("💿 오래된 설치 파일", n_old)
        if plan["llm_source"] == "fallback":
            st.warning("Gemini 호출이 일부 실패해서 그 파일들은 규칙 기반으로 분석했습니다. (항목의 '분석' 열 참고)")

        before, after = st.columns(2)
        with before:
            st.markdown("##### 정리 전")
            st.markdown(render_tree(tree_from_paths([i["src_rel"] for i in items]), "정리 폴더", max_files=14),
                        unsafe_allow_html=True)
        with after:
            st.markdown("##### 정리 후 (미리보기)")
            paths = [f"{i['dest_dir']}/{i['new_name']}" if i["include"] else i["src_rel"] for i in items]
            st.markdown(render_tree(tree_from_paths(paths), "정리 폴더", max_files=3), unsafe_allow_html=True)

        st.markdown("##### 제안 확인·수정")
        st.caption("새 이름과 옮길 폴더는 표에서 바로 고칠 수 있습니다. 옮기지 않을 파일은 '포함'을 끄세요.")
        df = pd.DataFrame([{
            "포함": i["include"], "원래 이름": i["src_rel"], "새 이름": i["new_name"], "옮길 폴더": i["dest_dir"],
            "분류": f"{CATEGORY_ICON.get(i['category'], '')} {i['category']}", "요약": i["summary"],
            "알림": item_note(i), "분석": SOURCE_LABEL.get(i["source"], i["source"]), "id": i["id"],
        } for i in items])
        edited = st.data_editor(
            df, hide_index=True, use_container_width=True, height=min(620, 38 + 35 * len(df)),
            disabled=["원래 이름", "분류", "요약", "알림", "분석", "id"],
            column_order=["포함", "원래 이름", "새 이름", "옮길 폴더", "분류", "요약", "알림", "분석"],
            column_config={
                "포함": st.column_config.CheckboxColumn(width="small"),
                "원래 이름": st.column_config.TextColumn(width="medium"),
                "새 이름": st.column_config.TextColumn(width="large"),
                "옮길 폴더": st.column_config.TextColumn(width="medium"),
                "요약": st.column_config.TextColumn(width="large"),
                "알림": st.column_config.TextColumn(width="medium"),
            }, key=f"editor-{plan['id']}")

        count = int(edited["포함"].sum())
        b1, b2, b3 = st.columns([2, 1, 1])
        if b1.button(f"✅ 선택한 {count}개 정리하기", type="primary", use_container_width=True, disabled=count == 0):
            original = {i["id"]: i for i in items}
            for row in edited.to_dict("records"):
                old = original[int(row["id"])]
                patch = {}
                if row["새 이름"] != old["new_name"]:
                    patch["new_name"] = row["새 이름"]
                if row["옮길 폴더"] != old["dest_dir"]:
                    patch["dest_dir"] = row["옮길 폴더"]
                if bool(row["포함"]) != old["include"]:
                    patch["include"] = bool(row["포함"])
                if patch:
                    api("PATCH", f"/api/v1/plans/{plan['id']}/items/{old['id']}", json=patch)
            result = api("POST", f"/api/v1/plans/{plan['id']}/apply", timeout=300)
            if result is not None:
                st.session_state["batch"] = result
                st.session_state.pop("plan", None)
                st.rerun()
        if b2.button("🔄 다시 살펴보기", use_container_width=True):
            start_scan()
        if b3.button("취소", use_container_width=True):
            api("DELETE", f"/api/v1/plans/{plan['id']}")
            st.session_state.pop("plan", None)
            st.rerun()

        with st.expander("🐧 이 정리를 리눅스 명령어로 보기"):
            st.caption("서비스가 하는 일은 결국 `mkdir -p`(폴더 만들기)와 `mv -n`(옮기며 이름 바꾸기, 덮어쓰지 않음)입니다. "
                       "지우는 명령은 없습니다. 내려받아 정리 폴더에서 `bash plan.sh`로 직접 실행해도 같은 결과가 나옵니다. "
                       "(표에서 고친 내용은 '정리하기'를 누를 때 반영되므로, 아래는 AI 제안 기준입니다.)")
            script = api("GET", f"/api/v1/plans/{plan['id']}/script")
            if isinstance(script, (bytes, bytearray)):
                text = script.decode("utf-8")
                st.code(text, language="bash")
                st.download_button("⬇️ 셸 스크립트 내려받기", data=text.encode("utf-8"),
                                   file_name=f"plan-{plan['id']}.sh", mime="text/x-shellscript")


# ---------------------------------------------------------------------------
# 2. 찾기
# ---------------------------------------------------------------------------
EXAMPLES = ["기말 프로젝트 공지", "카페 와이파이 비밀번호", "이번 달 영수증", "자료구조 시험 범위"]

with tab_find:
    st.markdown("#### 무엇을 찾을까요?")
    cols = st.columns(len(EXAMPLES))
    for col, example in zip(cols, EXAMPLES):
        if col.button(example, use_container_width=True):
            st.session_state["query"] = example
    with st.form("search-form", border=False):
        q = st.text_input("검색어", key="query", label_visibility="collapsed",
                          placeholder="예: 교수님이 보낸 기말 프로젝트 공지 찾아줘")
        submitted = st.form_submit_button("🔍 찾기", type="primary")
    if (submitted or st.session_state.get("query")) and q.strip():
        if submitted or st.session_state.get("search", {}).get("query") != q:
            with st.spinner("찾는 중…"):
                st.session_state["search"] = api("GET", "/api/v1/search", params={"q": q}, timeout=120) or {}
        res = st.session_state.get("search") or {}
        if res:
            st.markdown(f'<div class="fs-answer">💬 {html.escape(res["answer"])} '
                        f'<span class="fs-badge">{SOURCE_LABEL.get(res["source"], res["source"])}</span></div>',
                        unsafe_allow_html=True)
            for n, hit in enumerate(res["results"]):
                f = hit["file"]
                badges = f'<span class="fs-badge">{CATEGORY_ICON.get(f["category"], "")} {html.escape(f["category"])}</span>'
                if f["course"]:
                    badges += f'<span class="fs-badge">{html.escape(f["course"])}</span>'
                if f["date"]:
                    badges += f'<span class="fs-badge">{f["date"]}</span>'
                if f["sensitive"]:
                    badges += '<span class="fs-badge lock">🔒 민감</span>'
                st.markdown(
                    f'<div class="fs-card"><div class="title">{html.escape(f["title"] or f["original_name"])}</div>'
                    f'<div class="path">📁 {html.escape(f["path_rel"])}</div><div style="margin:6px 0">{badges}</div>'
                    f'<div>{html.escape(f["summary"])}</div>'
                    f'<div style="color:#57606A;font-size:.88rem;margin-top:4px">👉 {html.escape(hit["reason"])}</div></div>',
                    unsafe_allow_html=True)
                if n < 5 and f["size"] <= 20 * 1024 * 1024:
                    data = api("GET", f"/api/v1/files/{f['id']}/content")
                    if isinstance(data, bytes):
                        st.download_button(f"⬇️ 열기 ({human(f['size'])})", data=data,
                                           file_name=f["path_rel"].rsplit("/", 1)[-1], key=f"dl-{f['id']}")


# ---------------------------------------------------------------------------
# 3. 정리 기록
# ---------------------------------------------------------------------------
with tab_log:
    batches = api("GET", "/api/v1/batches") or []
    if not batches:
        st.info("아직 정리한 기록이 없습니다.")
    for b in batches:
        state = f"↩️ 되돌림 ({kst(b['undone_at'])})" if b["undone_at"] else "✅ 적용됨"
        with st.expander(f"#{b['id']} · {kst(b['created_at'])} · {b['moved']}개 정리 · {state}"):
            st.dataframe(pd.DataFrame([{"원래 위치": m["src_rel"], "→ 정리된 위치": m["dst_rel"],
                                        "상태": m["status"], "메모": m["error"] or ""} for m in b["moves"]]),
                         hide_index=True, use_container_width=True)
            if not b["undone_at"] and st.button("이 정리 되돌리기", key=f"undo-{b['id']}"):
                if api("POST", f"/api/v1/batches/{b['id']}/undo") is not None:
                    st.session_state.pop("batch", None)
                    st.toast("되돌렸습니다.", icon="↩️")
                    st.rerun()


# ---------------------------------------------------------------------------
# 4. 설정
# ---------------------------------------------------------------------------
with tab_cfg:
    with st.form("settings-form"):
        st.markdown("#### 내 과목 목록")
        courses = st.text_area(
            "한 줄에 한 과목. 별칭은 콜론 뒤에 쉼표로 (예: 기계학습: 머신러닝, ML)",
            value="\n".join(cfg.get("courses", [])), height=150)
        st.markdown("#### 새 이름 규칙")
        keys = list(PATTERNS)
        pattern = st.radio("이름 규칙", keys, index=keys.index(cfg.get("name_pattern", keys[0])),
                           format_func=PATTERNS.get, label_visibility="collapsed")
        st.markdown("#### 개인정보")
        analyze_images = st.toggle("이미지 내용을 AI로 분석하기", value=cfg.get("analyze_images", True),
                                   help="끄면 이미지는 파일 이름과 내 컴퓨터 OCR로만 분류합니다.")
        extra = st.text_area("민감 파일로 볼 단어 추가 (한 줄에 하나)",
                             value="\n".join(cfg.get("extra_sensitive_keywords", [])), height=80,
                             placeholder="예: 성적증명서")
        if st.form_submit_button("저장", type="primary"):
            body = {"courses": [c for c in courses.splitlines() if c.strip()], "name_pattern": pattern,
                    "analyze_images": analyze_images,
                    "extra_sensitive_keywords": [k for k in extra.splitlines() if k.strip()]}
            if api("PUT", "/api/v1/settings", json=body) is not None:
                st.toast("저장했습니다. 다음 '폴더 살펴보기'부터 적용됩니다.", icon="💾")
                st.rerun()
    st.info("정리 폴더를 바꾸려면 `.env`의 `HOST_TARGET_DIR`를 고친 뒤 `docker compose up -d`로 다시 시작하세요.\n\n"
            "Windows 예: `HOST_TARGET_DIR=C:/Users/내아이디/Downloads`")

    st.markdown("#### 📊 KNIME 실습용 데이터")
    st.caption("정리 폴더의 파일마다 이름 특징·규칙 분류·Gemini 분류(미리 저장된 것)·정답(연습 폴더)을 CSV로 내려받습니다. "
               "Gemini를 새로 부르지 않습니다. 사용법은 `knime/README.md`를 보세요.")
    if st.button("CSV 만들기"):
        with st.spinner("파일을 읽는 중… (이미지 글자 인식 때문에 수십 초 걸릴 수 있어요)"):
            data = api("GET", "/api/v1/export/knime.csv", timeout=300)
        if isinstance(data, (bytes, bytearray)):
            st.session_state["knime_csv"] = bytes(data)
    if st.session_state.get("knime_csv"):
        st.download_button("⬇️ knime_files.csv 내려받기", data=st.session_state["knime_csv"],
                           file_name="knime_files.csv", mime="text/csv")
