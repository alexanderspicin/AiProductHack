# syntax=docker/dockerfile:1.7
#
# Build context is the repo root (pyproject.toml lives there, and setuptools is
# configured with packages.find where=["backend"]):
#
#   docker build -f backend/Dockerfile --target cpu -t rula-backend .
#
# Two targets:
#   cpu   -- default, builds for linux/amd64 and linux/arm64 (Apple Silicon).
#   cuda  -- opt-in, amd64 only: faster-whisper on GPU needs CUDA + cuDNN.
#
# Everything the pipeline needs at runtime (faster-whisper/ctranslate2, Silero
# VAD and Smart Turn v3 via onnxruntime, PyAV) ships prebuilt manylinux wheels
# for aarch64 as well as x86_64, so the cpu target is genuinely multi-arch --
# no torch, no compiler in the image.

##############################################################################
# GPU target (linux/amd64 only)
##############################################################################
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04 AS cuda

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/models

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
RUN --mount=type=cache,target=/root/.cache/pip pip install -e .

RUN useradd --create-home --uid 10001 app && mkdir -p /models && chown -R app:app /models /app
USER app
WORKDIR /app/backend

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 7860), 3).close()"

# --host 0.0.0.0 is required to be reachable outside the container. Note the
# runner also builds the client's wsUrl from this value, which is why the
# frontend rebuilds that URL itself -- see resolveWsUrl() in main.ts.
CMD ["python", "app/bot.py", "--host", "0.0.0.0", "--port", "7860", "-t", "websocket"]

##############################################################################
# CPU target (default; linux/amd64 + linux/arm64)
##############################################################################
FROM python:3.13-slim AS cpu

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models

# libgomp1: OpenMP runtime that ctranslate2 and onnxruntime link against.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY backend ./backend
RUN --mount=type=cache,target=/root/.cache/pip pip install -e .

RUN useradd --create-home --uid 10001 app && mkdir -p /models && chown -R app:app /models /app
USER app
WORKDIR /app/backend

# Model weights (Whisper, Smart Turn v3) download on first use into HF_HOME;
# compose mounts a named volume there so a restart doesn't refetch them.
VOLUME ["/models"]

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import socket; socket.create_connection(('127.0.0.1', 7860), 3).close()"

CMD ["python", "app/bot.py", "--host", "0.0.0.0", "--port", "7860", "-t", "websocket"]
