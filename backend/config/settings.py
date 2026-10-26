"""Configuración de Angside AI Advisor. Todo valor sensible viene de variables de entorno."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Carga un .env simple (KEY=VALUE) sin sobrescribir variables ya definidas."""
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / '.env')


def env(name: str, default: str = '') -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in ('1', 'true', 'yes', 'on')


def env_list(name: str, default: str = '') -> list[str]:
    return [v.strip() for v in env(name, default).split(',') if v.strip()]


DEBUG = env_bool('DJANGO_DEBUG', False)

SECRET_KEY = env('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('DJANGO_SECRET_KEY es obligatorio cuando DJANGO_DEBUG es falso.')
    SECRET_KEY = 'dev-only-insecure-key-change-me'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'leads',
    'commercial',
    'angside_ai',
    'panel',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': env('DJANGO_DB_PATH', str(BASE_DIR / 'db.sqlite3')),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es'
TIME_ZONE = 'America/Caracas'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- API / CORS ---
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
    'UNAUTHENTICATED_USER': None,
}

# Solo el dominio del sitio puede llamar a la API desde el navegador.
CORS_ALLOWED_ORIGINS = env_list('ALLOWED_ORIGINS', 'http://localhost:4321,http://localhost:4399,http://127.0.0.1:4321,http://127.0.0.1:4399')
# El panel usa cookies de sesión: el navegador solo las envía a orígenes explícitamente permitidos.
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
CSRF_FAILURE_VIEW = 'panel.views.csrf_failure'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_NAME = 'angside_sid'
CORS_ALLOW_HEADERS = ['content-type', 'authorization', 'idempotency-key', 'x-csrftoken']
CORS_ALLOW_METHODS = ['GET', 'POST', 'PATCH', 'OPTIONS']

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SSL_REDIRECT', True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# --- Turnstile ---
# Para desarrollo usa los secretos de prueba de Cloudflare (ver .env.example).
TURNSTILE_SECRET = env('TURNSTILE_SECRET')
TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'

# --- OpenRouter / IA ---
OPENROUTER_API_KEY = env('OPENROUTER_API_KEY')
OPENROUTER_BASE_URL = env('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
# Modelo y respaldos configurables sin tocar el frontend. Verificar que soporten tools y salida estructurada.
AI_MODEL = env('OPENROUTER_MODEL', 'z-ai/glm-5.3-flash-20260826')
# GLM-5.3 Flash admite razonamiento; un esfuerzo bajo y sin devolverlo reduce costo y latencia en el chat comercial.
AI_REASONING_EFFORT = env('AI_REASONING_EFFORT', 'low')  # '', 'low', 'medium', 'high'
AI_MAX_PROPOSAL_ROUNDS = int(env('AI_MAX_PROPOSAL_ROUNDS', '6'))
AI_FALLBACK_MODELS = env_list('OPENROUTER_FALLBACK_MODELS', '')
AI_SITE_URL = env('AI_SITE_URL', 'https://angside.example')
AI_SITE_NAME = 'Angside'

# --- Límites y costos ---
AI_MAX_USER_MESSAGES_PER_SESSION = int(env('AI_MAX_USER_MESSAGES_PER_SESSION', '20'))
AI_MAX_TOKENS_PER_SESSION = int(env('AI_MAX_TOKENS_PER_SESSION', '30000'))
AI_MAX_OUTPUT_TOKENS = int(env('AI_MAX_OUTPUT_TOKENS', '1500'))
AI_MAX_USER_MESSAGE_CHARS = int(env('AI_MAX_USER_MESSAGE_CHARS', '1200'))
AI_DAILY_BUDGET_USD = float(env('AI_DAILY_BUDGET_USD', '2.00'))
AI_MONTHLY_BUDGET_USD = float(env('AI_MONTHLY_BUDGET_USD', '30.00'))
# Respaldo si OpenRouter no informa el costo (USD por millón de tokens).
AI_PRICE_IN_PER_M = float(env('AI_PRICE_IN_PER_M', '0.15'))
AI_PRICE_OUT_PER_M = float(env('AI_PRICE_OUT_PER_M', '0.50'))

# Rate limits: (cantidad, ventana en segundos)
RATE_LIMITS = {
    'session_create_ip': (5, 3600),
    'session_create_contact': (3, 3600),
    'message_ip': (60, 600),
    'message_session': (6, 60),
    'contact_request_session': (3, 3600),
    'profile_session': (10, 3600),
    'payment_mode_session': (30, 3600),
    'quote_register_ip': (20, 3600),
    'config_read_ip': (120, 600),
    'panel_login_ip': (10, 900),
    'panel_login_user': (6, 900),
}
# Detrás de Cloudflare, confiar en CF-Connecting-IP (activar solo si el origen solo recibe tráfico de Cloudflare).
TRUST_CF_CONNECTING_IP = env_bool('TRUST_CF_CONNECTING_IP', False)

SESSION_TOKEN_MAX_AGE = 60 * 60 * 6
PRIVACY_POLICY_VERSION = env('PRIVACY_POLICY_VERSION', '2026-10')
SESSION_REUSE_WINDOW = 60 * 30

# Contrato de precios generado desde src/data/pricing.ts (npm run export:contract).
PRICING_CONTRACT_PATH = BASE_DIR / 'angside_ai' / 'data' / 'pricing.json'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {'angside_ai': {'handlers': ['console'], 'level': 'INFO'}},
}
