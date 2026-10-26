"""Configuración de base de datos desde DATABASE_URL (postgres://usuario:clave@host:5432/nombre); sin URL se usa SQLite local."""
from pathlib import Path
from urllib.parse import unquote, urlparse


def from_url(url: str, conn_max_age: int = 60) -> dict:
    parsed = urlparse(url)
    if parsed.scheme not in ('postgres', 'postgresql'):
        raise ValueError(f'DATABASE_URL no soportada: {parsed.scheme or "(vacía)"}://')
    name = parsed.path.lstrip('/')
    if not name or not parsed.hostname:
        raise ValueError('DATABASE_URL debe incluir host y nombre de la base de datos.')
    return {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': unquote(name),
        'USER': unquote(parsed.username or ''),
        'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname,
        'PORT': str(parsed.port or 5432),
        'CONN_MAX_AGE': conn_max_age,
        'CONN_HEALTH_CHECKS': True,
    }


def sqlite(path: str | Path) -> dict:
    return {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(path)}
