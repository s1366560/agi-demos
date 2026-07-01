FROM python:3.12-slim

WORKDIR /app

ENV HF_HOME=/cache/huggingface \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RERANK_HOST=0.0.0.0 \
    RERANK_PORT=8081 \
    TOKENIZERS_PARALLELISM=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY app.py .

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -fsS "http://localhost:${RERANK_PORT}/health" >/dev/null || exit 1

CMD ["python", "/app/app.py"]
