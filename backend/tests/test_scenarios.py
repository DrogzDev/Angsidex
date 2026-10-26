"""
Conversaciones simuladas del asistente comercial. El modelo se reemplaza por un guion de herramientas (lo que haría GLM),
y se comprueba que los precios, la clasificación, la complejidad y el CRM coinciden EXACTAMENTE con el motor de cotización.
"""
import json

import pytest

from angside_ai import complexity, quote
from angside_ai.models import ChatSession
from leads.models import Lead, Proposal

from .conftest import text_round, tool_round
from .test_api import URL, create_session, events, msg_url, post

pytestmark = pytest.mark.django_db


def say(client, data, fake_ai, user_text, *rounds):
    """Un turno: el visitante escribe y el 'modelo' responde con las rondas indicadas (herramientas y/o texto)."""
    fake_ai.rounds = list(rounds)
    fake_ai.payloads.clear()
    return events(post(client, msg_url(data), {'message': user_text}, token=data['token']))


def cards_of(evs):
    return next(e for e in evs if e['type'] == 'proposals')['proposals']


def engine_total(config: str) -> dict:
    """Lo que el motor de cotización dice para esa configuración (fuente de verdad)."""
    return quote.compute_quote(quote.decode_state(config))


def assert_matches_engine(card):
    q = engine_total(card['config'])
    assert card['development_total'] == q['developmentTotal']
    assert card['payments'] == q['payments']
    assert card['monthly']['total'] == q['monthlyTotal']
    assert card['monthly']['hosting'] == q['hostingMonthly']
    assert card['monthly']['billing'] == q['billingMonthly']
    assert sum(f['price'] for f in card['features']) == q['developmentTotal']


def opt(tier, base, modules=(), hosting='externo', plan=None, maintenance=False, custom=(), benefits=()):
    o = {'tier': tier, 'base_id': base, 'module_ids': list(modules), 'hosting_id': hosting, 'maintenance': maintenance}
    if plan:
        o['billing_plan_id'] = plan
    if custom:
        o['custom_items'] = list(custom)
    if benefits:
        o['benefits'] = [{'feature_id': f, 'benefit': b} for f, b in benefits]
    return o


# 1 ---------------------------------------------------------------------------------------------------------------
def test_1_emprendedor_con_150_dolares(client, form, captcha, fake_ai):
    form.update(budget_range='lt200', need='Quiero que mis clientes me escriban y me encuentren en internet.', business='Uñas Ana')
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'Tengo como 150 dólares para empezar',
        tool_round('classify_client', {'business_size': 'small', 'size_reason': 'emprendedora individual', 'budget_stated_usd': 150}, 'c1'),
        tool_round('propose_options', {'options': [opt('essential', 'automatizacion'), opt('recommended', 'landing')]}, 'c2'),
        text_round('Con tu presupuesto la opción esencial es la que cabe; la recomendada lo supera un poco.'),
    )
    ess, rec = cards_of(evs)
    assert (ess['development_total'], rec['development_total']) == (120, 180)
    assert ess['within_budget'] is True and rec['within_budget'] is False
    for c in (ess, rec):
        assert_matches_engine(c)
        assert c['timeline'] == 'Pendiente de evaluación'
    lead = Lead.objects.get()
    assert lead.business_size == 'small' and lead.budget_stated_usd == 150 and lead.budget_ceiling_usd == 150
    assert lead.complexity in ('basic', 'intermediate') and lead.budget_calculated_usd == 180


