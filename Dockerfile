# The scoring API and the game, in one small image.
#
#   docker build -t momo-fraud .
#   docker run -p 8000:8000 momo-fraud        # http://localhost:8000/game, /docs, /v1/monitoring
#
# Only what serving needs goes in: the code, the exported model and its drift reference.
# No training data, no simulator output, no notebooks or tests.

ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    MOMO_DEMO_USERS=3000 \
    MOMO_DEMO_DAYS=30 \
    MOMO_DEMO_SEED=7

# LightGBM's wheel needs the OpenMP runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so code changes don't reinstall them
COPY requirements-serve.txt .
RUN pip install -r requirements-serve.txt

COPY src/ src/
COPY models/ models/
# Game attempts are logged here: mount a volume to keep them
RUN mkdir -p data/game && chown 10001 data/game

# Never run as root
USER 10001
EXPOSE 8000

# Building the demo network takes about 10 seconds at start-up
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# One worker on purpose: the network state lives in this process (see the README)
CMD ["uvicorn", "momofraud.serving.api:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "30"]
