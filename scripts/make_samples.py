"""연습용 '지저분한 다운로드 폴더' 샘플 파일을 만든다 (demo/samples/).

이미 만들어진 샘플이 저장소에 들어 있으므로 보통은 실행할 필요가 없다.
다시 만들려면: python scripts/make_samples.py   (PDF 변환에 LibreOffice, 글꼴에 Noto Sans CJK 필요)

모든 이름·계좌·번호는 지어낸 예시다.
"""
from __future__ import annotations

import json
import math
import random
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pptx import Presentation
from pptx.util import Pt as PPt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo" / "samples"
FONT_PATHS = [Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
              Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")]
KR_FONT = "Noto Sans CJK KR"
random.seed(7)


def kr_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_PATHS[1 if bold else 0]
    for index in range(10):
        font = ImageFont.truetype(str(path), size, index=index)
        if "KR" in font.getname()[0]:
            return font
    return ImageFont.truetype(str(path), size)


# ---------------------------------------------------------------------------
# 문서
# ---------------------------------------------------------------------------
def _docx(path: Path, title: str, lines: list[str], table: list[list[str]] | None = None) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = KR_FONT
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), KR_FONT)
    heading = doc.add_heading(title, level=1)
    for run in heading.runs:
        run.font.name = KR_FONT
        run.element.rPr.rFonts.set(qn("w:eastAsia"), KR_FONT)
    for line in lines:
        doc.add_paragraph(line)
    if table:
        t = doc.add_table(rows=len(table), cols=len(table[0]))
        t.style = "Table Grid"
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                t.cell(r, c).text = value
    doc.save(path)


def _pdf(name: str, title: str, lines: list[str], table: list[list[str]] | None = None) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / (Path(name).stem + ".docx")
        _docx(src, title, lines, table)
        subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
                       check=True, capture_output=True, timeout=180)
        shutil.copyfile(Path(tmp) / (Path(name).stem + ".pdf"), OUT / name)


