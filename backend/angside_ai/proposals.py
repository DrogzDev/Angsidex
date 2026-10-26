"""
Construcción de propuestas. Todo lo que ve el visitante en una tarjeta sale de aquí: se valida con las reglas
del cotizador y los montos los calcula el motor (quote.py). La IA solo elige ids; nunca aporta precios.
"""
import re
from typing import Any

from django.conf import settings
from django.db import transaction

from commercial import engine, services
from leads.models import Lead, Proposal

from . import complexity, quote

# No hay una regla de estimación de plazos aprobada: siempre se informa como pendiente.
TIMELINE_TEXT = 'Pendiente de evaluación'
CUSTOM_QUOTE_TEXT = 'Requiere cotización personalizada'

TIER_ORDER = ['essential', 'recommended', 'complete']
BENEFIT_FORBIDDEN = re.compile(r'[$%]|\busd\b|descuento|rebaja|gratis|promoci|garantiz|\d{3,}', re.IGNORECASE)
MAX_CUSTOM_ITEMS = 5
MAX_CUSTOM_LEN = 160
MAX_BENEFIT_LEN = 220


class ToolError(Exception):
    """Argumentos inválidos de una herramienta: se devuelven al modelo para que corrija."""


def clean_text(value: Any, name: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        raise ToolError(f'{name} debe ser texto{" no vacío" if required else ""}')
    return ' '.join(value.split())[:limit]


def profile_payload(lead: Lead) -> dict:
    return {
        'size': lead.business_size,
        'size_label': complexity.SIZE_LABELS.get(lead.business_size, ''),
        'size_confirmed': lead.size_confirmed_by_client,
        'complexity': lead.complexity,
        'complexity_label': complexity.LABELS.get(lead.complexity, ''),
    }


def _features(state: dict, q: dict) -> list[dict]:
    cat = quote.catalog()
    out: list[dict] = []
    base = quote.base_by_id(state['baseId'])
    for line in q['lines']:
        if line['kind'] == 'base':
            out.append({'id': line['id'], 'kind': 'base', 'label': line['label'], 'price': line['price'], 'from': False, 'benefit': base['description']})
        elif line['kind'] == 'module':
            mod = quote.module_by_id(line['id'])
            out.append({'id': line['id'], 'kind': 'module', 'label': line['label'], 'price': line['price'], 'from': line['from'], 'benefit': mod['description']})
        else:
            dep = cat['dependencies'][line['id']]
            out.append({'id': line['id'], 'kind': 'dependency', 'label': line['label'], 'price': line['price'], 'from': False, 'benefit': dep['reason']})
    for inc in base['includes'] if base else []:
        mod = quote.module_by_id(inc)
        dep = cat['dependencies'].get(inc)
        label = (mod or dep or {}).get('name')
        if label:
            out.append({'id': inc, 'kind': 'included', 'label': label, 'price': 0, 'from': False, 'benefit': (mod or {}).get('description') or (dep or {}).get('reason', '')})
    return out


def build_option(raw: dict, lead: Lead, signals: dict, config: dict) -> tuple[dict, dict]:
    """Valida una opción y devuelve (payload_para_el_visitante, estado_del_cotizador). Lanza ToolError si es inválida."""
    allowed = {'tier', 'base_id', 'module_ids', 'hosting_id', 'maintenance', 'billing_plan_id', 'custom_items', 'benefits', 'payment_mode_id', 'chatbot_usage'}
    extra = set(raw) - allowed
    if extra:
        raise ToolError(f'Argumentos no permitidos en la opción: {sorted(extra)}. Los precios los calcula el sistema.')
    tier = raw.get('tier')
    if tier not in Proposal.Tier.values:
        raise ToolError(f'tier inválido: {tier!r}')
    if 'base_id' not in raw:
        raise ToolError('Falta base_id')
    modules = raw.get('module_ids', [])
    if not isinstance(modules, list) or not all(isinstance(m, str) for m in modules):
        raise ToolError('module_ids debe ser una lista de textos')

    state = {
        'baseId': raw['base_id'],
        'moduleIds': modules,
        # Los requisitos técnicos se incluyen y se muestran como líneas; el asistente debe explicarlos.
        'confirmedDeps': list(quote.catalog()['dependencies']),
        'hostingId': raw.get('hosting_id', 'externo'),
        'maintenance': bool(raw.get('maintenance', False)),
        'billingPlanId': raw.get('billing_plan_id'),
        'paymentModeId': raw.get('payment_mode_id'),
        'chatbotUsage': raw.get('chatbot_usage'),
        'chatbotConversations': None,
    }
    if state['paymentModeId'] is not None and state['paymentModeId'] not in engine.PAYMENT_MODES:
        raise ToolError(f"payment_mode_id debe ser uno de {engine.PAYMENT_MODES}")
    if state['chatbotUsage'] is not None and state['chatbotUsage'] not in ('low', 'medium', 'high'):
        raise ToolError('chatbot_usage debe ser low, medium o high')
    problems = quote.validate_state(state)
    if state['chatbotUsage'] and not quote.has_chatbot(state['baseId'], state['moduleIds']):
        problems.append('chatbot_usage solo aplica si la propuesta incluye el chatbot con IA.')
    if problems:
        raise ToolError(f'Opción {tier}: ' + ' '.join(problems))
    if 'facturacion' in state['moduleIds'] and not state['billingPlanId']:
        raise ToolError(f'Opción {tier}: con facturacion debes indicar billing_plan_id (emprendedor, pymes o gold) según el tamaño de la operación.')

    custom_items_raw = raw.get('custom_items', [])
    if not isinstance(custom_items_raw, list) or len(custom_items_raw) > MAX_CUSTOM_ITEMS:
        raise ToolError(f'custom_items debe ser una lista de máximo {MAX_CUSTOM_ITEMS} textos')
    custom_items = [clean_text(c, 'custom_items', MAX_CUSTOM_LEN) for c in custom_items_raw]

    q = quote.compute_quote(state, config)
    state = q['state']
    features = _features(state, q)

    # Beneficios: solo para funcionalidades de la propuesta y sin cifras, descuentos ni promesas.
    benefits = raw.get('benefits', [])
    if not isinstance(benefits, list):
        raise ToolError('benefits debe ser una lista de {feature_id, benefit}')
    by_id = {f['id']: f for f in features}
    for b in benefits:
        if not isinstance(b, dict) or set(b) - {'feature_id', 'benefit'}:
            raise ToolError('Cada beneficio debe tener solo feature_id y benefit')
        fid, text = b.get('feature_id'), b.get('benefit')
        if fid not in by_id or not isinstance(text, str):
            continue
        text = ' '.join(text.split())[:MAX_BENEFIT_LEN]
        if text and not BENEFIT_FORBIDDEN.search(text):
            by_id[fid]['benefit'] = text

    level, factors = complexity.assess(state, signals, custom_items)
    ceiling = lead.budget_ceiling_usd
    hosting = quote.hosting_by_id(state['hostingId']) or {'name': 'Hosting externo'}
    plan = quote.plan_by_id(state['billingPlanId'])
    monthly_lines = []
    if q['hostingMonthly']:
        monthly_lines.append({'label': hosting['name'], 'usd': q['hostingMonthly'], 'from': bool(hosting.get('from'))})
    if q['billingMonthly']:
        monthly_lines.append({'label': f"Facturación digital {plan['name']} (costo fijo)", 'usd': q['billingMonthly'], 'from': False})
    if q['maintenanceMonthly']:
        monthly_lines.append({'label': quote.catalog()['maintenance']['name'], 'usd': q['maintenanceMonthly'], 'from': True})

    base = quote.base_by_id(state['baseId'])
    notices = list(q['notices'])
    if q['hostingNeedsEvaluation']:
        notices.append('El servidor Xeon compartido está sujeto a disponibilidad y evaluación.')

    payment_options = [engine.present_payment(b, config) for b in q['paymentOptions']]
    usage = q['usage']
    ai_usage = None
    if q['hasChatbot']:
        ai_usage = {
            'model': config['chatbot']['model'], 'rates_source': config['chatbot']['ratesSource'],
            'conversations': usage['conversations'] if usage else None,
            'monthly': engine.from_cents(usage['monthlyCents']) if usage else None,
            'under_one_cent': bool(usage and usage['underOneCent']),
            'note': 'Consumo de IA variable según uso, aparte del desarrollo y fuera del total mensual. Estimación orientativa, no una garantía.',
        }

    payload = {
        'recommended_type': base['name'],
        'config': quote.encode_state(state),
        'development_total': q['developmentTotal'],
        'development_from': q['developmentFrom'],
        'payments': q['payments'],
        'monthly': {'hosting': q['hostingMonthly'], 'billing': q['billingMonthly'], 'maintenance': q['maintenanceMonthly'], 'total': q['monthlyTotal'], 'from': q['monthlyFrom']},
        'monthly_lines': monthly_lines,
        'features': features,
        'custom_items': custom_items,
        'requires_custom_quote': bool(custom_items),
        'custom_quote_text': CUSTOM_QUOTE_TEXT if custom_items else '',
        'complexity': level,
        'complexity_label': complexity.LABELS[level],
        'complexity_factors': factors,
        'within_budget': (q['developmentTotal'] <= ceiling) if ceiling else None,
        'budget_ceiling': ceiling,
        'timeline': TIMELINE_TEXT,
        'notices': notices,
        'complete': q['complete'],
        'payment_options': payment_options,
        'payment_mode': state['paymentModeId'],
        'pricing_version': config['version'],
        'ai_usage': ai_usage,
    }
    return {**payload, 'tier': tier}, state


def _payment_summary(options: list[dict]) -> list[dict]:
    """Importes por modalidad para el modelo: todos calculados por el motor."""
    out = []
    for o in options:
        row = {'modalidad': o['mode'], 'nombre': o['label'], 'disponible': o['available'], 'total_desarrollo_usd': o['total']}
        if o['kind'] == 'cash':
            row.update(precio_original_usd=o['original'], descuento_usd=o['discount'], ahorro_usd=o['savings'])
        else:
            row.update(incremento_usd=o['surcharge'], inicial_usd=o['initial'], cuotas=o['cadence'], cuota_usd=o['installment'],
                       sin_descuento=True, sujeto_a_aprobacion=True)
        out.append(row)
    return out


def proposal_payload(p: Proposal) -> dict:
    # La modalidad elegida vive en la columna (puede cambiar después de crear la tarjeta); el resto del payload es histórico.
    return {**p.payload, 'id': p.id, 'tier': p.tier, 'name': p.get_tier_display(), 'round': p.round, 'requested': p.requested, 'payment_mode': p.payment_mode or None}


def create_proposals(args: dict, session) -> tuple[dict, list[dict]]:
    """Herramienta propose_options: valida 1 a 3 opciones, las calcula, las guarda en el CRM y arma el evento para el chat."""
    if set(args) - {'options'}:
        raise ToolError('Solo se permite el argumento options')
    options = args.get('options')
    if not isinstance(options, list) or not 1 <= len(options) <= 3:
        raise ToolError('options debe tener entre 1 y 3 opciones')

    lead = session.lead
    last_round = lead.proposals.order_by('-round').values_list('round', flat=True).first() or 0
    if last_round >= settings.AI_MAX_PROPOSAL_ROUNDS:
        raise ToolError('Se alcanzó el máximo de propuestas para esta conversación. Ofrece contacto humano con request_contact.')

    signals = complexity.clean_signals(lead.signals)
    config = services.current_config()  # una sola versión de precios para todas las opciones de la ronda
    built = [build_option(o if isinstance(o, dict) else {}, lead, signals, config) for o in options]
    tiers = [b[0]['tier'] for b in built]
    if len(set(tiers)) != len(tiers):
        raise ToolError('Cada opción debe tener un tier distinto')

    # Esencial ≤ Recomendada ≤ Completa en costo de desarrollo: no se "infla" la propuesta sin más funcionalidades.
    ranked = [b[0] for b in sorted(built, key=lambda b: TIER_ORDER.index(b[0]['tier']) if b[0]['tier'] in TIER_ORDER else 99) if b[0]['tier'] in TIER_ORDER]
    for lo, hi in zip(ranked, ranked[1:]):
        if lo['development_total'] > hi['development_total']:
            raise ToolError('El costo debe aumentar de Esencial a Recomendada y a Completa; ordena las opciones por alcance.')

    round_no = last_round + 1
    created: list[Proposal] = []
    with transaction.atomic():
        for payload, state in built:
            created.append(Proposal.objects.create(
                lead=lead, session=session, round=round_no, tier=payload['tier'], config=payload['config'],
                development_total=payload['development_total'], payload=payload,
                requires_custom_quote=payload['requires_custom_quote'], complexity=payload['complexity'],
                within_budget=payload['within_budget'], payment_mode=payload['payment_mode'] or '', pricing_version=config['version'],
            ))
        main = next((p for p in created if p.tier == 'recommended'), created[0])
        lead.complexity = main.complexity
        lead.recommended_features = [f['label'] for f in main.payload['features'] if f['kind'] != 'dependency']
        lead.budget_calculated_usd = main.development_total
        lead.save(update_fields=['complexity', 'recommended_features', 'budget_calculated_usd', 'updated_at'])

    cards = [proposal_payload(p) for p in created]
    result = {
        'ok': True,
        'ronda': round_no,
        'clasificacion_del_cliente': lead.get_business_size_display() or 'sin clasificar',
        'plazo': TIMELINE_TEXT,
        'propuestas': [
            {
                'tier': c['tier'], 'nombre': c['name'], 'complejidad': c['complexity_label'],
                'desarrollo_usd': c['development_total'], 'desde': c['development_from'],
                'pago_para_arrancar_usd': c['payments']['start'], 'pago_al_culminar_usd': c['payments']['delivery'],
                'mensual_usd': c['monthly']['total'],
                'funcionalidades': [f['label'] for f in c['features'] if f['kind'] in ('base', 'module')],
                'requiere_cotizacion_personalizada': c['custom_items'] or False,
                'dentro_del_presupuesto': c['within_budget'],
                'incompleta': not c['complete'],
                'modalidad_elegida': c['payment_mode'],
                'modalidades_de_pago': _payment_summary(c['payment_options']),
            }
            for c in cards
        ],
        'instruccion': (
            'Las tarjetas ya muestran al visitante precios, pagos, funcionalidades y costos recurrentes. No repitas todos los montos: '
            'explica en pocas frases por qué cada opción y qué problema suyo resuelve cada funcionalidad. Si el visitante pregunta por '
            'formas de pago, usa get_payment_options y cita solo esos importes; no inventes descuentos.'
        ),
    }
    event = {'type': 'proposals', 'round': round_no, 'profile': profile_payload(lead), 'proposals': cards}
    return result, [event]