# 2 ---------------------------------------------------------------------------------------------------------------
def test_2_hamburgueseria_gestion_de_pedidos(client, form, captcha, fake_ai):
    form.update(business='Burger Point', sector='Restaurante', need='Recibo pedidos por WhatsApp y se me pierden. Quiero ordenarlos.')
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'Somos 4 personas, vendemos unas 80 hamburguesas diarias',
        tool_round('classify_client', {'business_size': 'small', 'signals': {'users_estimate': 4, 'monthly_transactions_estimate': 2400}}, 'c1'),
        tool_round('propose_options', {'options': [
            opt('essential', 'tienda', hosting='vps-basico', benefits=[('pedidos', 'Ordena cada pedido en un solo lugar y evita que se pierdan mensajes.')]),
            opt('recommended', 'tienda', ['whatsapp', 'notificaciones'], 'vps-basico'),
            opt('complete', 'tienda', ['whatsapp', 'notificaciones', 'reportes', 'reservas'], 'vps-basico'),
        ]}, 'c2'),
        text_round('Te recomiendo la del medio: ordena pedidos y avisa por WhatsApp.'),
    )
    ess, rec, comp = cards_of(evs)
    assert [c['development_total'] for c in (ess, rec, comp)] == [550, 790, 1060]
    assert comp['development_from'] is False and ess['development_from'] is False
    assert all(c['monthly']['total'] == 15 for c in (ess, rec, comp))
    for c in (ess, rec, comp):
        assert_matches_engine(c)
    assert [c['tier'] for c in (ess, rec, comp)] == ['essential', 'recommended', 'complete']
    ped = next(f for f in ess['features'] if f['id'] == 'pedidos')
    assert ped['kind'] == 'included' and 'pedido' in ped['benefit'].lower()
    lead = Lead.objects.get()
    assert lead.budget_calculated_usd == 790  # la recomendada es la referencia
    assert 'Gestión de pedidos' in lead.recommended_features
    assert Proposal.objects.filter(lead=lead).count() == 3


# 3 ---------------------------------------------------------------------------------------------------------------
def test_3_tienda_de_repuestos_con_inventario_y_facturacion(client, form, captcha, fake_ai):
    form.update(business='Repuestos El Gato', sector='Autopartes', need='Necesito controlar inventario de repuestos y cobrar en línea.', budget_range='1000-3000')
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'Tenemos unos 3000 productos y facturamos todo',
        tool_round('classify_client', {'business_size': 'medium', 'signals': {'users_estimate': 6}}, 'c1'),
        tool_round('propose_options', {'options': [
            opt('recommended', 'sistema', ['inventario', 'reservas', 'facturacion'], 'vps-basico', plan='pymes'),
        ]}, 'c2'),
        text_round('Esta cubre inventario, reservas y facturación digital.'),
    )
    (card,) = cards_of(evs)
    assert card['development_total'] == 650 + 160 + 150 + 180
    assert card['development_from'] is False
    assert card['monthly']['billing'] == 30 and card['monthly']['total'] == 15 + 30
    assert any('Facturación digital Pymes' in l['label'] for l in card['monthly_lines'])
    assert card['complexity'] == 'advanced'  # sistema(3) + 3 módulos(1) + 2 integraciones(2) + 6 usuarios(1) = 7
    assert any('SENIAT' in n for n in card['notices'])
    assert card['within_budget'] is True and card['budget_ceiling'] == 3000
    assert_matches_engine(card)


# 4 ---------------------------------------------------------------------------------------------------------------
def test_4_empresa_mediana_con_varios_empleados(client, form, captcha, fake_ai):
    form.update(business='Distribuidora Andes', sector='Distribución', need='Varios empleados cargan pedidos y inventario en Excel.')
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'Somos 12 personas, con roles distintos. Vendedores, almacén y administración',
        tool_round('classify_client', {'business_size': 'medium', 'signals': {'users_estimate': 12, 'process_complexity': 'medium'}, 'needs_summary': 'Pedidos e inventario en Excel con varios roles'}, 'c1'),
        tool_round('propose_options', {'options': [
            opt('essential', 'sistema', ['inventario', 'excel']),
            opt('recommended', 'sistema', ['inventario', 'excel', 'roles', 'reportes']),
        ]}, 'c2'),
        text_round('Con roles y reportes cada área ve solo lo suyo.'),
    )
    ess, rec = cards_of(evs)
    assert (ess['development_total'], rec['development_total']) == (650 + 160 + 100, 650 + 160 + 100 + 150 + 120)
    assert rec['complexity'] == 'advanced' and ess['complexity'] == 'intermediate'
    assert 'Mediana empresa' in next(e for e in evs if e['type'] == 'proposals')['profile']['size_label']
    lead = Lead.objects.get()
    assert lead.business_size == 'medium' and lead.needs_summary.startswith('Pedidos e inventario')
    assert lead.signals['users_estimate'] == 12
    assert_matches_engine(ess), assert_matches_engine(rec)


