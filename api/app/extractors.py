"""파일에서 글자·이미지를 뽑아내는 부분.

| 형식                         | 방법                                                     |
|------------------------------|----------------------------------------------------------|
| PDF                          | pypdf로 앞쪽 3쪽 글자 추출 (글자가 없으면 스캔본 → 원본을 AI에 전달) |
| Word / PowerPoint / Excel    | python-docx / python-pptx / openpyxl                     |
| 한글 HWPX                    | ZIP 안의 Contents/section*.xml 에서 <hp:t> 글자 수집       |
| 한글 HWP (5.0)               | OLE 파일의 BodyText 구역을 풀어(zlib) PARA_TEXT 레코드만 읽음 |
| 이미지                       | 축소 JPEG(AI 전달용) + 촬영일(EXIF) + tesseract OCR(내 컴퓨터) |
| ZIP                          | 압축을 풀지 않고 안에 든 파일 이름만 읽음                  |

어떤 파일에서 오류가 나도 정리 전체가 멈추지 않도록 오류는 error 필드에만 담는다.
"""
from __future__ import annotations

import io
import re
import struct
import subprocess
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

DOC_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".hwp", ".hwpx",
           ".doc", ".ppt", ".xls", ".rtf", ".json", ".log"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tif", ".tiff"}
ARCHIVE_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".alz", ".egg"}
INSTALLER_EXT = {".exe", ".msi", ".dmg", ".pkg", ".apk"}
MEDIA_EXT = {".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a", ".aac"}

MAX_DOCUMENT_BYTES = 14 * 1024 * 1024  # 스캔 PDF를 AI에 직접 보낼 때의 상한
MAX_PARSE_BYTES = 80 * 1024 * 1024     # 이보다 큰 파일은 글자를 뽑지 않음 (속도·메모리 보호)


def kind_of(ext: str) -> str:
    ext = ext.lower()
    if ext in DOC_EXT:
        return "document"
    if ext in IMAGE_EXT:
        return "image"
    if ext in ARCHIVE_EXT:
        return "archive"
    if ext in INSTALLER_EXT:
        return "installer"
    if ext in MEDIA_EXT:
        return "media"
    return "other"


@dataclass
class Extracted:
    kind: str
    text: str = ""                # 문서에서 뽑은 글자
    ocr_text: str = ""            # 이미지에서 내 컴퓨터로 읽은 글자 (민감 정보 확인·규칙 분류용)
    image: bytes | None = None    # AI에 보낼 축소 JPEG
    image_mime: str = "image/jpeg"
    document: bytes | None = None  # 글자가 없는 PDF(스캔본) 원본
    exif_date: str = ""           # YYYY-MM-DD
    error: str | None = None


# ---------------------------------------------------------------------------
# 문서
# ---------------------------------------------------------------------------
def _clean(text: str, limit: int) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit]


def _pdf(path: Path, limit: int) -> tuple[str, bytes | None]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise ValueError("암호가 걸린 PDF") from exc
    parts = []
    for page in reader.pages[:3]:
        parts.append(page.extract_text() or "")
        if sum(len(p) for p in parts) > limit:
            break
    text = "\n".join(parts)
    scanned = None
    if len(text.strip()) < 20 and path.stat().st_size <= MAX_DOCUMENT_BYTES:
        scanned = path.read_bytes()  # 글자가 없는 스캔본 → 원본을 AI가 직접 보게 함
    return text, scanned


def _docx(path: Path) -> str:
    import docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables[:5]:
        for row in table.rows[:20]:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def _pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    parts = []
    for i, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text)
        if i >= 15:
            break
    return "\n".join(parts)


def _xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True, data_only=True)
    parts = []
    try:
        for ws in wb.worksheets[:3]:
            parts.append(f"[시트] {ws.title}")
            for row in ws.iter_rows(max_row=40, values_only=True):
                cells = [str(v) for v in row if v is not None]
                if cells:
                    parts.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(parts)


def _plain(path: Path, limit: int) -> str:
    raw = path.read_bytes()[: limit * 4]
    for enc in ("utf-8-sig", "cp949", "euc-kr"):  # 한국어 Windows 메모장 파일은 cp949인 경우가 많음
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="ignore")


def _hwpx(path: Path) -> str:
    """HWPX = ZIP + XML. 본문은 Contents/section0.xml, section1.xml ... 의 <hp:t> 요소에 있다."""
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)]
        names.sort(key=lambda n: int(re.findall(r"\d+", n)[-1]))
        parts: list[str] = []
        for name in names:
            if z.getinfo(name).file_size > 30 * 1024 * 1024:
                continue
            buf: list[str] = []
            for event, el in ET.iterparse(io.BytesIO(z.read(name)), events=("start", "end")):
                tag = el.tag.rsplit("}", 1)[-1]
                if event == "start" and tag == "p" and buf and buf[-1] != "\n":
                    buf.append("\n")  # 새 문단
                elif event == "end" and tag == "t" and el.text:
                    buf.append(el.text)
            parts.append("".join(buf))
        if not "".join(parts).strip() and "Preview/PrvText.txt" in z.namelist():
            parts.append(z.read("Preview/PrvText.txt").decode("utf-8", errors="ignore"))
    return "\n".join(parts)


# HWP 5.0 문단 글자(PARA_TEXT) 안의 제어 문자 중 8글자(16바이트)를 차지하는 것들
_HWP_WIDE_CONTROLS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
_HWPTAG_PARA_TEXT = 0x10 + 51  # = 67


