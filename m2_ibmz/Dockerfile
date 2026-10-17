# syntax=docker/dockerfile:1
# CriticalFlow AI - M2 (IBM Z) extractor: z/OSMF -> normalize -> POST /api/v1/incidents
FROM python:3.12-slim

LABEL org.opencontainers.image.title="criticalflow-m2-ibmz" \
      org.opencontainers.image.description="IBM Z (z/OSMF) job extractor and normalizer for CriticalFlow AI" \
      contract.version="1.0.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install -r requirements.txt

# application code (see .dockerignore: no secrets, events, venv or state)
COPY . .

# run as an unprivileged user; /data holds the checkpoint, quarantine and heartbeat
RUN useradd --system --uid 10001 --home-dir /app cfuser \
 && mkdir -p /data && chown cfuser:cfuser /data
USER cfuser

ENV MOCK_MODE=False \
    CF_STATE_FILE=/data/state.json \
    CF_QUARANTINE_DIR=/data/quarantine \
    CF_HEARTBEAT_FILE=/data/heartbeat
VOLUME ["/data"]

# healthy = a fully successful cycle in the last CF_HEALTH_MAX_AGE seconds (default 300)
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
  CMD ["python", "docker/healthcheck.py"]

# credentials are NEVER baked into the image: pass them with --env-file / environment
ENTRYPOINT ["python", "run_pipeline.py"]
CMD ["--interval", "10"]