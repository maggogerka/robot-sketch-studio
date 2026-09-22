FROM python:3.11-slim AS runtime

ARG INSTALL_EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SKETCHARM_HOST=0.0.0.0 \
    SKETCHARM_PORT=8000 \
    SKETCHARM_MODEL_DIR=/models \
    SKETCHARM_DATA_DIR=/data \
    SKETCHARM_RESULTS_DIR=/results

WORKDIR /app
RUN useradd --create-home --uid 10001 sketcharm \
    && mkdir -p /models /data /results \
    && chown -R sketcharm:sketcharm /models /data /results /app

COPY --chown=sketcharm:sketcharm . /app
RUN if [ -n "$INSTALL_EXTRAS" ]; then pip install --no-cache-dir ".[${INSTALL_EXTRAS}]"; else pip install --no-cache-dir .; fi

USER sketcharm
EXPOSE 8000
VOLUME ["/models", "/data", "/results"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "-m", "robot_sketch_studio", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]

