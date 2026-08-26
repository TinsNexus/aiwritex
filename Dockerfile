# syntax=docker/dockerfile:1
# AIWriteX — Web mode container (FastAPI UI on :8000)
# GUI mode (pywebview) is NOT supported inside Docker.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CREWAI_DISABLE_TELEMETRY=1 \
    OTEL_SDK_DISABLED=true

WORKDIR /app

# Toolchain for any source builds (Cython 3.0.0 has no cp312 wheels)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # aiforge requires playhouse.sqlite_ext.SqliteExtDatabase, removed in peewee 4.x
    && pip install --no-cache-dir "peewee>=3.14,<4"

# Application source
COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "src.ai_write_x.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
