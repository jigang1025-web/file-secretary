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

st.set_page_config(page_title="파일 정리 비서", page_icon="🗂️", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 2.2rem; max-width: 1280px;}
[data-testid="stHeaderActionElements"] {display: none;}
.fs-hero {background: linear-gradient(135deg, #0F6E56 0%, #138A6C 60%, #1FA37F 100%); color: #fff;
          border-radius: 18px; padding: 22px 28px; margin-bottom: 18px;}
.fs-hero h1 {color: #fff; font-size: 2.0rem; margin: 0 0 4px 0; padding: 0;}
.fs-hero p {margin: 0; opacity: .92; font-size: 1.02rem;}
.fs-tree {background: #F6F8FA; border: 1px solid #E3E8EE; border-radius: 12px; padding: 14px 16px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .86rem;
          line-height: 1.55; white-space: pre; overflow-x: auto; max-height: 460px; overflow-y: auto;}
.fs-tree .dir {color: #0F6E56; font-weight: 700;}
.fs-tree .muted {color: #8A94A0;}
.fs-card {border: 1px solid #E3E8EE; border-radius: 14px; padding: 14px 18px; margin-bottom: 10px; background: #fff;}
.fs-card .title {font-weight: 700; font-size: 1.05rem;}
.fs-card .path {font-family: ui-monospace, Menlo, Consolas, monospace; color: #57606A; font-size: .85rem;}
.fs-badge {display: inline-block; background: #E8F5EF; color: #0F6E56; border-radius: 999px; padding: 1px 10px;
           font-size: .8rem; margin-right: 6px;}
.fs-badge.warn {background: #FFF4E5; color: #9A5B00;}
.fs-badge.lock {background: #FDECEC; color: #B42318;}
.fs-answer {background: #F0F7FF; border-left: 4px solid #2F6FEB; padding: 10px 14px; border-radius: 8px;
            margin: 6px 0 14px 0;}
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

with st.sidebar:
    st.subheader("상태")
    if cfg.get("llm_mode") == "gemini":
        st.success(f"AI 분석: **Gemini** (`{cfg.get('gemini_model')}`)")
    else:
        st.warning("AI 분석: **규칙 기반** (Gemini 키 없음)\n\n`.env`에 `GEMINI_API_KEY`를 넣으면 AI가 내용을 읽습니다.")
    st.caption(f"🔒 이미지 속 민감 정보 확인(OCR): {'켜짐' if cfg.get('ocr_enabled') else '꺼짐'}")
    st.caption(watcher_line(watcher))
    st.subheader("정리 폴더")
    st.code(cfg.get("target_dir", "?"), language=None)
    c1, c2 = st.columns(2)
    c1.metric("흩어진 파일", stats.get("loose_files", 0))
    c2.metric("정리된 파일", stats.get("organized_files", 0))
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
