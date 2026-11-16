# Dockerfile — Ignite Desk backend (Python)
# Build:  docker build -t ignite-desk-backend .
# Run:    docker run --env-file .env -p 8000:8000 ignite-desk-backend
FROM python:3.11-slim

WORKDIR /app

# System deps for torch/pandas (no CUDA in base image; add nvidia/cuda if you have a GPU)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy application code (excludes .venv, __pycache__, .env via .dockerignore)
COPY backend/ ./backend/
COPY docs/ ./docs/
COPY spikes/ ./spikes/
COPY vendor/ ./vendor/

# Environment with safe defaults; override via --env-file .env at runtime
ENV IGNITE_BIND_HOST=0.0.0.0
ENV IGNITE_BIND_PORT=8000
ENV IGNITE_DB_PATH=/data/ignite.db
ENV IGNITE_TZ=local
ENV IGNITE_DRAFT_TTL_S=90
ENV IGNITE_MAX_DRIFT_ATR=0.30
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Default command: backend API. Override command to run the Kronos worker instead:
#   docker run --entrypoint "python" ignite-desk-backend -m backend.ignite.forecasting.worker
CMD ["python", "-m", "backend.ignite.api"]