def make_documents() -> None:
    _pdf("oss_final_notice.pdf", "오픈소스프로그래밍 기말 프로젝트 안내", [
        "강원대학교 AI융합학과 | 공지일: 2026년 11월 9일",
        "1. 목표: 수업에서 배운 내용(Git, GitHub, Linux, Docker, KNIME 등)을 활용하여 생성 AI 기반 서비스를 구현합니다.",
        "2. 발표: 2026년 12월 1일(화) ~ 12월 2일(수), 1인당 10분 (발표 형식 자유)",
        "3. 평가 기준: 아이디어 측면의 완결도, 강의 내용 활용 정도, 프레젠테이션, 기술 및 디자인 완결도",
        "4. 별도 제출물은 없으며 발표 자료와 시연으로 평가합니다.",
    ])
    _pdf("ml_week10_slides.pdf", "기계학습 10주차: 의사결정나무와 랜덤 포레스트", [
        "1. 의사결정나무는 질문을 반복해 데이터를 나누는 분류 모델입니다.",
        "2. 분할 기준: 지니 계수(Gini index)와 정보 이득(Information Gain)",
        "3. 과적합과 가지치기(Pruning): 노드당 최소 데이터 수를 늘리면 일반화 성능이 좋아질 수 있습니다.",
        "4. 랜덤 포레스트: 여러 나무의 투표로 예측하는 앙상블 방법",
        "실습: KNIME에서 Decision Tree Learner → Predictor → Scorer 노드로 정확도를 비교합니다.",
    ])
    _pdf("ml_hw2.pdf", "기계학습 과제 2: KNIME으로 타이타닉 생존 예측", [
        "공지일: 2026년 11월 16일",
        "1. titanic_training 데이터를 7:3으로 나누고(random seed = 0) 의사결정나무 모델을 학습하세요.",
        "2. Gini index와 Gain ratio 두 가지 기준의 정확도를 Scorer로 비교하세요.",
        "3. 결과 캡처와 해석을 보고서 1쪽 이내로 작성하세요.",
        "제출 기한: 2026년 11월 30일(월) 23:59, LMS 과제함",
    ])
    _pdf("order_receipt.pdf", "주문 내역서", [
        "가나다몰 | 주문번호 20261112-000123 | 결제일 2026년 11월 12일",
        "상품: USB-C 멀티 허브 (HDMI·USB 3.0) 1개 — 19,900원",
        "배송비: 0원 (무료 배송)",
        "결제 금액: 19,900원 (신용카드 일시불)",
        "배송지: 강원특별자치도 춘천시 (상세 주소 생략)",
    ])
    _pdf("bankbook_copy.pdf", "통장 사본", [
        "가나다은행 (예시) 보통예금",
        "계좌번호: 123-456-789012",
        "예금주: 홍길동",
        "※ 장학금 입금 계좌 제출용 예시 문서입니다.",
    ])
    _pdf("family_cert.pdf", "가족관계증명서", [
        "등록기준지: 강원특별자치도 춘천시 (예시)",
        "구분 | 성명 | 출생연월일 | 주민등록번호",
        "본인 | 홍길동 | 2000년 01월 01일 | 000101-3******",
        "위 가족관계등록부의 기록사항과 틀림없음을 증명합니다. (예시 문서)",
    ])
    _docx(OUT / "ds_hw3_template.docx", "자료구조 과제 3 보고서 양식", [
        "학번:            이름:",
        "1. 단일 연결 리스트(Singly Linked List)를 직접 구현하고 삽입·삭제 함수를 작성하세요.",
        "2. 각 연산의 시간 복잡도를 Big-O 표기법으로 분석하세요.",
        "3. 배열과 연결 리스트의 장단점을 비교하세요.",
        "제출 기한: 2026년 11월 24일(화) 23:59 (LMS 제출, 파일 이름: 학번_이름_과제3)",
    ])
    _docx(OUT / "algo_team_report.docx", "알고리즘 팀 프로젝트 최종 보고서", [
        "주제: 다익스트라 알고리즘을 이용한 캠퍼스 최단 경로 안내",
        "작성일: 2026년 11월 14일",
        "1. 서론: 건물 사이 이동 시간을 줄이기 위해 그래프 최단 경로 문제로 모델링했습니다.",
        "2. 방법: 건물을 정점, 길을 간선으로 두고 우선순위 큐로 다익스트라 알고리즘을 구현했습니다.",
        "3. 결과: 평균 이동 시간이 기존 안내 대비 18% 줄었습니다. 시간 복잡도는 O((V+E) log V)입니다.",
        "4. 결론 및 한계: 계단·경사 정보를 가중치에 반영하는 것이 다음 과제입니다.",
    ])
    _docx(OUT / "work_log.docx", "교내 근로장학생 근무일지 (11월)", [
        "근무 부서: 중앙도서관 자료실 | 근로 형태: 교내 근로",
    ], table=[["날짜", "근무 시간", "업무 내용"],
              ["11월 3일(화)", "13:00~16:00", "반납 도서 정리"],
              ["11월 5일(목)", "13:00~16:00", "열람실 좌석 점검"],
              ["11월 10일(화)", "13:00~16:00", "신착 도서 등록"],
              ["11월 12일(목)", "13:00~16:00", "서가 정리"]])

    prs = Presentation()
    slides = [("확률과통계 중간고사 정리", "발표: 2조 | 2026년 10월 21일"),
              ("베이즈 정리", "P(A|B) = P(B|A)·P(A) / P(B)\n사전 확률을 새 증거로 고치는 방법"),
              ("이항분포와 정규분포", "n이 크면 이항분포는 정규분포로 근사할 수 있다\n평균 np, 분산 np(1-p)")]
    for i, (title, body) in enumerate(slides):
        layout = prs.slide_layouts[0 if i == 0 else 1]
        slide = prs.slides.add_slide(layout)
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = PPt(28 if shape == slide.shapes.title else 20)
    prs.save(OUT / "prob_midterm_review.pptx")

    wb = Workbook()
    ws = wb.active
    ws.title = "회비 정산"
    ws.append(["2026-2학기 동아리 회비 정산"])
    ws.append(["이름", "납부일", "금액(원)", "비고"])
    for row in [["김민수", "2026-09-05", 20000, ""], ["이서연", "2026-09-06", 20000, ""],
                ["박지훈", "2026-09-12", 20000, "지각 납부"], ["최유나", "", 0, "미납"]]:
        ws.append(row)
    ws.append(["합계", "", "=SUM(C3:C6)", ""])
    wb.save(OUT / "club_dues.xlsx")

    memo = ("스터디카페 2층 와이파이\nSSID: STUDY_CAFE_5G\n비밀번호: study2026!\n\n"
            "도서관 그룹 스터디룸 예약: 매주 목요일 오후 4시\n")
    (OUT / "wifi_memo.txt").write_bytes(memo.encode("cp949"))  # 한국어 Windows 메모장 기본 인코딩


