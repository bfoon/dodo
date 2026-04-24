#!/bin/sh
set -e

if [ "${DB_ENGINE:-postgres}" = "postgres" ] && [ -n "${DB_HOST}" ]; then
  echo "[entrypoint] Waiting for PostgreSQL at ${DB_HOST}:${DB_PORT:-5432}..."
  timeout=60
  while ! pg_isready -h "${DB_HOST}" -p "${DB_PORT:-5432}" -U "${DB_USER:-dodo}" > /dev/null 2>&1; do
    timeout=$((timeout-1))
    if [ $timeout -le 0 ]; then
      echo "[entrypoint] ERROR: PostgreSQL did not become ready in time."
      exit 1
    fi
    sleep 1
  done
  echo "[entrypoint] PostgreSQL is ready."
fi

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] Generating missing migrations..."
  python manage.py makemigrations accounts --noinput || true
  python manage.py makemigrations projects --noinput || true
  python manage.py makemigrations monitoring surveys notifications --noinput || true
  python manage.py makemigrations --noinput || true
  echo "[entrypoint] Applying migrations..."
  python manage.py migrate --noinput
fi

if [ "${COLLECT_STATIC:-1}" = "1" ]; then
  python manage.py collectstatic --noinput --clear > /dev/null 2>&1 || true
fi

if [ "${LOAD_DEMO_DATA:-0}" = "1" ]; then
  python manage.py setup_demo || true
  python manage.py setup_workflow || true
fi

echo "[entrypoint] Starting: $@"
exec "$@"