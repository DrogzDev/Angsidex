"""API del panel: sesión + CSRF, permisos por rol y datos de prospectos."""
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from angside_ai.models import ChatMessage, ChatSession
from commercial import services
from leads.models import Lead, Proposal

pytestmark = pytest.mark.django_db

PASSWORD = 'clave-de-prueba-123'


@pytest.fixture
def staff():
    return get_user_model().objects.create_user('equipo', password=PASSWORD, is_staff=True)


@pytest.fixture
def customer():
    return get_user_model().objects.create_user('cliente', password=PASSWORD)


@pytest.fixture
def browser():
    """Cliente que, como un navegador real, hace cumplir CSRF."""
    return Client(enforce_csrf_checks=True)


def post(c, path, data, token=None):
    headers = {'HTTP_X_CSRFTOKEN': token} if token else {}
    return c.post(path, json.dumps(data), content_type='application/json', **headers)


def token_of(c):
    return c.get('/api/panel/csrf').json()['csrf']


def sign_in(c, user='equipo'):
    resp = post(c, '/api/panel/login', {'username': user, 'password': PASSWORD}, token_of(c))
    assert resp.status_code == 200, resp.content
    return resp.json()['csrf']


@pytest.fixture
def lead():
    lead = Lead.objects.create(name='Ana Pérez', business='Panadería Sol', email='ana@sol.co', whatsapp='584141112233', sector='Alimentos',
                               need='Vender pan en línea', privacy_version='1')
    session = ChatSession.objects.create(lead=lead)
    ChatMessage.objects.create(session=session, role='user', content='Necesito una tienda')
    ChatMessage.objects.create(session=session, role='assistant', content='Te recomiendo tienda online')
    ChatMessage.objects.create(session=session, role='tool', content='{"interno": true}')
    Proposal.objects.create(lead=lead, session=session, tier='recommended', config='b=tienda', development_total=550, complexity='basic',
                            payment_mode='cash', payload={'features': [{'label': 'Tienda online'}]})
    return lead


# --- Sesión y CSRF ---

def test_login_without_csrf_token_is_rejected(browser, staff):
    resp = post(browser, '/api/panel/login', {'username': 'equipo', 'password': PASSWORD})
    assert resp.status_code == 403 and resp.json()['code'] == 'csrf_failed'


def test_login_with_csrf_opens_a_session_and_rotates_the_token(browser, staff):
    first = token_of(browser)
    resp = post(browser, '/api/panel/login', {'username': 'equipo', 'password': PASSWORD}, first)
    body = resp.json()
    assert resp.status_code == 200 and body['user'] == {'username': 'equipo', 'name': 'equipo', 'role': 'staff'}
    assert body['csrf'] != first  # Django rota el token al iniciar sesión
    assert browser.get('/api/panel/me').json()['authenticated'] is True
    cookie = resp.cookies['angside_sid']
    assert cookie['httponly'] and cookie['samesite'] == 'Lax'


def test_wrong_credentials_are_generic(browser, staff):
    bad_pass = post(browser, '/api/panel/login', {'username': 'equipo', 'password': 'mala'}, token_of(browser))
    unknown = post(browser, '/api/panel/login', {'username': 'nadie', 'password': 'mala'}, token_of(browser))
    assert bad_pass.status_code == unknown.status_code == 401
    assert bad_pass.json() == unknown.json()  # no revela si el usuario existe


def test_inactive_user_cannot_login(browser, staff):
    staff.is_active = False
    staff.save()
    assert post(browser, '/api/panel/login', {'username': 'equipo', 'password': PASSWORD}, token_of(browser)).status_code == 401


def test_login_is_rate_limited_per_user(browser, staff):
    codes = [post(browser, '/api/panel/login', {'username': 'equipo', 'password': 'mala'}, token_of(browser)).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]


def test_logout_requires_csrf_and_closes_the_session(browser, staff):
    token = sign_in(browser)
    assert post(browser, '/api/panel/logout', {}).status_code == 403
    assert post(browser, '/api/panel/logout', {}, token).status_code == 200
    assert browser.get('/api/panel/me').json()['authenticated'] is False


def test_state_changing_requests_need_csrf_even_when_logged_in(browser, staff, lead):
    sign_in(browser)
    resp = browser.patch(f'/api/panel/leads/{lead.pk}', json.dumps({'status': 'won'}), content_type='application/json')
    assert resp.status_code == 403
    lead.refresh_from_db()
    assert lead.status == 'new'