# ---------------------------------------------------------------------------
# 이미지
# ---------------------------------------------------------------------------
def _screenshot_scholarship() -> None:
    img = Image.new("RGB", (1080, 1500), "#F4F6F8")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1080, 120], fill="#0B4A8B")
    d.text((40, 38), "학생 포털  >  공지사항", font=kr_font(40, True), fill="white")
    d.rounded_rectangle([30, 160, 1050, 1440], radius=24, fill="white")
    y = 210
    d.text((70, y), "2026학년도 2학기", font=kr_font(36), fill="#555")
    y += 60
    d.text((70, y), "교내 생활장학금 신청 안내", font=kr_font(52, True), fill="#111")
    y += 110
    for line in ["게시일: 2026. 11. 13.", "", "■ 신청 기간", "  2026. 11. 17.(화) ~ 11. 27.(금) 18:00",
                 "", "■ 신청 대상", "  재학생 중 직전 학기 12학점 이상 이수자", "", "■ 제출 서류",
                 "  장학금 신청서 1부, 소득분위 확인서 1부", "", "■ 문의: 학생지원과 장학팀"]:
        d.text((70, y), line, font=kr_font(38), fill="#222")
        y += 64
    img.save(OUT / "scholarship_screenshot.png")


def _chalkboard_photo() -> None:
    w, h = 1600, 1200
    img = Image.new("RGB", (w, h), "#2F4F3A")
    px = img.load()
    for _ in range(60000):  # 칠판 얼룩 느낌
        x, y = random.randrange(w), random.randrange(h)
        g = random.randint(-12, 12)
        r, gg, b = px[x, y]
        px[x, y] = (max(0, r + g), max(0, gg + g), max(0, b + g))
    d = ImageDraw.Draw(img)
    chalk = "#EDEDE6"
    d.text((140, 180), "자료구조 중간고사 범위", font=kr_font(96, True), fill=chalk)
    d.text((140, 400), "3장 스택·큐  ~  7장 트리", font=kr_font(80), fill=chalk)
    d.text((140, 580), "11월 10일(화) 3교시 / 공학관", font=kr_font(72), fill=chalk)
    d.text((140, 760), "※ 손코딩 문제 2개 출제", font=kr_font(64), fill="#F3E58C")
    img = img.rotate(-3, resample=Image.BICUBIC, fillcolor="#6B5B45")
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    img.save(OUT / "ds_board_photo.jpg", quality=85)


def _receipt() -> None:
    img = Image.new("RGB", (620, 1100), "white")
    d = ImageDraw.Draw(img)
    f, fb = kr_font(30), kr_font(36, True)
    y = 40
    for text, font in [("강변 로스터리 카페", fb), ("춘천시 (예시 매장)", f), ("-" * 28, f),
                       ("아메리카노       2  x 3,500", f), ("카페라떼         1  x 4,500", f),
                       ("-" * 28, f), ("합계                 11,500원", fb), ("카드승인  2026-11-10 20:12", f),
                       ("영수증 번호  0042", f), ("", f), ("감사합니다", f)]:
        d.text((40, y), text, font=font, fill="#111")
        y += 70
    img = img.rotate(2, resample=Image.BICUBIC, expand=True, fillcolor="#C9B79C")
    img.save(OUT / "cafe_receipt.jpg", quality=88)


