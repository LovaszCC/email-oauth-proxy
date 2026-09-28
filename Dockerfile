FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 --no-create-home proxy \
    && mkdir -p /data && chown proxy:proxy /data

USER proxy
VOLUME ["/data"]
EXPOSE 8080 1993

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)"

CMD ["email-oauth2-proxy-web"]
