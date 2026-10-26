"""
Modalidades de pago, descuento de contado, versionado de precios, API pública, administración y consumo de IA del chatbot.
Ninguna prueba llama a OpenRouter ni consume créditos: la red está simulada.
"""
import json
from decimal import Decimal

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from angside_ai import guard, limits, prompts, quote
from angside_ai.models import ChatSession
from commercial import engine, rates, services
from commercial.models import CommercialSettings, ModuleRule, PaymentPlan, PricingVersion, SavedQuote, UsageTier
from leads.models import Lead, Proposal

from .conftest import text_round, tool_round
from .test_api import create_session, events, msg_url, post
from .test_scenarios import cards_of, opt, say

pytestmark = pytest.mark.django_db

DEV_1200 = [
    {'kind': 'base', 'id': 'sistema', 'price': 650}, {'kind': 'module', 'id': 'crm', 'price': 180},
    {'kind': 'module', 'id': 'panel', 'price': 180}, {'kind': 'module', 'id': 'bcv', 'price': 90}, {'kind': 'module', 'id': 'reportes', 'price': 100},
]


@pytest.fixture
def cfg():
    return services.current_config()


def settings_row() -> CommercialSettings:
    return services.ensure_settings()


# --- Motor: ejemplos del enunciado comercial -------------------------------------------------------------------

def test_cash_discount_is_exactly_23_percent(cfg):
    p = engine.compute_payment(DEV_1200, 'cash', cfg)
    assert (p['originalCents'], p['discountCents'], p['savingsCents'], p['totalCents']) == (120000, 27600, 27600, 92400)


@pytest.mark.parametrize('mode,total,initial,each,count,dues', [
    ('m3', 132000, 52800, 26400, 3, ['Mes 1', 'Mes 2', 'Mes 3']),
    ('m6', 138000, 55200, 13800, 6, [f'Mes {i}' for i in range(1, 7)]),
    ('m9', 145000, 58000, 29000, 3, ['Mes 3', 'Mes 6', 'Mes 9']),
])
def test_financing_plans_have_no_discount_and_exact_schedule(cfg, mode, total, initial, each, count, dues):
    p = engine.compute_payment(DEV_1200, mode, cfg)
    assert (p['totalCents'], p['initialCents'], p['installmentCents'], p['installmentCount']) == (total, initial, each, count)
    assert p['discountCents'] == 0 and p['requiresApproval'] is True
    assert [s['due'] for s in p['schedule']][1:] == dues
    assert sum(s['amountCents'] for s in p['schedule']) == p['totalCents']


def test_last_payment_absorbs_cents(cfg):
    for price in (0.01, 33.33, 100.01, 777.77, 1234.56):
        for mode in ('m3', 'm6', 'm9'):
            p = engine.compute_payment([{'kind': 'base', 'id': 'x', 'price': price}], mode, cfg)
            assert sum(s['amountCents'] for s in p['schedule']) == p['totalCents']


def test_rounding_is_half_up_not_bankers():
    assert engine.percent_of(1005, '50') == 503
    assert engine.percent_of(1001, '50') == 501
    assert engine.percent_of(120000, '20.833333') == 25000


def test_discount_never_stacks_and_is_idempotent(cfg):
    once = engine.compute_payment(DEV_1200, 'cash', cfg)
    # Recalcular desde un desarrollo ya descontado no es posible: la entrada son precios de catálogo.
    assert engine.compute_payment(DEV_1200, 'cash', cfg) == once
    q = quote.compute_quote(quote.decode_state('b=sistema&m=crm,panel,bcv,reportes&d=auth,data&p=cash'), cfg)
    assert q['payment']['discountCents'] == 23920  # 23 % de $1.040
    assert q['developmentTotal'] * 100 == q['payment']['originalCents']  # el catálogo no se toca


def test_financed_plans_never_get_a_discount_even_if_cash_is_cheaper(cfg):
    for mode in ('m3', 'm6', 'm9'):
        assert engine.compute_payment(DEV_1200, mode, cfg)['discountPercent'] == '0'


