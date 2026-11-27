# =============================================================================
# 파일 정리 비서 대시보드 이미지 (Streamlit, 멀티스테이지 빌드)
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
WORKDIR /app
COPY --from=build /install /usr/local
COPY app.py .
COPY .streamlit ./.streamlit

RUN useradd --create-home --uid 10001 secretary && chown -R secretary /app
USER secretary

EXPOSE 8501
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)"
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