def _landscape() -> None:
    w, h = 1600, 1066
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):  # 노을 하늘
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(250 - 120 * t), int(170 - 60 * t), int(120 + 80 * t)))
    for i, color in enumerate(["#4C5C7A", "#3A4863", "#2B354A"]):
        pts = [(0, h)]
        for x in range(0, w + 1, 40):
            pts.append((x, int(h * (0.45 + 0.1 * i) + 60 * math.sin(x / (180 + 40 * i) + i))))
        pts.append((w, h))
        d.polygon(pts, fill=color)
    d.rectangle([0, int(h * 0.78), w, h], fill="#5D7FA6")
    exif = Image.Exif()
    exif[306] = "2026:10:18 16:20:11"  # 찍은 날짜
    img.save(OUT / "landscape.jpg", quality=88, exif=exif)


def _team_chat() -> None:
    img = Image.new("RGB", (1080, 1400), "#B2C7DA")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1080, 130], fill="#A1B6CA")
    d.text((40, 40), "알고리즘 팀플방  4", font=kr_font(44, True), fill="#111")
    msgs = [("김민수", "발표 자료 12월 3일까지 각자 파트 올려주세요!", False),
            ("이서연", "넵 저는 다익스트라 구현 부분 맡을게요", False),
            ("나", "저는 시간 복잡도 분석이랑 결론 쓸게요", True),
            ("박지훈", "보고서 최종본은 제가 합쳐서 금요일에 공유할게요", False)]
    y = 190
    for who, text, mine in msgs:
        f = kr_font(36)
        tw = d.textlength(text, font=f)
        if mine:
            x1 = 1040 - tw - 40
            d.rounded_rectangle([x1, y, 1040, y + 90], radius=24, fill="#FEE500")
            d.text((x1 + 20, y + 22), text, font=f, fill="#111")
            y += 140
        else:
            d.text((40, y), who, font=kr_font(30), fill="#333")
            d.rounded_rectangle([40, y + 45, 40 + tw + 40, y + 135], radius=24, fill="white")
            d.text((60, y + 67), text, font=f, fill="#111")
            y += 190
    img.save(OUT / "team_chat.png")


def _algo_slide() -> None:
    img = Image.new("RGB", (1600, 900), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1600, 150], fill="#7A1F2B")
    d.text((60, 40), "알고리즘 7주차 — 동적 계획법 (Dynamic Programming)", font=kr_font(56, True), fill="white")
    y = 240
    for line in ["• 큰 문제를 작은 부분 문제로 나누고, 그 답을 저장해 다시 쓴다 (메모이제이션)",
                 "• 조건: 최적 부분 구조 + 중복되는 부분 문제",
                 "• 예: 피보나치 수열, 0/1 배낭 문제, 최장 공통 부분 수열(LCS)",
                 "• 시간 복잡도: 부분 문제 수 × 부분 문제 하나를 푸는 시간"]:
        d.text((80, y), line, font=kr_font(42), fill="#222")
        y += 120
    img.save(OUT / "algo_slide.png")


def _id_card_placeholder() -> None:
    img = Image.new("RGB", (1000, 630), "#E8EEF3")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([20, 20, 980, 610], radius=40, outline="#8A9BAA", width=6)
    d.text((80, 80), "신분증 (예시 이미지)", font=kr_font(64, True), fill="#334")
    d.rectangle([700, 180, 900, 440], fill="#C8D2DC")
    d.text((80, 260), "이름: 홍길동 (가상)", font=kr_font(48), fill="#334")
    img.save(OUT / "id_card.jpg", quality=85)


