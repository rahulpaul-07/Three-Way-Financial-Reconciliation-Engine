# Two stages: build the dashboard with Node, then run the engine and serve the
# built dashboard with Python. The runtime image carries no Node toolchain.

FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    RECON_WEB_DIST=/app/web/dist
WORKDIR /app
COPY requirements-web.txt requirements.txt ./
# The model-backed layers are optional; the anthropic SDK is installed so a
# key set on the service enables them, and nothing else depends on it.
RUN pip install -r requirements-web.txt "anthropic>=0.40.0"
COPY src/ src/
COPY datasets/ datasets/
COPY --from=web /web/dist web/dist
RUN useradd --create-home --uid 10001 recon && chown -R recon /app
USER recon
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health',timeout=4)"
CMD ["sh", "-c", "python -m uvicorn app:app --app-dir src --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