# 5 ---------------------------------------------------------------------------------------------------------------
def test_5_empresa_con_cinco_sucursales(client, form, captcha, fake_ai):
    form.update(business='Farmacias Unidas', sector='Farmacia', need='Cinco sucursales que necesitan coordinar inventario y ventas.', budget_range='gt3000')
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'Tenemos 5 sucursales, unos 40 usuarios y necesitamos auditoría de cambios',
        tool_round('classify_client', {'business_size': 'large', 'signals': {'branches': 5, 'users_estimate': 40, 'special_audit': True}}, 'c1'),
        tool_round('propose_options', {'options': [
            opt('recommended', 'sistema', ['inventario', 'roles', 'reportes', 'auditoria', 'facturacion'], 'vps-superior', plan='gold',
                custom=['Sincronización de inventario en tiempo real entre sucursales']),
        ]}, 'c2'),
        text_round('La parte multi-sucursal requiere evaluación; lo demás sí está cotizado.'),
    )
    (card,) = cards_of(evs)
    assert card['complexity'] == 'custom'
    assert card['requires_custom_quote'] and card['custom_quote_text'] == 'Requiere cotización personalizada'
    assert card['custom_items'] == ['Sincronización de inventario en tiempo real entre sucursales']
    # Solo se cotiza lo que existe en el catálogo; el desarrollo a medida no suma ningún monto inventado.
    assert card['development_total'] == 650 + 160 + 150 + 120 + 100 + 180
    assert not any('Sincronización' in f['label'] for f in card['features'])
    assert card['monthly']['billing'] == 55
    assert Lead.objects.get().complexity == 'custom' and Lead.objects.get().business_size == 'large'
    assert Proposal.objects.get().requires_custom_quote is True
    assert_matches_engine(card)


# 6 ---------------------------------------------------------------------------------------------------------------
def test_6_cliente_sin_presupuesto_definido(client, form, captcha, fake_ai):
    form.update(budget_range='undefined', need='Quiero vender mis artesanías por internet, no sé cuánto cuesta.')
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'La verdad no sé cuánto debería gastar',
        tool_round('classify_client', {'business_size': 'small'}, 'c1'),
        tool_round('propose_options', {'options': [opt('essential', 'catalogo'), opt('recommended', 'tienda'), opt('complete', 'tienda', ['reservas', 'whatsapp'])]}, 'c2'),
        text_round('Te muestro tres caminos para que compares.'),
    )
    cards = cards_of(evs)
    assert [c['development_total'] for c in cards] == [280, 550, 850]
    assert all(c['within_budget'] is None and c['budget_ceiling'] is None for c in cards)
    assert Lead.objects.get().budget_ceiling_usd is None
    for c in cards:
        assert_matches_engine(c)