def test_excluded_items_keep_full_price(cfg):
    c = {**cfg, 'cashDiscount': {**cfg['cashDiscount'], 'excludedIds': ['crm']}}
    p = engine.compute_payment(DEV_1200, 'cash', c)
    assert p['discountableCents'] == 102000 and p['discountCents'] == 23460


def test_recurring_costs_are_never_discounted_or_increased(cfg):
    for mode in ('cash', 'm3', 'm6', 'm9'):
        q = quote.compute_quote(quote.decode_state(f'b=tienda&m=whatsapp&d=auth,data&h=vps-superior&k=1&p={mode}'), cfg)
        assert (q['hostingMonthly'], q['maintenanceMonthly'], q['monthlyTotal']) == (35, 25, 60)


def test_chatbot_only_examples(cfg):
    cash = quote.compute_quote(quote.decode_state('b=chatbot-ia&p=cash'), cfg)
    assert (cash['developmentTotal'], cash['payment']['totalCents']) == (100, 7700)
    fin = quote.compute_quote(quote.decode_state('b=chatbot-ia&p=m3'), cfg)
    assert (fin['payment']['originalCents'], fin['payment']['totalCents'], fin['payment']['discountCents']) == (10000, 11000, 0)


# --- Estimación de consumo de IA --------------------------------------------------------------------------------

def test_usage_estimate_levels(cfg):
    assert [engine.estimate_chatbot_usage(n, cfg['chatbot'])['monthlyCents'] for n in (100, 500, 2000)] == [14, 70, 280]


def test_usage_depends_on_tokens_and_configurable_rates(cfg):
    ch = cfg['chatbot']
    base = engine.estimate_chatbot_usage(500, ch)['monthlyCents']
    assert engine.estimate_chatbot_usage(500, {**ch, 'inputTokensPerQuery': 6000})['monthlyCents'] > base
    assert engine.estimate_chatbot_usage(500, {**ch, 'priceInPerM': '0.30', 'priceOutPerM': '1.00'})['monthlyCents'] == 140
    withm = engine.estimate_chatbot_usage(2000, {**ch, 'marginPercent': '25', 'monthlyLimitUsd': '3'})
    assert withm['monthlyCents'] == 350 and withm['overLimit'] is True


def test_usage_is_separate_from_development_and_monthly_total(cfg):
    q = quote.compute_quote(quote.decode_state('b=chatbot-ia&u=high&p=cash'), cfg)
    assert q['usage']['monthlyCents'] == 280 and q['monthlyTotal'] == 0 and q['developmentTotal'] == 100


# --- Configuración en Django Admin como única fuente de verdad ------------------------------------------------

def test_defaults_seed_the_database_once():
    s = settings_row()
    assert (s.cash_discount_enabled, s.cash_discount_percent) == (True, Decimal(23))
    assert PaymentPlan.objects.count() == 3 and UsageTier.objects.count() == 4
    assert services.ensure_settings().pk == s.pk and CommercialSettings.objects.count() == 1


def test_admin_changes_flow_into_config_and_quotes():
    s = settings_row()
    s.cash_discount_percent = Decimal('30')
    s.save()
    plan = PaymentPlan.objects.get(mode_id='m3')
    plan.surcharge_percent, plan.installments = Decimal('12'), 4
    plan.save()
    cfg = services.current_config()
    assert cfg['cashDiscount']['percent'] == '30'
    assert cfg['plans'][0]['surchargePercent'] == '12' and cfg['plans'][0]['installments'] == 4
    q = quote.compute_quote(quote.decode_state('b=landing&p=cash'), cfg)
    assert q['payment']['discountCents'] == 5400  # 30 % de $180
    assert quote.compute_quote(quote.decode_state('b=landing&p=m3'), cfg)['payment']['installmentCount'] == 4


