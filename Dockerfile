FROM python:3.13.1-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/models/fastembed \
    HF_HOME=/models/huggingface

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 rag \
    && useradd --uid 10001 --gid 10001 --create-home rag \
    && mkdir -p /models /app/data \
    && chown -R rag:rag /models /app

COPY requirements-docker.txt ./
RUN python -m pip install -r requirements-docker.txt
COPY --chown=rag:rag app.py frontend.py rag_engine.py query_pipeline.py migrate_qdrant.py ./
COPY --chown=rag:rag docker/healthcheck.py ./docker/healthcheck.py
USER rag
EXPOSE 8000 8501
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