# 7 ---------------------------------------------------------------------------------------------------------------
def test_7_cliente_que_quiere_negociar(client, form, captcha, fake_ai):
    form.update(budget_range='500-1000')
    data = create_session(client, form, captcha)
    say(
        client, data, fake_ai, 'Quiero una tienda con WhatsApp y avisos',
        tool_round('classify_client', {'business_size': 'small'}, 'c1'),
        tool_round('propose_options', {'options': [opt('essential', 'tienda'), opt('recommended', 'tienda', ['whatsapp', 'notificaciones'])]}, 'c2'),
        text_round('Aquí tienes dos opciones.'),
    )
    evs = say(
        client, data, fake_ai, 'Me parece caro, yo tenía pensado 500 dólares',
        tool_round('record_negotiation', {'reason': 'Considera elevado el presupuesto', 'ideal_budget_usd': 500}, 'n1'),
        tool_round('record_objection', {'category': 'price', 'detail': 'Esperaba pagar unos 500 USD'}, 'n2'),
        tool_round('propose_options', {'options': [opt('adjusted', 'catalogo', ['whatsapp'])]}, 'n3'),
        text_round('Reduje el alcance: catálogo con WhatsApp. Si quieres, una persona del equipo puede revisar tu caso.'),
    )
    (adj,) = cards_of(evs)
    assert adj['tier'] == 'adjusted' and adj['name'] == 'Ajustada a tu presupuesto'
    assert adj['development_total'] == 280 + 150 and adj['within_budget'] is True
    assert_matches_engine(adj)
    lead = Lead.objects.get()
    assert lead.negotiation_requested and lead.status == 'negotiating'
    assert lead.negotiation_initial_budget == 790  # la recomendada anterior
    assert lead.negotiation_ideal_budget == 500 and 'elevado' in lead.negotiation_reason
    assert lead.objections[0]['category'] == 'price'
    assert any(e['type'] == 'negotiation' for e in evs)
    assert Proposal.objects.filter(lead=lead).values_list('round', flat=True).distinct().count() == 2
    assert [e for e in evs if e['type'] == 'price_notice'] == []


# 8 ---------------------------------------------------------------------------------------------------------------
def test_8_cliente_que_desconfia_de_contratar_un_desarrollador(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'No sé, me da miedo pagar y que el programador se pierda o me quede amarrado',
        tool_round('record_objection', {'category': 'trust', 'detail': 'Teme que el programador desaparezca'}, 'o1'),
        tool_round('record_objection', {'category': 'ownership', 'detail': 'Teme quedar amarrado al desarrollador'}, 'o2'),
        text_round('Se paga en dos partes: una para arrancar y otra cuando ya ves todo funcionando. Y el sistema es 100 % tuyo.'),
    )
    assert not any(e['type'] == 'proposals' for e in evs)
    assert [o['category'] for o in Lead.objects.get().objections] == ['trust', 'ownership']
    system = fake_ai.payloads[0]['json']['messages'][0]['content']
    assert '100 % del cliente' in system and 'otros programadores' in system and 'dos partes' in system
    assert not [e for e in evs if e['type'] == 'price_notice']  # no hay montos inventados


# 9 ---------------------------------------------------------------------------------------------------------------
def test_9_funcionalidad_inexistente_en_el_cotizador(client, form, captcha, fake_ai):
    form.update(business='Textiles Sol', need='Necesito un sistema de nómina para pagar a mis 30 empleados.')
    data = create_session(client, form, captcha)
    evs = say(
        client, data, fake_ai, 'Lo que más necesito es la nómina de mis empleados',
        tool_round('classify_client', {'business_size': 'medium', 'signals': {'users_estimate': 30, 'needs_custom_development': True}}, 'c1'),
        tool_round('propose_options', {'options': [opt('recommended', 'sistema', ['roles'], custom=['Módulo de nómina de empleados'])]}, 'c2'),
        text_round('La nómina no está en el cotizador, así que esa parte requiere una cotización personalizada.'),
    )
    (card,) = cards_of(evs)
    assert card['requires_custom_quote'] and card['complexity'] == 'custom'
    assert card['development_total'] == 650 + 150  # solo lo que existe en el catálogo
    assert 'nómina' in card['custom_items'][0].lower()
    assert all('nómina' not in f['label'].lower() for f in card['features'])
    assert_matches_engine(card)