def test_discount_can_be_disabled():
    s = settings_row()
    s.cash_discount_enabled = False
    s.save()
    q = quote.compute_quote(quote.decode_state('b=landing&p=cash'))
    assert q['payment']['discountCents'] == 0 and q['payment']['totalCents'] == 18000


def test_every_change_creates_a_version_and_same_content_reuses_it():
    v1 = services.current_config()['version']
    assert services.current_config()['version'] == v1
    s = settings_row()
    s.cash_discount_percent = Decimal('40')
    s.save()
    v2 = services.current_config()['version']
    assert v2 > v1
    s.cash_discount_percent = Decimal('23')
    s.save()
    assert services.current_config()['version'] == v1  # mismo contenido, misma versión
    assert PricingVersion.objects.count() == 2


def test_historical_versions_keep_their_numbers():
    old = services.current_config()
    old_quote = quote.compute_quote(quote.decode_state('b=landing&p=cash'), old)
    s = settings_row()
    s.cash_discount_percent = Decimal('10')
    s.save()
    new = services.current_config()
    assert new['version'] != old['version']
    replay = quote.compute_quote(quote.decode_state('b=landing&p=cash'), services.config_for_version(old['version']))
    assert replay['payment'] == old_quote['payment'] and replay['payment']['totalCents'] == 13860
    assert quote.compute_quote(quote.decode_state('b=landing&p=cash'), new)['payment']['totalCents'] == 16200


# --- Validación administrativa: módulos excluidos del descuento ------------------------------------------------

def test_rule_blocks_discount_below_real_cost_unless_excluded():
    s = settings_row()
    rule = ModuleRule(settings=s, item_id='chatbot', min_implementation_cost=Decimal('80'))
    with pytest.raises(ValidationError) as exc:
        rule.full_clean()
    assert 'costo mínimo' in str(exc.value)
    rule.excluded_from_discount = True
    rule.full_clean()  # excluido del descuento: el mínimo ya no se viola
    rule.excluded_from_discount = False
    rule.min_implementation_cost = Decimal('50')
    rule.full_clean()  # $100 con 50 % = $50 cubre el mínimo


def test_rule_rejects_unknown_catalog_ids():
    with pytest.raises(ValidationError):
        ModuleRule(settings=settings_row(), item_id='no-existe').full_clean()


def test_raising_discount_is_blocked_if_it_breaks_an_existing_rule():
    s = settings_row()
    ModuleRule.objects.create(settings=s, item_id='chatbot', min_implementation_cost=Decimal('50'))
    s.cash_discount_percent = Decimal('60')
    with pytest.raises(ValidationError):
        s.full_clean()


def test_excluded_module_is_exposed_to_the_calculator():
    ModuleRule.objects.create(settings=settings_row(), item_id='chatbot', excluded_from_discount=True)
    cfg = services.current_config()
    assert cfg['cashDiscount']['excludedIds'] == ['chatbot']
    q = quote.compute_quote(quote.decode_state('b=chatbot-ia&p=cash'), cfg)
    assert q['payment']['discountCents'] == 0 and q['payment']['totalCents'] == 10000


def test_financing_and_discount_minimums():
    s = settings_row()
    s.financing_min_development = Decimal('150')
    s.cash_discount_min_development = Decimal('120')
    s.save()
    q = quote.compute_quote(quote.decode_state('b=chatbot-ia'))
    by = {p['modeId']: p for p in q['paymentOptions']}
    assert by['m3']['available'] is False and '$150' in by['m3']['unavailableReason']
    assert by['cash']['discountCents'] == 0
    big = {p['modeId']: p for p in quote.compute_quote(quote.decode_state('b=sistema')).get('paymentOptions')}
    assert big['m3']['available'] is True and big['cash']['discountCents'] > 0


def test_plan_installments_must_fit_the_term():
    plan = PaymentPlan(settings=settings_row(), mode_id='m3', term_months=3, surcharge_percent=10, initial_percent=40, installments=6, every_months=1)
    with pytest.raises(ValidationError):
        plan.clean()


