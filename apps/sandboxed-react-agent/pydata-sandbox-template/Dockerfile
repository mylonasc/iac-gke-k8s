ARG BASE_IMAGE=us-central1-docker.pkg.dev/k8s-staging-images/agent-sandbox/python-runtime-sandbox:latest-main
FROM ${BASE_IMAGE}

USER root

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
      apt-get update; \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends sqlite3 curl; \
      rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
      apk add --no-cache sqlite curl; \
    fi; \
    PYTHON_BIN="python3"; \
    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then PYTHON_BIN="python"; fi; \
    "${PYTHON_BIN}" -m pip install --no-cache-dir --upgrade pip setuptools wheel; \
    "${PYTHON_BIN}" -m pip install --no-cache-dir \
      numpy \
      scipy \
      pandas \
      matplotlib \
      seaborn \
      polars \
      yfinance; \
    find /root/.cache -mindepth 1 -delete 2>/dev/null || true