def _hwp_para_text(data: bytes) -> str:
    out = []
    i, n = 0, len(data) // 2
    while i < n:
        code = struct.unpack_from("<H", data, i * 2)[0]
        if code in _HWP_WIDE_CONTROLS:
            i += 8
            continue
        if code in (10, 13):
            out.append("\n")
        elif code >= 32:
            out.append(chr(code))
        i += 1
    return "".join(out)


def _hwp(path: Path, limit: int) -> str:
    """한글 HWP 5.0 (OLE 복합 문서) 본문 읽기.

    FileHeader 36바이트째 속성: bit0 압축, bit1 암호, bit2 배포용 문서.
    배포용·암호 문서는 본문이 암호화되어 있어 '미리보기 글자(PrvText)'만 사용한다.
    """
    import olefile

    with olefile.OleFileIO(str(path)) as ole:
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File"):
            raise ValueError("HWP 5.0 형식이 아님 (아주 오래된 HWP일 수 있음)")
        flags = struct.unpack_from("<I", header, 36)[0]
        compressed, password, distribution = bool(flags & 1), bool(flags & 2), bool(flags & 4)
        texts: list[str] = []
        if not password and not distribution:
            sections = [e for e in ole.listdir() if len(e) == 2 and e[0] == "BodyText"]
            sections.sort(key=lambda e: int(re.sub(r"\D", "", e[1]) or 0))
            for entry in sections:
                data = ole.openstream(entry).read()
                if compressed:
                    data = zlib.decompress(data, -15)
                pos = 0
                while pos + 4 <= len(data):
                    rec = struct.unpack_from("<I", data, pos)[0]
                    pos += 4
                    tag, size = rec & 0x3FF, (rec >> 20) & 0xFFF
                    if size == 0xFFF:  # 큰 레코드는 다음 4바이트에 실제 길이
                        size = struct.unpack_from("<I", data, pos)[0]
                        pos += 4
                    if tag == _HWPTAG_PARA_TEXT:
                        texts.append(_hwp_para_text(data[pos:pos + size]))
                    pos += size
                if sum(len(t) for t in texts) > limit:
                    break
        body = "".join(texts)
        if body.strip():
            return body
        if ole.exists("PrvText"):
            preview = ole.openstream("PrvText").read().decode("utf-16-le", errors="ignore")
            return re.sub(r"<[^>]*>", " ", preview)  # 표 칸 표시(<...>) 제거
    return ""


# ---------------------------------------------------------------------------
# 이미지
# ---------------------------------------------------------------------------
def _exif_date(img) -> str:
    try:
        exif = img.getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
        if raw:
            m = re.match(r"(\d{4}):(\d{2}):(\d{2})", str(raw))
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _ocr(img, timeout: int = 25) -> str:
    """tesseract로 이미지 속 글자를 읽는다 (내 컴퓨터 안에서만 처리).

    --psm 11(흩어진 글자 찾기)이 캡처·사진·영수증에서 가장 잘 읽혔다. 어두운 배경(칠판 등)은 반전한다.
    """
    from PIL import ImageOps

    gray = img.convert("L")
    gray.thumbnail((1800, 1800))
    hist = gray.histogram()
    if sum(hist[:100]) > sum(hist[156:]):
        gray = ImageOps.invert(gray)
    gray = ImageOps.autocontrast(gray)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        gray.save(tmp, format="PNG")
        tmp_path = tmp.name
    try:
        result = subprocess.run(["tesseract", tmp_path, "stdout", "-l", "kor+eng", "--psm", "11"],
                                capture_output=True, timeout=timeout, check=False)
        return result.stdout.decode("utf-8", errors="ignore")
    except (OSError, subprocess.TimeoutExpired):
        return ""
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _image(path: Path, want_image: bool, ocr: bool, out: Extracted) -> None:
    from PIL import Image, ImageOps

    with Image.open(path) as img:
        out.exif_date = _exif_date(img)
        img = ImageOps.exif_transpose(img)
        if ocr:
            out.ocr_text = _clean(_ocr(img), 3000)
        if want_image:
            rgb = img.convert("RGB")
            rgb.thumbnail((1024, 1024))
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=80)
            out.image = buf.getvalue()


# ---------------------------------------------------------------------------
# 공개 함수
# ---------------------------------------------------------------------------
def extract(path: Path, max_chars: int = 4000, want_image: bool = True, ocr: bool = False) -> Extracted:
    ext = path.suffix.lower()
    out = Extracted(kind=kind_of(ext))
    try:
        if path.stat().st_size > MAX_PARSE_BYTES and out.kind in ("document", "image"):
            out.error = "파일이 커서 내용을 읽지 않음"
            return out
        if ext == ".pdf":
            text, scanned = _pdf(path, max_chars)
            out.text, out.document = text, scanned
        elif ext == ".docx":
            out.text = _docx(path)
        elif ext == ".pptx":
            out.text = _pptx(path)
        elif ext == ".xlsx":
            out.text = _xlsx(path)
        elif ext in (".txt", ".md", ".csv", ".json", ".log"):
            out.text = _plain(path, max_chars)
        elif ext == ".hwpx":
            out.text = _hwpx(path)
        elif ext == ".hwp":
            out.text = _hwp(path, max_chars)
        elif out.kind == "image":
            _image(path, want_image, ocr, out)
        elif ext == ".zip":
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if not n.endswith("/")][:30]
            out.text = "압축 파일 안의 파일: " + ", ".join(names)
        out.text = _clean(out.text, max_chars)
    except Exception as exc:  # noqa: BLE001 — 손상된 파일이 있어도 전체 정리는 계속
        out.error = f"내용을 읽지 못함: {type(exc).__name__}"
    return out
