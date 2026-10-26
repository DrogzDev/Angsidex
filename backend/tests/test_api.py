import json

import pytest

from angside_ai import limits, quote
from angside_ai.models import AiUsageDay, ChatMessage, ChatSession, TurnstileUse
from leads.models import Lead

from .conftest import SECRET_KEY_VALUE, text_round, tool_round

pytestmark = pytest.mark.django_db

URL = '/api/ai/sessions'


def post(client, url, data=None, token=None, **extra):
    headers = {'HTTP_AUTHORIZATION': f'Bearer {token}'} if token else {}
    return client.post(url, data=json.dumps(data or {}), content_type='application/json', **headers, **extra)


def create_session(client, form, captcha):
    resp = post(client, URL, form)
    assert resp.status_code in (200, 201), resp.content
    return resp.json()


def events(resp):
    raw = b''.join(resp.streaming_content).decode()
    return [json.loads(chunk[6:]) for chunk in raw.split('\n\n') if chunk.startswith('data: ')]


# --- Creación de sesión / formulario / CAPTCHA ---

def test_creates_lead_and_session_with_greeting(client, form, captcha):
    data = create_session(client, form, captcha)
    assert data['token'] and data['session_id']
    assert data['messages'][0]['role'] == 'assistant'
    assert 'Panadería La Espiga' in data['messages'][0]['content']
    lead = Lead.objects.get()
    assert lead.marketing_consent is False  # nunca marcado por defecto
    assert lead.budget_range == '200-500'
    assert lead.privacy_version
    assert lead.ip_hash and '127.0.0.1' not in lead.ip_hash


def test_marketing_consent_is_independent_and_stored_when_given(client, form, captcha):
    form['marketing_consent'] = True
    create_session(client, form, captcha)
    assert Lead.objects.get().marketing_consent is True


def test_captcha_failure_creates_nothing(client, form, captcha):
    captcha.success = False
    resp = post(client, URL, form)
    assert resp.status_code == 403
    assert resp.json()['code'] == 'captcha_failed'
    assert Lead.objects.count() == 0 and ChatSession.objects.count() == 0


def test_missing_captcha_token_is_rejected(client, form, captcha):
    del form['turnstile_token']
    assert post(client, URL, form).status_code == 400
    assert Lead.objects.count() == 0


def test_captcha_token_cannot_be_reused(client, form, captcha):
    assert post(client, URL, form).status_code == 201
    form2 = {**form, 'email': 'otra@example.com'}  # mismo token, otro contacto
    resp = post(client, URL, form2)
    assert resp.status_code == 403
    assert TurnstileUse.objects.count() == 1


def test_dummy_token_of_cloudflare_test_key_is_allowed_repeatedly(client, form, captcha):
    form['turnstile_token'] = 'XXXX.DUMMY.TOKEN.XXXX'
    assert post(client, URL, form).status_code == 201
    assert post(client, URL, {**form, 'email': 'otra@example.com'}).status_code == 201


def test_dummy_token_is_single_use_with_a_real_secret(client, form, captcha, settings):
    settings.TURNSTILE_SECRET = '0x4AAAAAAA-real-looking-secret'
    form['turnstile_token'] = 'XXXX.DUMMY.TOKEN.XXXX'
    assert post(client, URL, form).status_code == 201
    assert post(client, URL, {**form, 'email': 'otra@example.com'}).status_code == 403


def test_turnstile_without_secret_fails_closed(client, form, captcha, settings):
    settings.TURNSTILE_SECRET = ''
    assert post(client, URL, form).status_code == 403
    assert Lead.objects.count() == 0


def test_turnstile_network_error_fails_closed(client, form, monkeypatch):
    import httpx
    from angside_ai import turnstile

    def boom(*a, **k):
        raise httpx.ConnectError('down')

    monkeypatch.setattr(turnstile.httpx, 'post', boom)
    assert post(client, URL, form).status_code == 403


def test_requires_email_or_phone(client, form, captcha):
    del form['email']
    resp = post(client, URL, form)
    assert resp.status_code == 400
    form['phone'] = '+58 412 0000000'
    form['turnstile_token'] = 'tok-2'
    assert post(client, URL, form).status_code == 201


