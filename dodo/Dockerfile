# Dodo — Production-ready Django container
FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=dodo.settings

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      libpq-dev \
      curl \
      gettext \
      postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create non-root app user
RUN groupadd --system dodo && useradd --system --gid dodo --home /app dodo

WORKDIR /app

# Install Python dependencies (leveraging Docker layer cache)
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the project
COPY --chown=dodo:dodo . /app/

# Create required runtime directories
RUN mkdir -p /app/media /app/staticfiles /app/logs \
    && chown -R dodo:dodo /app/media /app/staticfiles /app/logs

# Collect static files (run as root so permissions are clean, then drop)
RUN python manage.py collectstatic --noinput || true

# Copy the entrypoint script
COPY --chown=dodo:dodo docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

USER dodo

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/accounts/login/ || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "dodo.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
