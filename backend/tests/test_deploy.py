"""Piezas de despliegue: salud, caché de la API, DATABASE_URL y ruta del admin."""
import pytest

from config import database

pytestmark = pytest.mark.django_db


def test_healthz_reports_ok_when_the_database_answers(client):
    resp = client.get('/healthz')
    assert resp.status_code == 200 and resp.json() == {'status': 'ok'}


def test_healthz_returns_503_when_the_database_fails(client, monkeypatch):
    from django.db import connection

    def boom(*args, **kwargs):
        raise RuntimeError('db caída')

    monkeypatch.setattr(connection, 'cursor', boom)
    assert client.get('/healthz').status_code == 503


@pytest.mark.parametrize('path', ['/api/panel/me', '/api/panel/csrf', '/api/panel/overview'])
def test_api_responses_are_never_cached(client, path):
    assert client.get(path)['Cache-Control'] == 'no-store'


def test_public_pricing_config_keeps_its_short_public_cache(client):
    assert client.get('/api/commercial/config')['Cache-Control'] == 'public, max-age=60'


def test_non_api_paths_are_not_forced_to_no_store(client):
    assert 'no-store' not in client.get('/healthz').get('Cache-Control', '')


def test_database_url_is_parsed_with_escaped_credentials():
    cfg = database.from_url('postgres://angside:p%40ss%2Fword@db:5432/angside')
    assert cfg['ENGINE'] == 'django.db.backends.postgresql'
    assert (cfg['USER'], cfg['PASSWORD'], cfg['HOST'], cfg['PORT'], cfg['NAME']) == ('angside', 'p@ss/word', 'db', '5432', 'angside')
    assert cfg['CONN_HEALTH_CHECKS'] is True


def test_database_url_defaults_the_port():
    assert database.from_url('postgresql://u:p@host/name')['PORT'] == '5432'


@pytest.mark.parametrize('url', ['mysql://u:p@h/n', 'postgres://u:p@h', 'postgres:///n', ''])
def test_invalid_database_urls_fail_loudly(url):
    with pytest.raises(ValueError):
        database.from_url(url)


def test_admin_url_is_configurable(settings):
    from config import urls

    assert settings.ADMIN_URL.endswith('/') and not settings.ADMIN_URL.startswith('/')
    assert any(str(p.pattern) == settings.ADMIN_URL for p in urls.urlpatterns)
