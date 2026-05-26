"""
configuracion de django gpiv
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# seguridad
SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-fallback-local-only')
# En producción, si no se setea la variable DEBUG, el fallback es False (seguro).
# En desarrollo local, setear DEBUG=True en el .env.
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', 'http://localhost,http://127.0.0.1').split(',')

# aplicaciones
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'simple_history',
    'django_ratelimit',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'simple_history.middleware.HistoryRequestMiddleware',
]

ROOT_URLCONF = 'gpiv.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.user_groups',
            ],
        },
    },
]

WSGI_APPLICATION = 'gpiv.wsgi.application'


# base de datos local / docker
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('POSTGRES_DB', 'gpiv_db'),
        'USER': os.environ.get('POSTGRES_USER', 'gpiv_user'),
        'PASSWORD': os.environ.get('POSTGRES_PASSWORD', 'gpiv_password'),
        'HOST': os.environ.get('DB_HOST', 'db'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}


# validadores
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# i18n
LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'America/Argentina/Buenos_Aires'
USE_I18N = True
USE_TZ = True


# assets y carpetas de estaticos
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'assets',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Caché Redis — requerido por django-ratelimit (necesita shared cache con
# soporte de incr() atómico). Usa el backend nativo de Django 4+, sin
# paquetes extra. La URL apunta al servicio 'redis' del docker-compose.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': os.environ.get('REDIS_URL', 'redis://redis:6379/1'),
    }
}

# Rate limiting — usa el cache 'default' configurado arriba.
# RATELIMIT_FAIL_OPEN=False: si la caché falla, se BLOQUEA (fail closed = más seguro).
RATELIMIT_USE_CACHE = 'default'
RATELIMIT_FAIL_OPEN = False

# Seguridad HTTP — se activan solo en producción (DEBUG=False).
# En desarrollo local con HTTP no se aplican para no romper el flujo.
SESSION_COOKIE_SECURE = not DEBUG   # Cookie de sesión solo por HTTPS
CSRF_COOKIE_SECURE = not DEBUG      # Cookie CSRF solo por HTTPS
SECURE_SSL_REDIRECT = not DEBUG     # Redirige HTTP → HTTPS automáticamente
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000   # HSTS: 1 año en producción
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG

# Usuario customizado para roles
AUTH_USER_MODEL = 'core.CustomUser'

# Backends de autenticación: primero username/email dual, luego el estándar de Django.
# El backend propio busca primero por username y, si no coincide, por email (case-insensitive).
AUTHENTICATION_BACKENDS = [
    'core.backends.EmailOrUsernameModelBackend',
    'django.contrib.auth.backends.ModelBackend',
]

LOGIN_URL = 'core:login'
LOGIN_REDIRECT_URL = 'core:inicio'
LOGOUT_REDIRECT_URL = 'core:landing'

# Archivos subidos por usuarios (escrituras, certificados)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# clave de resend.com para envio transaccional. si esta vacia los emails se
# loguean como warning y no se envian (modo dev sin proveedor configurado).
# la misma key se usa para el SDK (tickets) y para SMTP (password reset).
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')

# correo saliente. si hay api key de resend, usamos su relay SMTP para que
# password_reset y cualquier otro email nativo de django funcione automatico.
# si no hay key (dev local), queda en console backend (imprime en stdout).
if RESEND_API_KEY:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = 'smtp.resend.com'
    EMAIL_PORT = 465
    EMAIL_USE_SSL = True
    EMAIL_HOST_USER = 'resend'
    EMAIL_HOST_PASSWORD = RESEND_API_KEY
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
    EMAIL_HOST = 'localhost'
    EMAIL_PORT = 25
    EMAIL_USE_SSL = False
    EMAIL_HOST_USER = ''
    EMAIL_HOST_PASSWORD = ''

DEFAULT_FROM_EMAIL = os.environ.get(
    'DEFAULT_FROM_EMAIL', 'GPIV <noreply@gpiv.tivena.com.ar>',
)

# bandeja que recibe avisos internos de tickets nuevos. en produccion poner
# el email de quien monitorea (ej: tu gmail personal). NO usar enrepavi.
SUPPORT_INBOX_EMAIL = os.environ.get('SUPPORT_INBOX_EMAIL', DEFAULT_FROM_EMAIL)

# url base del sitio para generar links absolutos en emails transaccionales.
# sin barra final. en desarrollo queda en localhost, en produccion se setea
# al dominio real.
SITE_URL = os.environ.get('SITE_URL', 'http://localhost:8000')
