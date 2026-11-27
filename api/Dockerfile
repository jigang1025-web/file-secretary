# =============================================================================
# 파일 정리 비서 API 이미지 (멀티스테이지 빌드)
# 1단계(build)에서 패키지를 설치하고, 2단계(실행 이미지)에는 결과물만 복사해 가볍게 만든다.
# =============================================================================

# ---------- 1단계: 빌드 ----------
FROM python:3.13-slim AS build
WORKDIR /src
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------- 2단계: 실행 ----------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul
# tesseract: 이미지 속 글자를 '내 컴퓨터 안에서' 읽어 민감 정보가 보이면 AI로 보내지 않기 위해 사용 (오픈소스 OCR)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-kor tzdata \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /install /usr/local
COPY app ./app

# 최소 권한 원칙: root가 아닌 일반 사용자로 실행 (compose의 user: 로 내 계정 번호에 맞출 수 있음)
RUN useradd --create-home --uid 1000 secretary && chown -R secretary /app
USER secretary

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