# --- Tarifas de OpenRouter (red simulada) -----------------------------------------------------------------------

def _models_response(model, prompt, completion):
    req = httpx.Request('GET', 'https://openrouter.ai/api/v1/models')
    return httpx.Response(200, json={'data': [{'id': model, 'pricing': {'prompt': prompt, 'completion': completion}}]}, request=req)


def test_live_rates_are_stored_with_date_and_used(monkeypatch):
    s = settings_row()
    monkeypatch.setattr(rates.httpx, 'get', lambda url, timeout=None: _models_response(s.chatbot_model, '0.0000002', '0.0000008'))
    ok, _ = rates.refresh_rates()
    assert ok
    cfg = services.current_config()
    assert cfg['chatbot']['priceInPerM'] == '0.2' and cfg['chatbot']['priceOutPerM'] == '0.8'
    assert cfg['chatbot']['ratesSource'] == 'openrouter' and cfg['chatbot']['ratesUpdatedAt']
    assert engine.estimate_chatbot_usage(500, cfg['chatbot'])['monthlyCents'] == 100  # 500 conversaciones × 4 consultas × (1500 × 0,2 + 250 × 0,8) / 1e6 = $1,00


def test_rate_failure_keeps_fallback_and_is_recorded(monkeypatch):
    def boom(url, timeout=None):
        raise httpx.ConnectError('sin red')

    monkeypatch.setattr(rates.httpx, 'get', boom)
    ok, note = rates.refresh_rates()
    assert not ok and 'respaldo' in note
    cfg = services.current_config()
    assert cfg['chatbot']['ratesSource'] == 'fallback' and cfg['chatbot']['priceInPerM'] == '0.15' and cfg['chatbot']['ratesUpdatedAt'] is None


def test_unknown_model_falls_back(monkeypatch):
    monkeypatch.setattr(rates.httpx, 'get', lambda url, timeout=None: _models_response('otro/modelo', '0.1', '0.2'))
    assert rates.refresh_rates()[0] is False


def test_live_rates_can_be_turned_off(monkeypatch):
    s = settings_row()
    monkeypatch.setattr(rates.httpx, 'get', lambda url, timeout=None: _models_response(s.chatbot_model, '0.0000009', '0.000002'))
    rates.refresh_rates()
    s.refresh_from_db()
    s.use_live_rates = False
    s.save()
    assert services.current_config()['chatbot']['priceInPerM'] == '0.15'


def test_chatbot_rates_do_not_touch_the_advisor_budget(monkeypatch):
    """El chatbot de clientes y Angside AI Advisor no comparten tarifas ni presupuestos."""
    s = settings_row()
    s.fallback_price_in_per_m = Decimal('9')
    s.save()
    assert limits.estimate_cost(1_000_000, 0) == Decimal('0.15')


# --- API pública ----------------------------------------------------------------------------------------------

def test_config_endpoint_is_public_and_matches_admin(client):
    s = settings_row()
    s.cash_discount_percent = Decimal('45')
    s.save()
    resp = client.get('/api/commercial/config')
    assert resp.status_code == 200
    body = resp.json()
    assert body['cashDiscount']['percent'] == '45' and body['version'] == services.current_config()['version']
    assert [p['id'] for p in body['plans']] == ['m3', 'm6', 'm9']
    assert isinstance(body['chatbot']['priceInPerM'], str)  # decimales como texto: sin flotantes


REF = 'ANG-ABCD2345'


def _register(client, **extra):
    body = {'reference': REF, 'config': 'b=sistema&m=crm&d=auth,data&p=m6', **extra}
    return post(client, '/api/commercial/quotes', body)


def test_register_quote_recomputes_on_the_server(client):
    resp = _register(client, development_total=1, total=1)  # importes enviados por el navegador: se ignoran
    assert resp.status_code == 201
    saved = SavedQuote.objects.get()
    q = quote.compute_quote(quote.decode_state('b=sistema&m=crm&d=auth,data&p=m6'))
    assert saved.development_original == Decimal(q['payment']['originalCents']) / 100
    assert saved.development_total == Decimal(q['payment']['totalCents']) / 100
    assert saved.payment_mode == 'm6' and saved.pricing_version_id == services.current_config()['version']
    assert saved.breakdown['payment']['schedule'][0]['label'] == 'Inicial'


