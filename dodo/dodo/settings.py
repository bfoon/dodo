"""
Dodo — Django Settings
Reads configuration from environment variables for Docker/12-factor deployment.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(key, default=False):
    val = os.environ.get(key, str(default)).lower()
    return val in ('true', '1', 'yes', 'on')


def env_list(key, default=''):
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(',') if item.strip()]


# Core
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-dodo-CHANGE-ME-IN-PRODUCTION-xxxxxxxxxxxxxxxxxxxxxxxxxx'
)
DEBUG = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,web,*')
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS', 'http://localhost,http://127.0.0.1')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    # Third-party
    'crispy_forms',
    'crispy_bootstrap5',
    'django_filters',
    'django_celery_beat',
    'django_celery_results',
    # Dodo Apps
    'apps.accounts',
    'apps.projects',
    'apps.monitoring',
    'apps.surveys',
    'apps.reporting',
    'apps.dashboard',
    'apps.notifications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.accounts.middleware.CountryOfficeMiddleware',
]

ROOT_URLCONF = 'dodo.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
            'apps.accounts.context_processors.user_context',
            'apps.notifications.context_processors.notifications_context',
        ],
    },
}]

WSGI_APPLICATION = 'dodo.wsgi.application'
ASGI_APPLICATION = 'dodo.asgi.application'

# Database — Postgres via env vars, sqlite fallback
if os.environ.get('DB_ENGINE', '').lower() == 'postgres' or os.environ.get('DB_HOST'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'dodo'),
            'USER': os.environ.get('DB_USER', 'dodo'),
            'PASSWORD': os.environ.get('DB_PASSWORD', 'dodo'),
            'HOST': os.environ.get('DB_HOST', 'db'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': 60,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Cache & Celery
REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': REDIS_URL,
    } if os.environ.get('REDIS_URL') else {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Auth
AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
]
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# i18n
LANGUAGE_CODE = os.environ.get('DJANGO_LANGUAGE_CODE', 'en-us')
TIME_ZONE = os.environ.get('DJANGO_TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

# Static & media
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Bootstrap / crispy-forms
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# Email
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.office365.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'Dodo <noreply@dodo.undp.org>')

# Production security
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', False)
    CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', False)
    X_FRAME_OPTIONS = 'DENY'

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '[{asctime}] {levelname} {name} {message}', 'style': '{'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'verbose'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'apps': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
    },
}

# Platform metadata
DODO_PLATFORM_NAME = 'Dodo'
DODO_PLATFORM_VERSION = '1.0.0'
