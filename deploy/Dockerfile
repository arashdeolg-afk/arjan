# Deol Tech — paper trading platform
#
# Deliberately minimal: the application is pure Python 3.11 standard library,
# so there is nothing to install, no build stage, and no dependency surface to
# patch. The image is the interpreter plus the source.

FROM python:3.11-slim

# Never write .pyc files or buffer stdout — buffered logs are useless in a
# container, because you only see them after a crash.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DEOLTECH_DB=/data/deoltech.db \
    DEOLTECH_HOST=0.0.0.0 \
    DEOLTECH_PORT=8000

# Run as an unprivileged user. A web process that can write to its own source
# tree is one file-write bug away from remote code execution.
RUN useradd --create-home --uid 10001 deoltech \
 && mkdir -p /data \
 && chown deoltech:deoltech /data

WORKDIR /app
COPY --chown=deoltech:deoltech src/ /app/src/
COPY --chown=deoltech:deoltech tests/ /app/tests/

USER deoltech

# The database lives on a volume. Without this, every redeploy silently wipes
# every user, account and trade.
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', \
timeout=4).status == 200 else 1)"

# --trust-proxy is safe here because the container is expected to sit behind
# the reverse proxy in deploy/nginx.conf, which overwrites X-Forwarded-For.
CMD ["python", "-m", "deoltech", "serve", "--trust-proxy", "--secure-cookies"]