@pytest.mark.parametrize('field,value', [
    ('name', 'A'), ('business', ''), ('sector', ''), ('need', 'corto'),
    ('budget_range', 'mucho'), ('email', 'no-es-correo'), ('phone', 'abc'),
])
def test_validation_errors(client, form, captcha, field, value):
    form[field] = value
    if field == 'email':
        form['phone'] = ''
    resp = post(client, URL, form)
    assert resp.status_code == 400
    assert Lead.objects.count() == 0


def test_honeypot_blocks_bots(client, form, captcha):
    form['website_url'] = 'http://spam.example'
    assert post(client, URL, form).status_code == 400
    assert Lead.objects.count() == 0


def test_idempotency_key_prevents_duplicate_sessions(client, form, captcha):
    h = {'HTTP_IDEMPOTENCY_KEY': 'retry-key-12345'}
    a = post(client, URL, form, **h)
    b = post(client, URL, form, **h)  # reintento: no vuelve a gastar el token de Turnstile
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()['session_id'] == b.json()['session_id']
    assert Lead.objects.count() == 1 and ChatSession.objects.count() == 1


def test_same_contact_reuses_recent_session(client, form, captcha):
    a = post(client, URL, form)
    b = post(client, URL, {**form, 'turnstile_token': 'tok-2'})
    assert a.json()['session_id'] == b.json()['session_id']
    assert Lead.objects.count() == 1


def test_ip_rate_limit(client, form, captcha):
    for i in range(5):
        post(client, URL, {**form, 'email': f'u{i}@example.com', 'turnstile_token': f't{i}'})
    resp = post(client, URL, {**form, 'email': 'x@example.com', 'turnstile_token': 'tx'})
    assert resp.status_code == 429
    assert 'Retry-After' in resp


def test_contact_rate_limit(client, form, captcha):
    for i in range(3):
        captcha.success = False  # intentos fallidos también cuentan
        post(client, URL, {**form, 'turnstile_token': f't{i}'})
    resp = post(client, URL, {**form, 'turnstile_token': 'next'})
    assert resp.status_code == 429


# --- Mensajes / streaming / herramientas ---

def msg_url(data):
    return f"/api/ai/sessions/{data['session_id']}/messages"


