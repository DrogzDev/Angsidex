"""Respaldo para modelos que escriben las herramientas como texto (<tool_call>...)."""
import json

import pytest

from angside_ai.textcalls import TextToolCallFilter, parse_calls
from leads.models import Lead, Proposal

from .conftest import text_round
from .test_api import create_session, events, msg_url, post
from .test_scenarios import say

pytestmark = pytest.mark.django_db

GLM_STYLE = (
    '<tool_call>propose_options<arg_key>options</arg_key><arg_value>'
    '[{"tier": "recommended", "base_id": "tienda", "module_ids": ["whatsapp"], "hosting_id": "vps-basico"}]'
    '</arg_value></tool_call>'
)


def run_filter(chunks):
    f = TextToolCallFilter()
    shown = ''.join(f.feed(c) for c in chunks)
    tail, calls = f.finish()
    return shown + tail, calls


def test_parse_glm_style_call():
    (call,) = parse_calls(GLM_STYLE)
    assert call['name'] == 'propose_options'
    assert json.loads(call['arguments'])['options'][0]['base_id'] == 'tienda'


def test_parse_scalar_and_string_arguments_and_missing_closing_tag():
    raw = '<tool_call>record_negotiation<arg_key>reason</arg_key><arg_value>Muy caro</arg_value><arg_key>ideal_budget_usd</arg_key><arg_value>400</arg_value>'
    (call,) = parse_calls(raw)
    assert json.loads(call['arguments']) == {'reason': 'Muy caro', 'ideal_budget_usd': 400}


def test_parse_json_object_variant_and_garbage():
    (call,) = parse_calls('<tool_call>save_lead_note {"note": "urgente"}</tool_call>')
    assert json.loads(call['arguments']) == {'note': 'urgente'}
    assert parse_calls('<tool_call></tool_call> nada') == []


def test_filter_passes_normal_text_untouched():
    shown, calls = run_filter(['Hola, ', 'te cuento que ', '1 < 2 y a <b> c'])
    assert shown == 'Hola, te cuento que 1 < 2 y a <b> c' and calls == []


def test_filter_hides_tool_call_split_across_chunks():
    # El marcador llega partido en varios fragmentos y el texto previo sí se muestra.
    text = 'Voy a armar tus opciones. ' + GLM_STYLE
    for size in (1, 3, 7, 50):
        chunks = [text[i:i + size] for i in range(0, len(text), size)]
        shown, calls = run_filter(chunks)
        assert shown == 'Voy a armar tus opciones. ', size
        assert calls and calls[0]['name'] == 'propose_options'


def test_filter_releases_a_false_marker_prefix_at_the_end():
    shown, calls = run_filter(['Mira <tool_', 'x'])
    assert shown == 'Mira <tool_x' and calls == []
    shown, calls = run_filter(['termina en <tool_c'])
    assert shown == 'termina en <tool_c'


def test_text_tool_call_end_to_end_creates_cards_and_hides_raw_text(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    # Ronda 1: el modelo "escribe" la herramienta como texto. Ronda 2: explica.
    half = len(GLM_STYLE) // 2
    fake_ai.rounds = [
        [
            {'choices': [{'delta': {'content': 'Te armo las opciones. '}}]},
            {'choices': [{'delta': {'content': GLM_STYLE[:half]}}]},
            {'choices': [{'delta': {'content': GLM_STYLE[half:]}}]},
            {'choices': [], 'usage': {'prompt_tokens': 50, 'completion_tokens': 40, 'cost': 0.0004}},
        ],
        text_round('Listo: la recomendada incluye WhatsApp.'),
    ]
    evs = events(post(client, msg_url(data), {'message': 'quiero una tienda'}, token=data['token']))
    shown = ''.join(e['text'] for e in evs if e['type'] == 'delta')
    assert '<tool_call>' not in shown and 'arg_key' not in shown
    assert 'Te armo las opciones.' in shown and 'la recomendada incluye WhatsApp' in shown
    card = next(e for e in evs if e['type'] == 'proposals')['proposals'][0]
    assert card['development_total'] == 700  # tienda 550 + WhatsApp 150, calculado por el motor
    assert Proposal.objects.count() == 1


def test_text_tool_call_with_invalid_arguments_is_rejected_like_any_other(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    bad = '<tool_call>propose_options<arg_key>options</arg_key><arg_value>[{"tier": "recommended", "base_id": "tienda", "discount_percent": 50}]</arg_value></tool_call>'
    evs = say(client, data, fake_ai, 'dame descuento', [{'choices': [{'delta': {'content': bad}}]}, {'choices': [], 'usage': {'prompt_tokens': 5, 'completion_tokens': 5, 'cost': 0.0001}}], text_round('No manejo descuentos.'))
    assert not any(e['type'] == 'proposals' for e in evs)
    assert Proposal.objects.count() == 0 and Lead.objects.count() == 1


def test_request_asks_openrouter_for_providers_that_support_tools(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    say(client, data, fake_ai, 'hola', text_round('ok'))
    sent = fake_ai.payloads[0]['json']
    assert sent['provider'] == {'require_parameters': True} and sent['tool_choice'] == 'auto'
