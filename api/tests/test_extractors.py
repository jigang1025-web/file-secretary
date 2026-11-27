import io
import shutil
import zipfile

import pytest
from PIL import Image

from app.extractors import extract, kind_of
from conftest import FIXTURES, SAMPLES


def test_kind_of():
    assert kind_of(".PDF") == "document"
    assert kind_of(".jpg") == "image"
    assert kind_of(".exe") == "installer"
    assert kind_of(".zip") == "archive"
    assert kind_of(".m4a") == "media"
    assert kind_of(".xyz") == "other"


def test_pdf_docx_pptx_xlsx_samples():
    assert "기말 프로젝트" in extract(SAMPLES / "oss_final_notice.pdf").text
    assert "연결 리스트" in extract(SAMPLES / "ds_hw3_template.docx").text
    assert "베이즈 정리" in extract(SAMPLES / "prob_midterm_review.pptx").text
    assert "회비" in extract(SAMPLES / "club_dues.xlsx").text


def test_cp949_text(tmp_path):
    p = tmp_path / "memo.txt"
    p.write_bytes("와이파이 비밀번호 메모".encode("cp949"))
    assert extract(p).text == "와이파이 비밀번호 메모"


def test_hwp5_body_text():
    ex = extract(FIXTURES / "simple.hwp")
    assert ex.error is None
    assert "안녕하세요" in ex.text and "샘플" in ex.text


def test_hwp5_distribution_uses_preview_text():
    ex = extract(FIXTURES / "distribution.hwp")
    assert ex.error is None
    assert "공고" in ex.text


def test_hwpx(tmp_path):
    p = tmp_path / "report.hwpx"
    ns = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
    section = (f'<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" {ns}>'
               '<hp:p><hp:run><hp:t>자료구조 과제 보고서</hp:t></hp:run></hp:p>'
               '<hp:p><hp:run><hp:t>연결 리스트 </hp:t></hp:run><hp:run><hp:t>구현</hp:t></hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", section)
    assert extract(p).text == "자료구조 과제 보고서\n연결 리스트 구현"


def test_zip_lists_names(tmp_path):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("실습/1주차_리눅스.txt", "x")
    assert "1주차_리눅스" in extract(p).text


def test_image_resize_and_exif():
    ex = extract(SAMPLES / "landscape.jpg", want_image=True)
    assert ex.exif_date == "2026-10-18"
    img = Image.open(io.BytesIO(ex.image))
    assert max(img.size) <= 1024 and img.format == "JPEG"


def test_image_without_ai_has_no_bytes():
    assert extract(SAMPLES / "landscape.jpg", want_image=False).image is None


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract 없음")
def test_ocr_reads_korean_screenshot():
    ex = extract(SAMPLES / "scholarship_screenshot.png", want_image=False, ocr=True)
    assert "장학금" in ex.ocr_text


def test_broken_file_does_not_raise(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"not a pdf at all")
    ex = extract(p)
    assert ex.error and ex.text == ""