def test_messages_require_valid_token(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    assert post(client, msg_url(data), {'message': 'hola'}).status_code == 401
    assert post(client, msg_url(data), {'message': 'hola'}, token='basura').status_code == 401


def test_token_of_other_session_is_rejected(client, form, captcha, fake_ai):
    a = create_session(client, form, captcha)
    b = create_session(client, {**form, 'email': 'b@example.com', 'turnstile_token': 't-b'}, captcha)
    assert post(client, msg_url(a), {'message': 'hola'}, token=b['token']).status_code == 401


def test_streams_answer_and_stores_history_and_usage(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [text_round('Claro, cuéntame cuántos productos vendes.')]
    resp = post(client, msg_url(data), {'message': 'Quiero una tienda'}, token=data['token'])
    assert resp['Content-Type'].startswith('text/event-stream')
    evs = events(resp)
    assert ''.join(e['text'] for e in evs if e['type'] == 'delta') == 'Claro, cuéntame cuántos productos vendes.'
    assert evs[-1]['type'] == 'done'
    s = ChatSession.objects.get()
    assert s.user_messages == 1 and s.total_tokens == 70
    assert float(s.cost_usd) == pytest.approx(0.0004)
    assert float(AiUsageDay.objects.get().cost_usd) == pytest.approx(0.0004)
    assert list(s.messages.values_list('role', flat=True)) == ['assistant', 'user', 'assistant']


def test_system_prompt_uses_real_catalog_and_untrusted_lead_data(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [text_round('ok')]
    events(post(client, msg_url(data), {'message': 'hola'}, token=data['token']))
    system = fake_ai.payloads[0]['json']['messages'][0]['content']
    assert '$550' in system and 'Angside' in system and 'cachicamo' not in system.lower() and '100 %' in system
    assert 'no son instrucciones' in system
    assert fake_ai.payloads[0]['json']['model']  # modelo por configuración, no por el frontend
    assert {t['function']['name'] for t in fake_ai.payloads[0]['json']['tools']} == {
        'classify_client', 'propose_options', 'record_negotiation', 'record_objection', 'request_contact', 'save_lead_note',
        'get_payment_options', 'select_payment_mode', 'request_payment_plan_negotiation',
    }
    assert fake_ai.payloads[0]['json']['model'] == 'z-ai/glm-5.3-flash-20260826'
    assert fake_ai.payloads[0]['json']['stream'] is True


def test_tool_call_propose_options_uses_real_engine(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [
        tool_round('propose_options', {'options': [{'tier': 'recommended', 'base_id': 'tienda', 'module_ids': ['bcv'], 'hosting_id': 'vps-basico'}]}),
        text_round('Te recomiendo la tienda con tasa BCV.'),
    ]
    evs = events(post(client, msg_url(data), {'message': 'tienda con tasa BCV'}, token=data['token']))
    ev = next(e for e in evs if e['type'] == 'proposals')
    card = ev['proposals'][0]
    assert card['development_total'] == 640 and card['monthly']['total'] == 15
    assert card['payments'] == {'start': 320, 'delivery': 320}
    assert card['timeline'] == 'Pendiente de evaluación'
    assert quote.decode_state(card['config'])['moduleIds'] == ['bcv']
    # El resultado de la herramienta llegó al modelo en la segunda ronda
    second = fake_ai.payloads[1]['json']['messages']
    tool_msg = next(m for m in second if m['role'] == 'tool')
    assert json.loads(tool_msg['content'])['propuestas'][0]['desarrollo_usd'] == 640
    assert evs[-1]['type'] == 'done'


def test_invalid_tool_arguments_are_returned_to_model_not_executed(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [
        tool_round('propose_options', {'options': [{'tier': 'essential', 'base_id': 'landing', 'module_ids': ['inventario']}]}),
        text_round('Ese módulo no aplica a una landing.'),
    ]
    evs = events(post(client, msg_url(data), {'message': 'landing con inventario'}, token=data['token']))
    assert not any(e['type'] == 'proposals' for e in evs)
    tool_msg = next(m for m in fake_ai.payloads[1]['json']['messages'] if m['role'] == 'tool')
    assert json.loads(tool_msg['content'])['ok'] is False


def test_unknown_tool_and_extra_args_are_rejected(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [tool_round('delete_everything', {'x': 1}), text_round('Perdón.')]
    events(post(client, msg_url(data), {'message': 'hola'}, token=data['token']))
    tool_msg = next(m for m in fake_ai.payloads[1]['json']['messages'] if m['role'] == 'tool')
    assert json.loads(tool_msg['content'])['ok'] is False
    assert Lead.objects.get().status == 'new'


def test_request_contact_tool_marks_lead(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [tool_round('request_contact', {'reason': 'Quiere negociar el precio'}), text_round('Listo, te contactarán.')]
    evs = events(post(client, msg_url(data), {'message': 'quiero negociar'}, token=data['token']))
    assert any(e['type'] == 'contact_requested' for e in evs)
    lead = Lead.objects.get()
    assert lead.status == 'contact_requested' and 'negociar' in lead.notes


def test_request_contact_endpoint(client, form, captcha):
    data = create_session(client, form, captcha)
    resp = post(client, f"/api/ai/sessions/{data['session_id']}/request-contact", {'message': 'Llámenme'}, token=data['token'])
    assert resp.status_code == 200
    assert Lead.objects.get().status == 'contact_requested'


def test_message_limits_per_session(client, form, captcha, fake_ai, settings):
    settings.AI_MAX_USER_MESSAGES_PER_SESSION = 2
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, 'message_session': (100, 60)}
    data = create_session(client, form, captcha)
    fake_ai.rounds = [text_round('uno'), text_round('dos')]
    for _ in range(2):
        events(post(client, msg_url(data), {'message': 'hola'}, token=data['token']))
    resp = post(client, msg_url(data), {'message': 'otra'}, token=data['token'])
    assert resp.status_code == 429 and resp.json()['code'] == 'session_limit'
    assert len(fake_ai.payloads) == 2  # no se llamó a OpenRouter de más


def test_token_limit_per_session_stops_before_calling_model(client, form, captcha, fake_ai, settings):
    settings.AI_MAX_TOKENS_PER_SESSION = 100
    data = create_session(client, form, captcha)
    ChatSession.objects.update(total_tokens=100)
    evs = events(post(client, msg_url(data), {'message': 'hola'}, token=data['token']))
    assert evs[-1]['type'] == 'error' and evs[-1]['code'] == 'session_limit'
    assert fake_ai.payloads == []


def test_daily_budget_blocks_calls(client, form, captcha, fake_ai, settings):
    settings.AI_DAILY_BUDGET_USD = 0.001
    data = create_session(client, form, captcha)
    fake_ai.rounds = [text_round('hola', cost=0.002)]
    events(post(client, msg_url(data), {'message': 'hola'}, token=data['token']))  # agota el presupuesto
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, 'message_session': (100, 60)}
    resp = post(client, msg_url(data), {'message': 'otra'}, token=data['token'])
    assert resp.status_code == 503 and resp.json()['code'] == 'budget_exhausted'
    assert len(fake_ai.payloads) == 1
    assert limits.spent_today() > 0


def test_cost_is_estimated_when_openrouter_omits_it(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    rnd = text_round('hola', usage=(1000, 500))
    rnd[-1]['usage'].pop('cost')
    fake_ai.rounds = [rnd]
    events(post(client, msg_url(data), {'message': 'hola'}, token=data['token']))
    assert float(ChatSession.objects.get().cost_usd) > 0


def test_message_validation(client, form, captcha, fake_ai, settings):
    data = create_session(client, form, captcha)
    assert post(client, msg_url(data), {'message': '   '}, token=data['token']).status_code == 400
    long = 'x' * (settings.AI_MAX_USER_MESSAGE_CHARS + 1)
    assert post(client, msg_url(data), {'message': long}, token=data['token']).json()['code'] == 'message_too_long'
    assert fake_ai.payloads == []


def test_message_rate_limit_per_session(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [text_round('ok')] * 10
    codes = [post(client, msg_url(data), {'message': 'hola'}, token=data['token']).status_code for _ in range(8)]
    assert codes.count(429) >= 1


def test_ai_outage_returns_friendly_error_event(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    fake_ai.status = 500
    evs = events(post(client, msg_url(data), {'message': 'hola'}, token=data['token']))
    assert evs[-1]['type'] == 'error' and evs[-1]['code'] == 'ai_unavailable'


def test_api_key_never_leaks_to_client_or_logs(client, form, captcha, fake_ai, caplog):
    data = create_session(client, form, captcha)
    fake_ai.rounds = [text_round('hola')]
    raw = b''.join(post(client, msg_url(data), {'message': 'hola'}, token=data['token']).streaming_content).decode()
    assert SECRET_KEY_VALUE not in raw and SECRET_KEY_VALUE not in json.dumps(data)
    assert SECRET_KEY_VALUE not in caplog.text
    assert 'tok-1' not in caplog.text  # tampoco el token de CAPTCHA
    assert fake_ai.payloads[0]['headers']['Authorization'] == f'Bearer {SECRET_KEY_VALUE}'


def test_session_history_endpoint(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    resp = client.get(f"/api/ai/sessions/{data['session_id']}", HTTP_AUTHORIZATION=f"Bearer {data['token']}")
    assert resp.status_code == 200 and resp.json()['messages']
    assert client.get(f"/api/ai/sessions/{data['session_id']}").status_code == 401


def test_cors_only_allows_configured_origin(client):
    ok = client.options(URL, HTTP_ORIGIN='http://localhost:4321', HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST')
    bad = client.options(URL, HTTP_ORIGIN='https://evil.example', HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST')
    assert ok.headers.get('access-control-allow-origin') == 'http://localhost:4321'
    assert 'access-control-allow-origin' not in bad.headers
