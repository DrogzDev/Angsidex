"""
Motor de cotización en Python. Reproduce src/lib/quote-engine.ts usando los precios exportados de
src/data/pricing.ts (backend/angside_ai/data/pricing.json). La paridad se comprueba con
tests/fixtures/quote_cases.json, generado por el motor TypeScript (npm run export:contract).
"""
import json
import math
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, urlencode

from django.conf import settings

from commercial import engine

State = dict[str, Any]


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    with open(settings.PRICING_CONTRACT_PATH, encoding='utf-8') as f:
        return json.load(f)


def _by_id(items: list[dict], item_id: str | None) -> dict | None:
    return next((i for i in items if i['id'] == item_id), None)


def base_by_id(i): return _by_id(catalog()['bases'], i)
def module_by_id(i): return _by_id(catalog()['modules'], i)
def hosting_by_id(i): return _by_id(catalog()['hostingOptions'], i)
def plan_by_id(i): return _by_id(catalog()['billingPlans'], i)


def _unique(xs: list) -> list:
    return list(dict.fromkeys(xs))


def initial_state() -> State:
    return {
        'baseId': None, 'moduleIds': [], 'confirmedDeps': [], 'hostingId': 'externo', 'maintenance': False, 'billingPlanId': None,
        'paymentModeId': None, 'chatbotUsage': None, 'chatbotConversations': None,
    }


MAX_CUSTOM_CONVERSATIONS = 1_000_000


def has_chatbot(base_id: str | None, module_ids: list[str]) -> bool:
    base = base_by_id(base_id)
    return 'chatbot' in module_ids or bool(base and 'chatbot' in base['includes'])


def _required_dependencies(base_id: str | None, module_ids: list[str]) -> list[str]:
    base = base_by_id(base_id)
    needed: list[str] = []
    for mid in module_ids:
        for dep in module_by_id(mid)['requires']:
            if not (base and dep in base['includes']) and dep not in needed:
                needed.append(dep)
    return needed


def normalize_state(state: State) -> State:
    base = base_by_id(state.get('baseId'))
    module_ids: list[str] = []
    if base:
        for mid in _unique(list(state.get('moduleIds', []))):
            mod = module_by_id(mid)
            if mod and base['id'] not in mod.get('incompatibleWith', []) and mid not in base['includes']:
                module_ids.append(mid)
    needed = _required_dependencies(base['id'] if base else None, module_ids)
    deps = catalog()['dependencies']
    usage = state.get('chatbotUsage')
    usage = usage if usage in engine.USAGE_TIERS and has_chatbot(base['id'] if base else None, module_ids) else None
    convs = state.get('chatbotConversations')
    convs = min(int(convs), MAX_CUSTOM_CONVERSATIONS) if usage == 'custom' and isinstance(convs, int) and not isinstance(convs, bool) and convs > 0 else None
    mode = state.get('paymentModeId')
    return {
        'baseId': base['id'] if base else None,
        'moduleIds': module_ids,
        'confirmedDeps': [d for d in _unique(list(state.get('confirmedDeps', []))) if d in deps and d in needed],
        'hostingId': (hosting_by_id(state.get('hostingId')) or {'id': 'externo'})['id'],
        'maintenance': bool(state.get('maintenance')),
        'billingPlanId': (plan_by_id(state.get('billingPlanId')) or {}).get('id') if 'facturacion' in module_ids else None,
        'paymentModeId': mode if mode in engine.PAYMENT_MODES else None,
        'chatbotUsage': usage,
        'chatbotConversations': convs,
    }


def validate_state(state: State) -> list[str]:
    """Problemas de una combinación (vacío = válida). Mismos criterios que validateState en TypeScript."""
    errors: list[str] = []
    base = base_by_id(state.get('baseId'))
    if state.get('baseId') and not base:
        errors.append(f"Base desconocida: {state['baseId']}")
    if not hosting_by_id(state.get('hostingId', 'externo')):
        errors.append(f"Hosting desconocido: {state.get('hostingId')}")
    mods = list(state.get('moduleIds', []))
    if len(set(mods)) != len(mods):
        errors.append('Hay módulos duplicados.')
    for mid in mods:
        mod = module_by_id(mid)
        if not mod:
            errors.append(f'Módulo desconocido: {mid}')
        elif not base:
            errors.append(f"Elige primero un tipo de proyecto antes de agregar «{mod['name']}».")
        elif base['id'] in mod.get('incompatibleWith', []):
            errors.append(f"«{mod['name']}» no aplica a {base['name']}.")
        elif mid in base['includes']:
            errors.append(f"«{mod['name']}» ya está incluido en {base['name']}.")
    plan = state.get('billingPlanId')
    if plan:
        if not plan_by_id(plan):
            errors.append(f'Plan de facturación desconocido: {plan}')
        elif 'facturacion' not in mods:
            errors.append('El plan de facturación requiere el módulo de facturación digital.')
    if state.get('paymentModeId') and state['paymentModeId'] not in engine.PAYMENT_MODES:
        errors.append(f"Modalidad de pago desconocida: {state['paymentModeId']}")
    if state.get('chatbotUsage'):
        if state['chatbotUsage'] not in engine.USAGE_TIERS:
            errors.append(f"Volumen de uso desconocido: {state['chatbotUsage']}")
        if not has_chatbot(state.get('baseId'), mods):
            errors.append('El volumen de uso requiere el chatbot con IA.')
    return errors


def split_payments(total: int) -> dict[str, int]:
    start = math.floor(total * catalog()['paymentSplit']['start'] + 0.5)  # Math.round de JS
    return {'start': start, 'delivery': total - start}


