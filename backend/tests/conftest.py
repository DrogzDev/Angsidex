import json
import itertools

import pytest

from angside_ai import openrouter, turnstile

SECRET_KEY_VALUE = 'sk-or-test-SUPER-SECRET'


@pytest.fixture(autouse=True)
def _settings(settings):
    settings.OPENROUTER_API_KEY = SECRET_KEY_VALUE
    settings.TURNSTILE_SECRET = '1x0000000000000000000000000000000AA'
    settings.ALLOWED_HOSTS = ['testserver']
    settings.RATE_LIMITS = {
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
        'panel_login_user': (3, 900),
    }
    settings.AI_MAX_USER_MESSAGES_PER_SESSION = 20
    settings.AI_MAX_TOKENS_PER_SESSION = 30000
    settings.AI_DAILY_BUDGET_USD = 2.0
    settings.AI_MONTHLY_BUDGET_USD = 30.0
    return settings


class _Resp:
    def __init__(self, success=True):
        self._success = success

    def raise_for_status(self):
        pass

    def json(self):
        return {'success': self._success}


@pytest.fixture
def captcha(monkeypatch):
    """Simula Cloudflare Turnstile. captcha.success = False para rechazar; captcha.calls cuenta las consultas."""
    state = type('S', (), {'success': True, 'calls': []})()

    def fake_post(url, data=None, timeout=None):
        state.calls.append(data)
        return _Resp(state.success)

    monkeypatch.setattr(turnstile.httpx, 'post', fake_post)
    return state


class _FakeStream:
    def __init__(self, chunks, status_code=200):
        self.status_code = status_code
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b''

    def iter_lines(self):
        yield ': OPENROUTER PROCESSING'
        for c in self._chunks:
            yield 'data: ' + json.dumps(c)
        yield 'data: [DONE]'


def text_round(text, usage=(50, 20), cost=0.0004):
    half = max(len(text) // 2, 1)
    return [
        {'choices': [{'delta': {'content': text[:half]}}]},
        {'choices': [{'delta': {'content': text[half:]}}]},
        {'choices': [], 'usage': {'prompt_tokens': usage[0], 'completion_tokens': usage[1], 'cost': cost}},
    ]


def tool_round(name, args, call_id='call_1', usage=(60, 25), cost=0.0005):
    raw = json.dumps(args)
    cut = len(raw) // 2
    return [
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': call_id, 'function': {'name': name, 'arguments': raw[:cut]}}]}}]},
        {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': raw[cut:]}}]}}]},
        {'choices': [], 'usage': {'prompt_tokens': usage[0], 'completion_tokens': usage[1], 'cost': cost}},
    ]


@pytest.fixture
def fake_ai(monkeypatch):
    """Simula OpenRouter. fake_ai.rounds = [ronda1, ronda2, ...]; fake_ai.payloads guarda lo enviado."""
    state = type('S', (), {'rounds': [], 'payloads': [], 'status': 200})()

    def fake_stream(method, url, json=None, headers=None, timeout=None):
        state.payloads.append({'url': url, 'json': json, 'headers': headers})
        # Cada llamada a OpenRouter consume la siguiente ronda del guion (o responde "ok" si se acabó).
        chunks = state.rounds.pop(0) if state.rounds else text_round('ok')
        return _FakeStream(chunks, state.status)

    monkeypatch.setattr(openrouter.httpx, 'stream', fake_stream)
    return state


VALID_FORM = {
    'name': 'María Pérez',
    'business': 'Panadería La Espiga',
    'email': 'maria@example.com',
    'sector': 'Alimentos',
    'need': 'Quiero vender mis panes por internet y controlar el inventario.',
    'budget_range': '200-500',
    'turnstile_token': 'tok-1',
}


@pytest.fixture
def form():
    return dict(VALID_FORM)