# --- Permisos ---

@pytest.mark.parametrize('path', ['/api/panel/overview', '/api/panel/leads', '/api/panel/quotes', '/api/panel/leads/1'])
def test_admin_endpoints_require_a_session(browser, path):
    assert browser.get(path).status_code == 401


def test_customers_cannot_read_admin_data(browser, customer, lead):
    sign_in(browser, 'cliente')
    me = browser.get('/api/panel/me').json()
    assert me['user']['role'] == 'client'
    for path in ('/api/panel/overview', '/api/panel/leads', f'/api/panel/leads/{lead.pk}', '/api/panel/quotes'):
        assert browser.get(path).status_code == 403


def test_cors_allows_the_site_origin_with_credentials(browser):
    resp = browser.get('/api/panel/me', HTTP_ORIGIN='http://127.0.0.1:4321')
    assert resp['Access-Control-Allow-Origin'] == 'http://127.0.0.1:4321' and resp['Access-Control-Allow-Credentials'] == 'true'
    other = browser.get('/api/panel/me', HTTP_ORIGIN='https://evil.example')
    assert 'Access-Control-Allow-Origin' not in other


# --- Datos ---

def test_overview_counts(browser, staff, lead):
    services.current_config()
    sign_in(browser)
    data = browser.get('/api/panel/overview').json()
    assert data['leads']['total'] == 1 and data['leads']['today'] == 1
    assert {s['status']: s['count'] for s in data['leads']['by_status']}['new'] == 1
    assert {m['mode']: m['count'] for m in data['payment_modes']}['cash'] == 1
    assert data['recent_leads'][0]['business'] == 'Panadería Sol'
    assert data['ai']['sessions'] == 1


def test_lead_list_search_and_filters(browser, staff, lead):
    Lead.objects.create(name='Luis', business='Taller Gato', email='l@g.co', sector='Autopartes', need='x', privacy_version='1', status='won')
    sign_in(browser)
    assert browser.get('/api/panel/leads').json()['total'] == 2
    found = browser.get('/api/panel/leads', {'q': 'sol'}).json()
    assert [i['business'] for i in found['items']] == ['Panadería Sol'] and found['items'][0]['payment_modes'] == ['cash']
    assert browser.get('/api/panel/leads', {'status': 'won'}).json()['total'] == 1
    assert browser.get('/api/panel/leads', {'page': 'x'}).status_code == 200


def test_lead_detail_has_conversation_without_tool_messages_and_proposals(browser, staff, lead):
    sign_in(browser)
    data = browser.get(f'/api/panel/leads/{lead.pk}').json()
    (conv,) = data['conversations']
    assert [(m['role'], m['text']) for m in conv['messages']] == [('user', 'Necesito una tienda'), ('assistant', 'Te recomiendo tienda online')]
    (prop,) = data['proposals_detail']
    assert prop['payment_mode'] == 'cash' and prop['features'] == ['Tienda online'] and prop['development_total'] == 550
    assert browser.get('/api/panel/leads/99999').status_code == 404


def test_patch_updates_status_and_notes_only_with_valid_values(browser, staff, lead):
    token = sign_in(browser)

    def patch(body):
        return browser.patch(f'/api/panel/leads/{lead.pk}', json.dumps(body), content_type='application/json', HTTP_X_CSRFTOKEN=token)

    ok = patch({'status': 'contacted', 'notes': 'Llamar el lunes'})
    assert ok.status_code == 200 and ok.json()['status_label'] == 'Contactado'
    lead.refresh_from_db()
    assert (lead.status, lead.notes) == ('contacted', 'Llamar el lunes')
    assert patch({'status': 'hackeado'}).status_code == 400
    assert patch({'notes': 'x' * 4001}).status_code == 400
    lead.refresh_from_db()
    assert lead.status == 'contacted'


def test_saved_quotes_listing(browser, staff):
    from commercial.models import SavedQuote

    version = services.publish_version()
    SavedQuote.objects.create(reference='ANG-ABCD1234', config_query='b=landing', payment_mode='cash', pricing_version=version,
                              development_original=180, development_total=138.6)
    sign_in(browser)
    (item,) = browser.get('/api/panel/quotes').json()['items']
    assert item['reference'] == 'ANG-ABCD1234' and item['development_total'] == 138.6