def usage_conversations(state: State, config: dict[str, Any]) -> int | None:
    if not state['chatbotUsage']:
        return None
    if state['chatbotUsage'] == 'custom':
        return state['chatbotConversations']
    tier = next((t for t in config['chatbot']['tiers'] if t['id'] == state['chatbotUsage']), None)
    return tier['conversations'] if tier else None


def compute_quote(input_state: State, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Cotiza con la configuración comercial indicada (por ejemplo, una versión histórica) o con la vigente."""
    if config is None:
        from commercial import services

        config = services.current_config()
    state = normalize_state(input_state)
    cat = catalog()
    base = base_by_id(state['baseId'])
    lines: list[dict] = []
    if base:
        lines.append({'kind': 'base', 'id': base['id'], 'label': base['name'], 'price': base['price'], 'from': bool(base.get('from'))})
    selected = [module_by_id(m) for m in state['moduleIds']]
    notices: list[str] = []
    for mod in selected:
        lines.append({'kind': 'module', 'id': mod['id'], 'label': mod['name'], 'price': mod['price'], 'from': bool(mod.get('from'))})
        if mod.get('notice'):
            notices.append(f"{mod['name']}: {mod['notice']}")
    pending: list[dict] = []
    for dep_id in _required_dependencies(state['baseId'], state['moduleIds']):
        dep = cat['dependencies'][dep_id]
        if dep_id in state['confirmedDeps']:
            lines.append({'kind': 'dependency', 'id': dep_id, 'label': dep['name'], 'price': dep['price'], 'from': False})
        else:
            pending.append({'id': dep_id, 'name': dep['name'], 'price': dep['price'], 'requiredBy': [m['name'] for m in selected if dep_id in m['requires']]})

    hosting = hosting_by_id(state['hostingId']) or cat['hostingOptions'][0]
    hosting_monthly = hosting['monthly']
    maintenance_monthly = cat['maintenance']['monthly'] if state['maintenance'] else 0
    plan = plan_by_id(state['billingPlanId'])
    billing_monthly = plan['monthly'] if plan else 0
    missing_plan = 'facturacion' in state['moduleIds'] and not state['billingPlanId']
    development_total = sum(l['price'] for l in lines)
    dev_lines = [
        {'kind': l['kind'], 'id': l['id'], 'price': l['price'], 'alsoIds': [base['sameAs']] if l['kind'] == 'base' and base.get('sameAs') else []}
        for l in lines
    ]
    payment_options = engine.compute_all_payments(dev_lines, config) if base else []
    payment = next((p for p in payment_options if p['modeId'] == state['paymentModeId']), None) if state['paymentModeId'] else None
    chatbot = has_chatbot(state['baseId'], state['moduleIds'])
    convs = usage_conversations(state, config)
    usage = engine.estimate_chatbot_usage(convs, config['chatbot']) if chatbot and convs is not None else None
    return {
        'state': state,
        'lines': lines,
        'developmentTotal': development_total,
        'payments': split_payments(development_total),
        'hostingMonthly': hosting_monthly,
        'billingMonthly': billing_monthly,
        'maintenanceMonthly': maintenance_monthly,
        'monthlyTotal': hosting_monthly + billing_monthly + maintenance_monthly,
        'developmentFrom': any(l['from'] for l in lines),
        'monthlyFrom': (hosting_monthly > 0 and bool(hosting.get('from'))) or state['maintenance'],
        'pending': pending,
        'missingBillingPlan': missing_plan,
        'notices': notices,
        'hostingNeedsEvaluation': bool(hosting.get('needsEvaluation')),
        'complete': bool(base) and not pending and not missing_plan,
        'payment': payment,
        'paymentOptions': payment_options,
        'hasChatbot': chatbot,
        'usage': usage,
        'pricingVersion': config.get('version'),
    }


def decode_state(query: str) -> State:
    p = parse_qs(query, keep_blank_values=False)
    first = lambda k: (p.get(k) or [''])[0]
    lst = lambda k: [v for v in first(k).split(',') if v]
    cat = catalog()
    return normalize_state({
        'baseId': first('b') if base_by_id(first('b')) else None,
        'moduleIds': [m for m in lst('m') if module_by_id(m)],
        'confirmedDeps': [d for d in lst('d') if d in cat['dependencies']],
        'hostingId': first('h') if hosting_by_id(first('h')) else 'externo',
        'maintenance': first('k') == '1',
        'billingPlanId': first('c') if plan_by_id(first('c')) else None,
        'paymentModeId': first('p') if first('p') in engine.PAYMENT_MODES else None,
        'chatbotUsage': first('u') if first('u') in engine.USAGE_TIERS else None,
        'chatbotConversations': int(first('n')) if first('n').isdigit() and len(first('n')) <= 7 else None,
    })


def encode_state(state: State) -> str:
    s = normalize_state(state)
    params: list[tuple[str, str]] = []
    if s['baseId']: params.append(('b', s['baseId']))
    if s['moduleIds']: params.append(('m', ','.join(s['moduleIds'])))
    if s['confirmedDeps']: params.append(('d', ','.join(s['confirmedDeps'])))
    if s['hostingId'] != 'externo': params.append(('h', s['hostingId']))
    if s['maintenance']: params.append(('k', '1'))
    if s['billingPlanId']: params.append(('c', s['billingPlanId']))
    if s['paymentModeId']: params.append(('p', s['paymentModeId']))
    if s['chatbotUsage']: params.append(('u', s['chatbotUsage']))
    if s['chatbotConversations']: params.append(('n', str(s['chatbotConversations'])))
    return urlencode(params, safe=',')