# ---------------------------------------------------------------------------
# 기타
# ---------------------------------------------------------------------------
def make_misc(hwp_sample: Path | None) -> None:
    (OUT / "chrome_setup.exe").write_bytes(b"MZ" + bytes(random.getrandbits(8) for _ in range(60_000)))
    (OUT / "python_installer.exe").write_bytes(b"MZ" + bytes(random.getrandbits(8) for _ in range(80_000)))
    (OUT / "voice_memo.m4a").write_bytes(b"\x00\x00\x00\x20ftypM4A " + bytes(30_000))
    with zipfile.ZipFile(OUT / "lab_materials.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("오픈소스프로그래밍_실습/1주차_리눅스_기초.txt", "리눅스 기본 명령어 실습: ls, cd, pwd, mkdir\n")
        z.writestr("오픈소스프로그래밍_실습/2주차_Git_설치.txt", "git init, git add, git commit 실습\n")
        z.writestr("오픈소스프로그래밍_실습/3주차_Docker.txt", "docker run hello-world\n")
    if hwp_sample and hwp_sample.exists():
        shutil.copyfile(hwp_sample, OUT / "hwp_sample.hwp")


MANIFEST = [
    ("oss_final_notice.pdf", "다운로드 (7).pdf", 11, 0),
    ("ml_week10_slides.pdf", "강의자료_week10.pdf", 9, 0),
    ("ml_hw2.pdf", "다운로드.pdf", 4, 0),
    ("ml_hw2.pdf", "다운로드 (1).pdf", 4, -30),
    ("ds_hw3_template.docx", "과제양식(3).docx", 12, 0),
    ("ds_hw3_template.docx", "과제양식(3)(1).docx", 12, -45),
    ("algo_team_report.docx", "final_진짜최종(2).docx", 6, 0),
    ("prob_midterm_review.pptx", "제출용.pptx", 30, 0),
    ("work_log.docx", "제목 없음.docx", 7, 0),
    ("club_dues.xlsx", "무제 스프레드시트.xlsx", 14, 0),
    ("wifi_memo.txt", "새 텍스트 문서.txt", 25, 0),
    ("order_receipt.pdf", "주문내역.pdf", 8, 0),
    ("bankbook_copy.pdf", "통장사본.pdf", 40, 0),
    ("family_cert.pdf", "scan0001.pdf", 45, 0),
    ("scholarship_screenshot.png", "Screenshot_20261115-224512.png", 5, 0),
    ("ds_board_photo.jpg", "KakaoTalk_20261103_153201234.jpg", 17, 0),
    ("cafe_receipt.jpg", "KakaoTalk_20261110_201544871.jpg", 10, 0),
    ("team_chat.png", "KakaoTalk_20261118_090011223.png", 2, 0),
    ("algo_slide.png", "image (3).png", 13, 0),
    ("landscape.jpg", "IMG_4821.JPG", 33, 0),
    ("id_card.jpg", "신분증.jpg", 50, 0),
    ("hwp_sample.hwp", "새 한글 문서(2).hwp", 3, 0),
    ("lab_materials.zip", "자료.zip", 20, 0),
    ("chrome_setup.exe", "ChromeSetup.exe", 60, 0),
    ("python_installer.exe", "python-3.13.0-amd64.exe", 2, 0),
    ("voice_memo.m4a", "녹음_20261119_143010.m4a", 1, 0),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    hwp = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    make_documents()
    _screenshot_scholarship()
    _chalkboard_photo()
    _receipt()
    _landscape()
    _team_chat()
    _algo_slide()
    _id_card_placeholder()
    make_misc(hwp)
    files = [{"sample": s, "name": n, "days_ago": d, "minutes": m}
             for s, n, d, m in MANIFEST if (OUT / s).exists()]
    (OUT / "manifest.json").write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(f"샘플 {len(files)}개 → {OUT}")


if __name__ == "__main__":
    main()