def test_register_quote_stores_no_personal_data(client):
    _register(client, name='Ana', phone='+58412', email='a@b.c')
    dump = json.dumps(SavedQuote.objects.values().get(), default=str)
    assert 'Ana' not in dump and '58412' not in dump and 'a@b.c' not in dump


def test_register_quote_is_idempotent_and_keeps_its_version(client):
    first = _register(client).json()
    s = settings_row()
    s.cash_discount_percent = Decimal('20')
    s.save()
    again = _register(client)
    assert again.status_code == 200 and again.json()['pricing_version'] == first['pricing_version']
    assert SavedQuote.objects.count() == 1


def test_register_quote_uses_the_version_the_visitor_saw(client):
    seen = services.current_config()
    s = settings_row()
    s.cash_discount_percent = Decimal('10')
    s.save()
    resp = post(client, '/api/commercial/quotes', {'reference': REF, 'config': 'b=landing&p=cash', 'version': seen['version']})
    body = resp.json()
    assert body['pricing_version'] == seen['version'] and body['development_total'] == 138.6 and body['is_latest'] is False


@pytest.mark.parametrize('payload', [
    {'reference': 'x', 'config': 'b=landing'},
    {'reference': REF, 'config': 'b=' + 'a' * 700},
    {'reference': REF, 'config': 'b=landing', 'version': 'uno'},
    {'reference': REF, 'config': 'm=bcv'},          # sin proyecto: incompleta
    {'reference': REF, 'config': 'b=tienda&m=facturacion&d=auth,data'},  # falta el plan de facturación
])
def test_register_quote_rejects_bad_input(client, payload):
    assert post(client, '/api/commercial/quotes', payload).status_code == 400
    assert SavedQuote.objects.count() == 0


def test_register_quote_is_rate_limited(client, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, 'quote_register_ip': (2, 3600)}
    codes = [post(client, '/api/commercial/quotes', {'reference': f'ANG-ABCDE{i}XYZ', 'config': 'b=landing'}).status_code for i in range(3)]
    assert codes == [201, 201, 429]


# --- Administración ------------------------------------------------------------------------------------------

def test_admin_pages_render_and_save_creates_a_version(client):
    user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw-12345-xyz')
    client.force_login(user)
    resp = client.get('/admin/commercial/commercialsettings/')
    assert resp.status_code == 200
    resp = client.get('/admin/commercial/commercialsettings/1/change/')
    assert resp.status_code == 200 and 'Descuento de contado' in resp.content.decode()
    for model in ('pricingversion', 'savedquote'):
        assert client.get(f'/admin/commercial/{model}/').status_code == 200


def test_admin_action_updates_rates_without_network(client, monkeypatch):
    user = get_user_model().objects.create_superuser('admin', 'a@example.com', 'pw-12345-xyz')
    client.force_login(user)
    settings_row()
    monkeypatch.setattr(rates.httpx, 'get', lambda url, timeout=None: _models_response(CommercialSettings.objects.get().chatbot_model, '0.0000003', '0.000001'))
    resp = client.post('/admin/commercial/commercialsettings/', {'action': 'update_rates', '_selected_action': [1]}, follow=True)
    assert resp.status_code == 200
    assert CommercialSettings.objects.get().live_price_in_per_m == Decimal('0.3')


# --- Asesor GLM: herramientas deterministas -----------------------------------------------------------------

def _propose(client, form, captcha, fake_ai, *options):
    data = create_session(client, form, captcha)
    evs = say(client, data, fake_ai, 'quiero cotizar',
              tool_round('classify_client', {'business_size': 'small'}, 'c1'),
              tool_round('propose_options', {'options': list(options)}, 'c2'),
              text_round('Aquí tienes.'))
    return data, cards_of(evs)