# --- No descuentos, no precios por tamaño, no precios en argumentos ----------------------------------------------
def propose_result(client, data, fake_ai, option):
    evs = say(client, data, fake_ai, 'arma la propuesta', tool_round('propose_options', {'options': [option]}, 'p'), text_round('Listo.'))
    return next((e for e in evs if e['type'] == 'proposals'), None), evs


def test_price_is_independent_of_company_size(client, form, captcha, fake_ai, settings):
    settings.AI_MAX_PROPOSAL_ROUNDS = 10
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, 'message_session': (100, 60)}
    data = create_session(client, form, captcha)
    option = opt('recommended', 'sistema', ['inventario', 'roles'], 'vps-basico')
    totals = []
    for size in ('small', 'medium', 'large'):
        say(client, data, fake_ai, f'somos {size}', tool_round('classify_client', {'business_size': size}, 'c'), text_round('ok'))
        ev, _ = propose_result(client, data, fake_ai, option)
        totals.append((ev['proposals'][0]['development_total'], ev['proposals'][0]['monthly']['total'], ev['proposals'][0]['payments']))
    assert len(set(map(str, totals))) == 1 and totals[0][0] == 650 + 160 + 150


@pytest.mark.parametrize('forbidden', [
    {'discount_percent': 20}, {'price': 100}, {'total_usd': 90}, {'description': 'oferta'},
])
def test_options_reject_price_and_discount_arguments(client, form, captcha, fake_ai, forbidden):
    data = create_session(client, form, captcha)
    ev, evs = propose_result(client, data, fake_ai, {**opt('recommended', 'landing'), **forbidden})
    assert ev is None and Proposal.objects.count() == 0
    tool_msg = next(m for m in fake_ai.payloads[1]['json']['messages'] if m['role'] == 'tool')
    assert json.loads(tool_msg['content'])['ok'] is False


