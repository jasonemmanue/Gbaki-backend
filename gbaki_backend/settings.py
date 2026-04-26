"""
gbaki_backend/settings.py
"""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-gbaki-dev-key-change-in-prod')
DEBUG = os.environ.get('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    'storages',
    'core',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gbaki_backend.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]

WSGI_APPLICATION = 'gbaki_backend.wsgi.application'

# ── Base de données ───────────────────────────────────────────────────────────
# SQLite local par défaut.
# Pour Cloudflare D1 : installe django-cloudflare-d1 et configure DATABASE_URL
# Voir README_CLOUDFLARE.md inclus dans le zip
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ── Cloudflare R2 (stockage fichiers) ────────────────────────────────────────
# Remplis ces variables dans ton .env ou via les variables d'environnement
CF_R2_ACCESS_KEY     = os.environ.get('CF_R2_ACCESS_KEY', '')
CF_R2_SECRET_KEY     = os.environ.get('CF_R2_SECRET_KEY', '')
CF_R2_BUCKET_NAME    = os.environ.get('CF_R2_BUCKET_NAME', 'gbaki-documents')
CF_R2_ENDPOINT_URL   = os.environ.get('CF_R2_ENDPOINT_URL', '')   # ex: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CF_R2_PUBLIC_DOMAIN  = os.environ.get('CF_R2_PUBLIC_DOMAIN', '')  # ex: https://pub-xxx.r2.dev  (si bucket public)

# URL signée expirée après N secondes (pour téléchargements privés)
CF_R2_PRESIGN_EXPIRY = int(os.environ.get('CF_R2_PRESIGN_EXPIRY', '3600'))

# ── DRF ──────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.TokenAuthentication'],
    'DEFAULT_PERMISSION_CLASSES':     ['rest_framework.permissions.IsAuthenticatedOrReadOnly'],
}

# ── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# ── I18n ─────────────────────────────────────────────────────────────────────
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE     = 'Africa/Abidjan'
USE_I18N      = True
USE_TZ        = True

STATIC_URL = '/static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