def test_cards_carry_payment_options_schedule_and_version(client, form, captcha, fake_ai):
    _, (card,) = _propose(client, form, captcha, fake_ai, opt('recommended', 'landing', ['bcv']))
    assert card['pricing_version'] == services.current_config()['version'] and card['payment_mode'] is None
    by = {o['mode']: o for o in card['payment_options']}
    assert by['cash']['total'] == 207.9 and by['cash']['savings'] == 62.1  # (180 + 90) × 23 %
    assert by['m9']['total'] == 326.25 and by['m9']['schedule'][0]['label'] == 'Inicial'
    assert sum(s['amount'] for s in by['m6']['schedule']) == pytest.approx(by['m6']['total'])
    assert Proposal.objects.get().pricing_version == card['pricing_version']


def test_propose_options_can_preselect_the_mode_and_chatbot_usage(client, form, captcha, fake_ai):
    o = opt('recommended', 'chatbot-ia')
    o.update(payment_mode_id='cash', chatbot_usage='medium')
    _, (card,) = _propose(client, form, captcha, fake_ai, o)
    assert card['payment_mode'] == 'cash' and card['development_total'] == 100
    assert card['ai_usage']['monthly'] == 0.7 and card['ai_usage']['conversations'] == 500
    assert 'config' in card and 'p=cash' in card['config'] and 'u=medium' in card['config']
    assert Proposal.objects.get().payment_mode == 'cash'