def test_classify_client_rejects_price_arguments(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    say(client, data, fake_ai, 'hola', tool_round('classify_client', {'business_size': 'large', 'discount': 30}, 'c'), text_round('ok'))
    tool_msg = next(m for m in fake_ai.payloads[1]['json']['messages'] if m['role'] == 'tool')
    assert json.loads(tool_msg['content'])['ok'] is False
    assert Lead.objects.get().business_size == ''


def test_tool_schemas_have_no_price_or_discount_fields():
    """Ninguna herramienta tiene campos para precios, totales ni descuentos (se revisan nombres de campos, no textos)."""
    from angside_ai.tools import tool_definitions

    def field_names(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == 'properties' and isinstance(v, dict):
                    yield from v.keys()
                yield from field_names(v)
        elif isinstance(node, list):
            for v in node:
                yield from field_names(v)

    names = {n.lower() for n in field_names(tool_definitions())}
    assert 'options' in names and 'business_size' in names
    for n in names:
        assert not any(w in n for w in ('discount', 'descuento', 'price', 'precio', 'total', 'cost')), n
    # El único monto que el cliente puede aportar es su presupuesto, que no cambia ningún precio.
    assert {'budget_stated_usd', 'ideal_budget_usd'} <= names


def test_benefits_with_numbers_or_discounts_are_dropped(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    ev, _ = propose_result(client, data, fake_ai, opt('recommended', 'tienda', ['bcv'], benefits=[
        ('bcv', 'Te da un 30% de descuento gratis'), ('tienda', 'Vende 24/7 sin depender de mensajes.'),
    ]))
    feats = {f['id']: f for f in ev['proposals'][0]['features']}
    assert feats['bcv']['benefit'] == quote.module_by_id('bcv')['description']  # el texto con descuento se descartó
    assert feats['tienda']['benefit'] == 'Vende 24/7 sin depender de mensajes.'


def test_unknown_benefit_ids_are_ignored(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    ev, _ = propose_result(client, data, fake_ai, opt('essential', 'landing', benefits=[('inexistente', 'texto')]))
    assert ev['proposals'][0]['development_total'] == 180


def test_tier_order_and_duplicates_are_validated(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    bad_order = {'options': [opt('essential', 'tienda', ['bcv']), opt('recommended', 'landing')]}
    evs = say(client, data, fake_ai, 'x', tool_round('propose_options', bad_order, 'a'), text_round('ok'))
    assert not any(e['type'] == 'proposals' for e in evs)
    dup = {'options': [opt('essential', 'landing'), opt('essential', 'catalogo')]}
    evs = say(client, data, fake_ai, 'y', tool_round('propose_options', dup, 'b'), text_round('ok'))
    assert not any(e['type'] == 'proposals' for e in evs) and Proposal.objects.count() == 0


def test_billing_plan_required_with_facturacion(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    ev, _ = propose_result(client, data, fake_ai, opt('recommended', 'sistema', ['facturacion']))
    assert ev is None
    ev, _ = propose_result(client, data, fake_ai, opt('recommended', 'sistema', ['facturacion'], plan='emprendedor'))
    assert ev['proposals'][0]['monthly']['billing'] == 20


def test_dependencies_are_shown_as_lines(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    ev, _ = propose_result(client, data, fake_ai, opt('recommended', 'corporativa', ['crm']))
    card = ev['proposals'][0]
    assert any(f['kind'] == 'dependency' and f['id'] == 'data' for f in card['features'])
    assert card['development_total'] == 350 + 180 + 100
    assert_matches_engine(card)


def test_max_proposal_rounds(client, form, captcha, fake_ai, settings):
    settings.AI_MAX_PROPOSAL_ROUNDS = 1
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, 'message_session': (100, 60)}
    data = create_session(client, form, captcha)
    assert propose_result(client, data, fake_ai, opt('essential', 'landing'))[0]
    assert propose_result(client, data, fake_ai, opt('essential', 'catalogo'))[0] is None


# --- Guardia de montos inventados ---------------------------------------------------------------------------------
def test_guard_warns_about_invented_prices_and_discounts(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    evs = say(client, data, fake_ai, 'cuánto cuesta una landing?', text_round('Una landing te sale en $99 USD, y te hago 20% de descuento.'))
    notice = next(e for e in evs if e['type'] == 'price_notice')
    assert 'descuentos' in notice['message']
    assert ChatSession.objects.get().messages.filter(meta__has_key='guard').exists()


@pytest.mark.parametrize('text,flagged', [
    ('No manejamos descuentos, pero podemos reducir el alcance.', False),
    ('Por política no ofrecemos descuentos ni promociones.', False),
    ('Sin descuentos, el precio es el del cotizador.', False),
    ('Te hago un descuento especial.', True),
    ('No te preocupes. Tengo una promoción para ti.', True),
    ('Hay una oferta especial esta semana.', True),
])
def test_guard_discount_words_respect_negation(text, flagged):
    from angside_ai.guard import offered_discounts
    assert bool(offered_discounts(text)) is flagged


def test_guard_accepts_catalog_and_calculated_amounts(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    evs = say(client, data, fake_ai, 'cuánto cuesta una landing?', text_round('Una landing parte desde $180 USD y el hosting básico es $15 al mes.'))
    assert not any(e['type'] == 'price_notice' for e in evs)


def test_guard_accepts_amounts_the_visitor_said(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    evs = say(client, data, fake_ai, 'Tengo $320 dólares', text_round('Entiendo, con $320 USD podemos ver la mejor opción.'))
    assert not any(e['type'] == 'price_notice' for e in evs)


def test_guard_marker_is_not_sent_back_to_the_model(client, form, captcha, fake_ai, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, 'message_session': (100, 60)}
    data = create_session(client, form, captcha)
    say(client, data, fake_ai, 'hola', text_round('Te lo dejo en $77 USD.'))
    say(client, data, fake_ai, 'sigue', text_round('ok'))
    sent = fake_ai.payloads[0]['json']['messages']
    assert all(not (m['role'] == 'assistant' and not m.get('content') and not m.get('tool_calls')) for m in sent)


# --- Perfil editable, solicitar propuesta, reanudar -------------------------------------------------------------------
def patch(client, url, data, token):
    return client.patch(url, data=json.dumps(data), content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {token}')


def test_client_can_correct_size_without_changing_prices(client, form, captcha, fake_ai, settings):
    settings.RATE_LIMITS = {**settings.RATE_LIMITS, 'message_session': (100, 60)}
    data = create_session(client, form, captcha)
    option = opt('recommended', 'tienda', ['bcv'])
    before, _ = propose_result(client, data, fake_ai, option)
    resp = patch(client, f"/api/ai/sessions/{data['session_id']}/profile", {'business_size': 'large'}, data['token'])
    assert resp.status_code == 200 and resp.json()['profile']['size'] == 'large' and resp.json()['profile']['size_confirmed']
    # La IA intenta reclasificar: se respeta la corrección del cliente.
    say(client, data, fake_ai, 'hola', tool_round('classify_client', {'business_size': 'small'}, 'c'), text_round('ok'))
    assert Lead.objects.get().business_size == 'large'
    after, _ = propose_result(client, data, fake_ai, option)
    assert after['proposals'][0]['development_total'] == before['proposals'][0]['development_total'] == 640
    assert patch(client, f"/api/ai/sessions/{data['session_id']}/profile", {'business_size': 'gigante'}, data['token']).status_code == 400
    assert patch(client, f"/api/ai/sessions/{data['session_id']}/profile", {'business_size': 'small'}, 'mal').status_code == 401


def test_request_proposal_marks_it_and_is_scoped_to_session(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    ev, _ = propose_result(client, data, fake_ai, opt('recommended', 'landing'))
    pid = ev['proposals'][0]['id']
    url = f"/api/ai/sessions/{data['session_id']}/request-contact"
    assert post(client, url, {'proposal_id': pid}, token=data['token']).status_code == 200
    p = Proposal.objects.get(pk=pid)
    assert p.requested and Lead.objects.get().status == 'contact_requested' and 'Recomendada' in Lead.objects.get().notes
    assert post(client, url, {'proposal_id': 99999}, token=data['token']).status_code == 404
    other = create_session(client, {**form, 'email': 'otro@example.com', 'turnstile_token': 't2'}, captcha)
    assert post(client, f"/api/ai/sessions/{other['session_id']}/request-contact", {'proposal_id': pid}, token=other['token']).status_code == 404


def test_session_resume_restores_cards_and_profile(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    say(client, data, fake_ai, 'hola', tool_round('classify_client', {'business_size': 'small'}, 'c'),
        tool_round('propose_options', {'options': [opt('essential', 'landing'), opt('recommended', 'corporativa')]}, 'p'), text_round('Mira las opciones.'))
    resp = client.get(f"/api/ai/sessions/{data['session_id']}", HTTP_AUTHORIZATION=f"Bearer {data['token']}").json()
    kinds = [m['role'] for m in resp['messages']]
    assert 'event' in kinds and kinds.index('event') > kinds.index('user')
    event = next(m['event'] for m in resp['messages'] if m['role'] == 'event')
    assert [p['development_total'] for p in event['proposals']] == [180, 350]
    assert resp['profile']['size'] == 'small'


def test_discovery_prompt_includes_form_data_and_rules(client, form, captcha, fake_ai):
    data = create_session(client, form, captcha)
    say(client, data, fake_ai, 'hola', text_round('ok'))
    system = fake_ai.payloads[0]['json']['messages'][0]['content']
    assert 'NO vuelvas a preguntar' in system and 'Panadería La Espiga' in system and '$200–$500' in system
    assert 'UNA pregunta a la vez' in system and 'tier adjusted' in system and 'ÚNICO descuento' in system and 'MODALIDADES DE PAGO' in system
    greeting = data['messages'][0]['content']
    assert 'qué te gustaría mejorar con una página web o un sistema' in greeting


# --- Complejidad (unitarias) --------------------------------------------------------------------------------------
@pytest.mark.parametrize('state,signals,custom,expected', [
    ({'baseId': 'landing', 'moduleIds': []}, {}, None, 'basic'),
    ({'baseId': 'tienda', 'moduleIds': []}, {}, None, 'basic'),
    ({'baseId': 'tienda', 'moduleIds': ['whatsapp', 'notificaciones']}, {}, None, 'intermediate'),
    ({'baseId': 'sistema', 'moduleIds': ['inventario', 'reservas', 'facturacion']}, {}, None, 'intermediate'),
    ({'baseId': 'sistema', 'moduleIds': ['inventario', 'reservas', 'facturacion', 'roles']}, {}, None, 'advanced'),
    ({'baseId': 'landing', 'moduleIds': []}, {'branches': 4}, None, 'custom'),
    ({'baseId': 'landing', 'moduleIds': []}, {'special_availability': True}, None, 'custom'),
    ({'baseId': 'landing', 'moduleIds': []}, {'existing_systems_integration': True}, None, 'custom'),
    ({'baseId': 'landing', 'moduleIds': []}, {}, ['algo a medida'], 'custom'),
])
def test_complexity_levels(state, signals, custom, expected):
    assert complexity.assess(state, signals, custom)[0] == expected


def test_complexity_depends_on_scope_not_on_budget_or_size():
    state = {'baseId': 'tienda', 'moduleIds': ['whatsapp']}
    for sig in ({}, {'size_reason': 'empresa enorme'}, {'budget': 999999}):
        assert complexity.assess(state, complexity.clean_signals(sig))[0] == complexity.assess(state, {})[0]


def test_clean_signals_drops_invalid_values():
    assert complexity.clean_signals({'branches': -3, 'users_estimate': True, 'special_audit': 'sí', 'process_complexity': 'extreme', 'hack': 1}) == {}
    assert complexity.clean_signals({'branches': 3, 'infrastructure': 'special'}) == {'branches': 3, 'infrastructure': 'special'}


# --- Admin / CRM -----------------------------------------------------------------------------------------------------
def test_admin_shows_crm_data(client, form, captcha, fake_ai, django_user_model):
    data = create_session(client, form, captcha)
    say(client, data, fake_ai, 'caro', tool_round('classify_client', {'business_size': 'small', 'needs_summary': 'Vender panes'}, 'c'),
        tool_round('propose_options', {'options': [opt('recommended', 'tienda')]}, 'p'),
        tool_round('record_negotiation', {'reason': 'Muy caro', 'ideal_budget_usd': 400}, 'n'),
        tool_round('record_objection', {'category': 'price', 'detail': 'Presupuesto menor'}, 'o'), text_round('ok'))
    admin = django_user_model.objects.create_superuser('admin', 'a@example.com', 'pw-12345-xyz')
    client.force_login(admin)
    lead = Lead.objects.get()
    page = client.get(f'/admin/leads/lead/{lead.pk}/change/')
    assert page.status_code == 200
    html = page.content.decode()
    for needle in ('Pequeño negocio', 'Muy caro', 'Presupuesto menor', 'Vender panes', 'Recomendada'):
        assert needle in html
    assert client.get('/admin/leads/lead/').status_code == 200
    assert client.get('/admin/leads/proposal/').status_code == 200
    export = client.post('/admin/leads/lead/', {'action': 'export_csv', '_selected_action': [lead.pk]})
    assert export.status_code == 200 and 'Panadería La Espiga' in export.content.decode() and 'Muy caro' in export.content.decode()
