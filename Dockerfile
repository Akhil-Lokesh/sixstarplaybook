# One image for all five services; SERVICE picks which one runs.
#   docker build -t sixstar .
#   docker run -e SERVICE=gateway -p 8000:8000 sixstar
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SERVICE=gateway \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY sixstar ./sixstar
COPY guide ./guide
COPY data ./data

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=3)" || exit 1

# --proxy-headers is off on purpose: the gateway reads CF-Connecting-IP / X-Forwarded-For
# itself, and only when TRUST_PROXY_HEADERS=true.
CMD ["sh", "-c", "exec uvicorn sixstar.${SERVICE}.app:app --host 0.0.0.0 --port ${PORT} --no-proxy-headers --timeout-keep-alive 75"]
