FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# WeasyPrint (the 'pdf' extra) renders through GLib/Pango/Cairo, which are system
# libraries rather than wheels. Without them render_pdf raised 501 and TZ 35.9
# ("pdf_url с работающей ссылкой") had no way to be met.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
    libglib2.0-0 libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
    libcairo2 libgdk-pixbuf-2.0-0 shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy source, then editable install so `app`/`worker` import from /app and
# run_migrations() can locate /app/migrations at runtime.
COPY . .
# [pdf] = WeasyPrint, [storage] = boto3 for Yandex Object Storage. Without
# them the app silently degraded: PDFs 501'd and uploads fell back to disk.
RUN pip install --upgrade pip && pip install -e '.[pdf,storage]'

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
