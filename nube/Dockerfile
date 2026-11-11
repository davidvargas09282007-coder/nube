# syntax=docker/dockerfile:1
# ============================================================================
# Imagen de produccion del servidor Jarvis.
#
#   docker build -t jarvis-server .
#   docker build --build-arg INSTALL_VOICE=true -t jarvis-server:voice .
#
# Sin INSTALL_VOICE la imagen pesa ~200 MB y funciona en modo texto.
# ============================================================================
FROM python:3.12-slim AS runtime

ARG INSTALL_VOICE=false
ARG JARVIS_UID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/data/hf \
    XDG_CACHE_HOME=/data/cache \
    JARVIS_HOST=0.0.0.0 \
    JARVIS_PORT=8080

WORKDIR /app

# Dependencias primero: esta capa solo se reconstruye si cambian los requirements.
COPY requirements.txt requirements-voice.txt ./
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt \
    && if [ "$INSTALL_VOICE" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends libgomp1 libsndfile1 \
        && rm -rf /var/lib/apt/lists/* \
        && python -m pip install -r requirements-voice.txt; \
    fi

# Codigo de la aplicacion.
COPY pyproject.toml ./
COPY jarvis_server ./jarvis_server
COPY scripts ./scripts
RUN python -m pip install --no-deps --no-build-isolation .

# Usuario sin privilegios y volumen persistente.
RUN groupadd --gid "$JARVIS_UID" jarvis \
    && useradd --uid "$JARVIS_UID" --gid jarvis --create-home --shell /usr/sbin/nologin jarvis \
    && mkdir -p /data \
    && chown -R jarvis:jarvis /data /app \
    && chmod +x scripts/*.sh

USER jarvis

EXPOSE 8080

# Healthcheck sin curl: usa solo la stdlib.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "scripts/healthcheck.py"]

# exec en start.sh: uvicorn queda como PID 1 y recibe SIGTERM correctamente.
CMD ["bash", "scripts/start.sh"]
