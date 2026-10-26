"""
Motor de modalidades de pago y consumo de IA. Reproduce src/lib/payment-plans.ts: aritmética entera/Decimal,
redondeo "mitad hacia arriba" a centavos y la diferencia de centavos absorbida por el último pago.
Trabaja sobre un snapshot de configuración (dict camelCase, el mismo que sirve la API pública), nunca sobre la base de datos.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

Config = dict[str, Any]
Line = dict[str, Any]

PAYMENT_MODES = ['cash', 'm3', 'm6', 'm9']
USAGE_TIERS = ['low', 'medium', 'high', 'custom']

_CENT = Decimal(1)


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def to_cents(usd: Any) -> int:
    return int((d(usd) * 100).quantize(_CENT, rounding=ROUND_HALF_UP))


def from_cents(cents: int) -> int | float:
    """Centavos → USD; entero cuando no hay centavos (igual que el número que imprime JavaScript)."""
    return cents // 100 if cents % 100 == 0 else cents / 100


def percent_of(cents: int, percent: Any) -> int:
    return int((Decimal(cents) * d(percent) / 100).quantize(_CENT, rounding=ROUND_HALF_UP))


def _div_round(n: int, den: int) -> int:
    return int((Decimal(n) / Decimal(den)).quantize(_CENT, rounding=ROUND_HALF_UP))


def clean_decimal(value: Any) -> str:
    """Decimal → texto sin ceros sobrantes ("50.000000" → "50")."""
    text = format(d(value), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _blank(mode_id: str, original: int) -> dict[str, Any]:
    return {
        'modeId': mode_id, 'kind': 'cash' if mode_id == 'cash' else 'financing', 'available': True, 'unavailableReason': '',
        'originalCents': original, 'discountableCents': 0, 'discountPercent': '0', 'discountCents': 0,
        'surchargePercent': '0', 'surchargeCents': 0, 'totalCents': original, 'savingsCents': 0,
        'initialPercent': '0', 'initialCents': 0, 'installmentCount': 0, 'installmentCents': 0,
        'everyMonths': 0, 'termMonths': 0, 'schedule': [], 'requiresApproval': mode_id != 'cash',
    }


def compute_payment(lines: list[Line], mode_id: str, config: Config) -> dict[str, Any]:
    """Una modalidad calculada desde el precio de catálogo. Es idempotente: el descuento nunca se acumula."""
    original = sum(to_cents(l['price']) for l in lines)
    out = _blank(mode_id, original)

    if mode_id == 'cash':
        disc = config['cashDiscount']
        excluded = set(disc['excludedIds'])
        discountable = sum(to_cents(l['price']) for l in lines if l['id'] not in excluded and not excluded & set(l.get('alsoIds', [])))
        below_min = original < to_cents(disc['minDevelopmentUsd'])
        out['discountableCents'] = discountable
        if disc['enabled'] and not below_min and discountable > 0:
            out['discountPercent'] = clean_decimal(disc['percent'])
            out['discountCents'] = percent_of(discountable, disc['percent'])
        elif disc['enabled'] and below_min:
            out['unavailableReason'] = f"El descuento de contado aplica desde ${clean_decimal(disc['minDevelopmentUsd'])} de desarrollo."
        out['totalCents'] = original - out['discountCents']
        out['savingsCents'] = out['discountCents']
        out['installmentCount'] = 1
        out['schedule'] = [{'label': 'Pago único', 'due': 'Al confirmar el proyecto', 'amountCents': out['totalCents']}] if original > 0 else []
        return out

    plan = next((p for p in config['plans'] if p['id'] == mode_id), None)
    if not plan or not plan['enabled']:
        out['available'] = False
        out['unavailableReason'] = 'Esta modalidad no está disponible por ahora.'
        return out
    out.update(surchargePercent=clean_decimal(plan['surchargePercent']), initialPercent=clean_decimal(plan['initialPercent']),
               termMonths=plan['termMonths'], everyMonths=plan['everyMonths'], installmentCount=plan['installments'])
    if original < to_cents(config['financingMinDevelopmentUsd']):
        out['available'] = False
        out['unavailableReason'] = f"El financiamiento aplica desde ${clean_decimal(config['financingMinDevelopmentUsd'])} de desarrollo. Consulta con Angside."

    out['surchargeCents'] = percent_of(original, plan['surchargePercent'])
    out['totalCents'] = original + out['surchargeCents']
    out['initialCents'] = percent_of(out['totalCents'], plan['initialPercent'])
    remaining = out['totalCents'] - out['initialCents']
    n = plan['installments']
    each = _div_round(remaining, n)
    out['installmentCents'] = each
    if original > 0:
        out['schedule'].append({'label': 'Inicial', 'due': 'Al aprobar el plan y firmar el contrato', 'amountCents': out['initialCents']})
        for i in range(1, n + 1):
            amount = remaining - each * (n - 1) if i == n else each  # el último pago absorbe los centavos
            out['schedule'].append({'label': f'Cuota {i} de {n}', 'due': f"Mes {i * plan['everyMonths']}", 'amountCents': amount})
    return out


def compute_all_payments(lines: list[Line], config: Config) -> list[dict[str, Any]]:
    return [compute_payment(lines, m, config) for m in ['cash', *[p['id'] for p in config['plans']]]]


def mode_label(mode_id: str, config: Config) -> str:
    if mode_id == 'cash':
        return 'Contado'
    plan = next((p for p in config['plans'] if p['id'] == mode_id), None)
    return f"{plan['termMonths']} meses" if plan else mode_id


def cadence_text(count: int, every_months: int) -> str:
    unit = 'mensuales' if every_months == 1 else 'trimestrales' if every_months == 3 else f'cada {every_months} meses'
    return f"{count} cuota{'' if count == 1 else 's'} {unit}"


def present_payment(b: dict[str, Any], config: Config) -> dict[str, Any]:
    """Versión para tarjetas y respuestas de herramientas: importes en USD y textos listos para mostrar."""
    usd = from_cents
    out = {
        'mode': b['modeId'], 'label': mode_label(b['modeId'], config), 'kind': b['kind'],
        'available': b['available'], 'unavailable_reason': b['unavailableReason'],
        'original': usd(b['originalCents']), 'discount_percent': b['discountPercent'], 'discount': usd(b['discountCents']),
        'surcharge_percent': b['surchargePercent'], 'surcharge': usd(b['surchargeCents']), 'total': usd(b['totalCents']),
        'savings': usd(b['savingsCents']), 'initial_percent': b['initialPercent'], 'initial': usd(b['initialCents']),
        'installment_count': b['installmentCount'], 'installment': usd(b['installmentCents']), 'every_months': b['everyMonths'],
        'term_months': b['termMonths'], 'requires_approval': b['requiresApproval'],
        'schedule': [{'label': s['label'], 'due': s['due'], 'amount': usd(s['amountCents'])} for s in b['schedule']],
    }
    if b['kind'] == 'financing':
        out['cadence'] = cadence_text(b['installmentCount'], b['everyMonths'])
    return out


# --- Consumo de IA del chatbot ---

def estimate_chatbot_usage(conversations: int, cfg: Config) -> dict[str, Any]:
    convs = max(0, int(conversations))
    queries = convs * cfg['queriesPerConversation']
    in_tokens = queries * cfg['inputTokensPerQuery']
    out_tokens = queries * cfg['outputTokensPerQuery']
    raw = d(in_tokens) * d(cfg['priceInPerM']) + d(out_tokens) * d(cfg['priceOutPerM'])  # USD × 1e6
    cost = raw / Decimal(1_000_000) * (1 + d(cfg['marginPercent']) / 100)
    cents = int((cost * 100).quantize(_CENT, rounding=ROUND_HALF_UP))
    limit = None if cfg.get('monthlyLimitUsd') is None else to_cents(cfg['monthlyLimitUsd'])
    return {
        'conversations': convs, 'queries': queries, 'inputTokens': in_tokens, 'outputTokens': out_tokens,
        'monthlyCents': cents, 'underOneCent': cents == 0 and raw > 0,
        'overLimit': limit is not None and cents > limit, 'monthlyLimitCents': limit,
    }
