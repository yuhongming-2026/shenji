FROM python:3.11-slim-bookworm

LABEL maintainer="audit-system"
LABEL description="财务大数据审计系统"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    FLASK_DEBUG=0

WORKDIR /app

# 系统依赖：OCR、语音识别音频转换
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads data && \
    adduser --disabled-password --gecos "" appuser && \
    chown -R appuser:appuser /app

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN sed -i 's/\r$//' /docker-entrypoint.sh && chmod +x /docker-entrypoint.sh

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT}/ || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
# 单 worker：应用使用内存存储表数据，多 worker 会导致会话不一致
CMD ["gunicorn", "--preload", "--bind", "0.0.0.0:5000", "--workers", "1", "--worker-class", "gthread", "--threads", "16", "--keep-alive", "5", "--timeout", "120", "app:app"]