def test_model_cannot_pass_discounts_or_unknown_modes(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    bad = opt('recommended', 'landing')
    bad['discount_percent'] = 90
    evs = say(client, data, fake_ai, 'hola', tool_round('propose_options', {'options': [bad]}, 'c1'), text_round('ok'))
    assert not [e for e in evs if e['type'] == 'proposals'] and Proposal.objects.count() == 0
    o = opt('recommended', 'landing')
    o['payment_mode_id'] = 'm12'
    evs = say(client, data, fake_ai, 'hola', tool_round('propose_options', {'options': [o]}, 'c2'), text_round('ok'))
    assert Proposal.objects.count() == 0


def _tool_result(session_id, name):
    msgs = ChatSession.objects.get(pk=session_id).messages.filter(role='tool').order_by('-id')
    return json.loads(msgs.first().content)


def test_get_payment_options_returns_exact_amounts_and_budget_flags(client, form, captcha, fake_ai):
    data, _ = _propose(client, form, captcha, fake_ai, opt('recommended', 'landing', ['bcv']))
    say(client, data, fake_ai, 'cuánto es de contado y cuánto la inicial?',
        tool_round('get_payment_options', {'budget_usd': 250}, 'c3'), text_round('Listo.'))
    res = _tool_result(data['session_id'], 'get_payment_options')
    assert res['ok'] is True and res['presupuesto_del_cliente_usd'] == 250
    rows = {r['modalidad']: r for r in res['modalidades']}
    assert rows['cash']['total_desarrollo_usd'] == 207.9 and rows['cash']['ahorro_usd'] == 62.1
    assert rows['m3']['total_desarrollo_usd'] == 297 and rows['m3']['inicial_usd'] == 118.8
    assert rows['m3']['cuotas'] == '3 cuotas mensuales' and rows['m3']['cuota_usd'] == 59.4
    assert rows['m9']['cuotas'] == '3 cuotas trimestrales'
    assert rows['cash']['total_cabe_en_el_presupuesto'] is True and rows['m3']['total_cabe_en_el_presupuesto'] is False
    assert rows['m3']['inicial_cabe_en_el_presupuesto'] is True
    assert rows['m3']['descuento_de_contado'] == 'no aplica en planes financiados'


def test_get_payment_options_needs_a_proposal(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    say(client, data, fake_ai, 'cuánto cuesta?', tool_round('get_payment_options', {}, 'c1'), text_round('Aún no hay propuesta.'))
    assert _tool_result(data['session_id'], 'get_payment_options')['ok'] is False


def test_select_payment_mode_persists_and_updates_the_card(client, form, captcha, fake_ai):
    data, (card,) = _propose(client, form, captcha, fake_ai, opt('recommended', 'landing'))
    evs = say(client, data, fake_ai, 'pago a 6 meses', tool_round('select_payment_mode', {'mode': 'm6'}, 'c3'), text_round('Registrado.'))
    assert {'type': 'payment_mode', 'proposal_id': card['id'], 'mode': 'm6'} in evs
    assert Proposal.objects.get().payment_mode == 'm6'
    # Al reanudar la conversación la tarjeta muestra la modalidad elegida
    resumed = client.get(f"/api/ai/sessions/{data['session_id']}", HTTP_AUTHORIZATION=f"Bearer {data['token']}").json()
    event = next(m['event'] for m in resumed['messages'] if m['role'] == 'event')
    assert event['proposals'][0]['payment_mode'] == 'm6'
    # Un plan financiado jamás lleva descuento
    assert next(o for o in event['proposals'][0]['payment_options'] if o['mode'] == 'm6')['discount'] == 0


def test_select_payment_mode_rejects_unknown_or_unavailable_modes(client, form, captcha, fake_ai):
    s = settings_row()
    s.financing_min_development = Decimal('500')
    s.save()
    data, _ = _propose(client, form, captcha, fake_ai, opt('recommended', 'landing'))
    say(client, data, fake_ai, 'a 3 meses', tool_round('select_payment_mode', {'mode': 'm3'}, 'c3'), text_round('No se pudo.'))
    assert _tool_result(data['session_id'], 'select_payment_mode')['ok'] is False
    assert Proposal.objects.get().payment_mode == ''
    say(client, data, fake_ai, 'a 12 meses', tool_round('select_payment_mode', {'mode': 'm12'}, 'c4'), text_round('No.'))
    assert _tool_result(data['session_id'], 'select_payment_mode')['ok'] is False


def test_custom_payment_plan_is_recorded_and_sent_to_a_human(client, form, captcha, fake_ai):
    data, _ = _propose(client, form, captcha, fake_ai, opt('recommended', 'landing'))
    evs = say(client, data, fake_ai, 'puedo pagarlo en 12 cuotas con 20% de inicial?',
              tool_round('request_payment_plan_negotiation', {'note': 'Quiere 12 cuotas', 'desired_months': 12, 'desired_initial_percent': 20}, 'c3'),
              text_round('Lo derivé con una persona del equipo.'))
    assert {'type': 'contact_requested'} in evs and {'type': 'negotiation'} in evs
    lead = Lead.objects.get()
    assert lead.negotiation_requested and lead.status == Lead.Status.CONTACT_REQUESTED
    assert '12' in lead.negotiation_reason and 'inicial deseada' in lead.notes
    assert Proposal.objects.get().payment_mode == ''  # no se cambió nada por su cuenta


def test_visitor_can_change_the_mode_from_the_card(client, form, captcha, fake_ai):
    data, (card,) = _propose(client, form, captcha, fake_ai, opt('recommended', 'landing'))
    url = f"/api/ai/sessions/{data['session_id']}/proposals/{card['id']}/payment-mode"
    ok = post(client, url, {'mode': 'cash'}, token=data['token'])
    assert ok.status_code == 200 and ok.json()['proposal']['payment_mode'] == 'cash'
    assert post(client, url, {'mode': 'm12'}, token=data['token']).status_code == 400
    assert post(client, url, {'mode': 'cash'}).status_code == 401
    assert post(client, f"/api/ai/sessions/{data['session_id']}/proposals/99999/payment-mode", {'mode': 'cash'}, token=data['token']).status_code == 404


def test_payment_tools_have_no_money_fields():
    from angside_ai.tools import tool_definitions

    names = {t['function']['name']: t['function']['parameters']['properties'] for t in tool_definitions()}
    for tool in ('get_payment_options', 'select_payment_mode', 'request_payment_plan_negotiation'):
        assert not any(w in k for k in names[tool] for w in ('discount', 'price', 'total', 'cost', 'percent_off')), tool


# --- Guardia y prompt ------------------------------------------------------------------------------------------

def _session_with_card(client, form, captcha, fake_ai):
    data, _ = _propose(client, form, captcha, fake_ai, opt('recommended', 'landing', ['bcv']))
    return ChatSession.objects.get(pk=data['session_id'])


def test_guard_allows_real_payment_amounts_and_cash_discount_wording(client, form, captcha, fake_ai):
    session = _session_with_card(client, form, captcha, fake_ai)
    text = 'De contado pagas $207,90 USD con 23 % de descuento y ahorras $62,10. A 3 meses la inicial es $118,80 y cada cuota $59,40.'
    found = guard.unverified(text, session)
    assert found == {'amounts': [], 'discount_words': [], 'percents': []}


def test_guard_flags_invented_amounts_percentages_and_other_discounts(client, form, captcha, fake_ai):
    session = _session_with_card(client, form, captcha, fake_ai)
    found = guard.unverified('Te hago 70 % de descuento de contado, queda en $77 USD.', session)
    assert found['percents'] == [70.0] and 77 in found['amounts']
    assert guard.unverified('Tienes una promoción especial del plan financiado.', session)['discount_words']
    assert guard.unverified('Con el plan financiado hay un descuento adicional.', session)['discount_words']  # fuera de "contado"
    assert guard.unverified('Pagando a 6 meses el incremento es de 33 %.', session)['percents'] == [33.0]


def test_guard_accepts_percentages_of_the_pricing_version_used_by_the_card(client, form, captcha, fake_ai):
    session = _session_with_card(client, form, captcha, fake_ai)
    s = settings_row()
    s.cash_discount_percent = Decimal('20')
    s.save()
    assert guard.unverified('Esa propuesta tiene 23 % de descuento de contado.', session)['percents'] == []  # versión de la tarjeta
    assert guard.unverified('Ahora el descuento de contado es 20 %.', session)['percents'] == []


def test_system_prompt_reads_payment_rules_from_admin_config(client, form, captcha, fake_ai):
    lead = Lead.objects.create(name='A', business='B', email='a@b.co', sector='s', need='n', privacy_version='1')
    text = prompts.build_system_prompt(lead)
    for needle in ('Contado (cash): 23 % de descuento', '+10 % sobre el desarrollo', '+20,833333 % sobre el desarrollo', '3 cuotas trimestrales',
                   'get_payment_options', 'request_payment_plan_negotiation', 'CHATBOT EMPRESARIAL CON IA', 'NO es Angside AI Advisor'):
        assert needle in text, needle
    s = settings_row()
    s.cash_discount_percent = Decimal('35')
    s.save()
    assert 'Contado (cash): 35 % de descuento' in prompts.build_system_prompt(lead)
    s.cash_discount_enabled = False
    s.save()
    assert 'por ahora no hay descuento de contado' in prompts.build_system_prompt(lead)


# --- Chatbot en el catálogo ----------------------------------------------------------------------------------

def test_chatbot_catalog_entries():
    c = quote.catalog()
    mod = quote.module_by_id('chatbot')
    assert (mod['price'], mod['from'], mod['category']) == (100, True, 'ia')
    assert len(mod['scope']['included']) == 7 and 'Integración oficial con WhatsApp' in mod['scope']['excluded']
    base = quote.base_by_id('chatbot-ia')
    assert base['price'] == 100 and base['includes'] == ['chatbot']
    assert any(cat['id'] == 'ia' for cat in c['categories'])


def test_chatbot_cannot_be_charged_twice():
    state = quote.normalize_state({**quote.initial_state(), 'baseId': 'chatbot-ia', 'moduleIds': ['chatbot']})
    assert state['moduleIds'] == []
    q = quote.compute_quote(state)
    assert q['developmentTotal'] == 100
