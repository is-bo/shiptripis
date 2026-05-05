FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# psycopg[binary] ships its own libpq, so no build deps needed.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collect static files at build time (whitenoise serves them)
RUN DJANGO_SETTINGS_MODULE=config.settings.base \
    DJANGO_SECRET_KEY=build-placeholder \
    POSTGRES_DB=x POSTGRES_USER=x POSTGRES_PASSWORD=x \
    JWT_HS256_SECRET=x S3_ENDPOINT_URL=x S3_ACCESS_KEY=x S3_SECRET_KEY=x \
    python manage.py collectstatic --noinput 2>/dev/null || true

EXPOSE ${PORT}

# Production: gunicorn with proper worker count
CMD gunicorn config.wsgi:application \
    --bind 0.0.0.0:${PORT} \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
