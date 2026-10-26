"""
Guardia contra montos inventados. Los precios oficiales salen del motor de cotización; si el texto libre del
asistente menciona un monto que no proviene del catálogo, de una propuesta calculada ni de lo que dijo el
visitante, se avisa en la conversación y se deja constancia en el historial.
"""
import re

from commercial import services

from . import quote

MONEY = re.compile(r'\$\s?(\d[\d.,]*)|(\d[\d.,]*)\s?(?:usd|dólares|dolares)\b', re.IGNORECASE)
NUMBER = re.compile(r'\d[\d.,]*')

DISCOUNT_WORDS = re.compile(r'\b(descuento|rebaja|promoci[oó]n|gratis|regalo|oferta especial)\b', re.IGNORECASE)


def _to_int(raw: str) -> int | None:
    s = raw.strip('.,')
    if not s:
        return None
    # "1.250" y "1,250" son miles; "12,5" / "12.5" se descartan por decimales (se redondean).
    if re.fullmatch(r'\d{1,3}([.,]\d{3})+', s):
        return int(re.sub(r'[.,]', '', s))
    if re.fullmatch(r'\d+[.,]\d{1,2}', s):
        return int(float(s.replace(',', '.')))
    return int(re.sub(r'[.,]', '', s)) if re.fullmatch(r'\d+', s) else None


def mentioned_amounts(text: str) -> set[int]:
    out: set[int] = set()
    for m in MONEY.finditer(text):
        v = _to_int(m.group(1) or m.group(2))
        if v is not None:
            out.add(v)
    return out


def catalog_amounts() -> set[int]:
    c = quote.catalog()
    # 2: el texto comercial del chatbot dice "puede ser inferior a $2 USD mensuales" (no es una garantía).
    nums: set[int] = {c['billingRange']['min'], c['billingRange']['max'], c['maintenance']['monthly'], 2}
    nums.update(b['price'] for b in c['bases'])
    nums.update(m['price'] for m in c['modules'])
    nums.update(d['price'] for d in c['dependencies'].values())
    nums.update(h['monthly'] for h in c['hostingOptions'])
    nums.update(p['monthly'] for p in c['billingPlans'])
    return nums


def _whole(value) -> set[int]:
    """Un importe con centavos puede citarse truncado o redondeado ($264,50 → 264 o 265)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return set()
    return {int(value), int(value + 0.5)}


def allowed_amounts(session) -> set[int]:
    allowed = catalog_amounts()
    for p in session.lead.proposals.all():
        data = p.payload
        allowed.add(p.development_total)
        allowed.update(data.get('payments', {}).values())
        allowed.update(v for v in data.get('monthly', {}).values() if isinstance(v, int) and not isinstance(v, bool))
        allowed.update(f['price'] for f in data.get('features', []))
        allowed.update(l['usd'] for l in data.get('monthly_lines', []))
        for o in data.get('payment_options', []):
            for key in ('original', 'discount', 'surcharge', 'total', 'savings', 'initial', 'installment'):
                allowed.update(_whole(o.get(key)))
            for step in o.get('schedule', []):
                allowed.update(_whole(step.get('amount')))
        usage = data.get('ai_usage')
        if usage:
            allowed.update(_whole(usage.get('monthly')))
    lead = session.lead
    for v in (lead.budget_stated_usd, lead.negotiation_ideal_budget, lead.negotiation_initial_budget, lead.budget_calculated_usd):
        if v:
            allowed.add(v)
    for m in session.messages.filter(role='user'):
        allowed.update(int(n) for n in (_to_int(x) for x in NUMBER.findall(m.content)) if n is not None)
    return allowed


def unverified(text: str, session) -> dict:
    """Montos del texto que no son verificables y palabras de descuento/promoción."""
    bad = sorted(mentioned_amounts(text) - allowed_amounts(session))
    return {'amounts': bad, 'discount_words': offered_discounts(text), 'percents': unverified_percents(text, session)}


PERCENT = re.compile(r'(\d+(?:[.,]\d+)?)\s?%')
PAYMENT_CONTEXT = re.compile(r'descuento|rebaja|incremento|recargo|aumento|inicial|financ|cuota|ahorr', re.IGNORECASE)


def allowed_percents(session) -> set[float]:
    """Porcentajes de pago que sí existen: los de la configuración vigente, los de la versión de cada propuesta y los que dijo el visitante."""
    out: set[float] = {100.0}  # "el sistema es 100 % tuyo"
    configs = [services.current_config()]
    for version in {p.pricing_version for p in session.lead.proposals.all() if p.pricing_version}:
        old = services.config_for_version(version)
        if old:
            configs.append(old)
    for cfg in configs:
        out.add(float(cfg['cashDiscount']['percent']))
        for plan in cfg['plans']:
            out.update({float(plan['surchargePercent']), float(plan['initialPercent'])})
    for m in session.messages.filter(role='user'):
        out.update(float(x.replace(',', '.')) for x in PERCENT.findall(m.content))
    return out


def unverified_percents(text: str, session) -> list[float]:
    """Porcentajes de descuento, incremento o inicial que no existen en las condiciones comerciales."""
    bad: set[float] = set()
    allowed: set[float] | None = None
    for m in PERCENT.finditer(text):
        if not PAYMENT_CONTEXT.search(text[max(0, m.start() - 40): m.end() + 40]):
            continue
        value = float(m.group(1).replace(',', '.'))
        allowed = allowed if allowed is not None else allowed_percents(session)
        if not any(abs(value - a) < 0.01 or abs(value - round(a, 1)) < 0.01 for a in allowed):
            bad.add(value)
    return sorted(bad)


NEGATION = re.compile(r'\b(no|ni|sin|tampoco|nunca|jam[aá]s)\b', re.IGNORECASE)


def offered_discounts(text: str) -> list[str]:
    """Palabras de descuento/promoción que se OFRECEN. "No manejamos descuentos" es correcto y no cuenta."""
    found: list[str] = []
    for m in DISCOUNT_WORDS.finditer(text):
        before = text[max(0, m.start() - 45): m.start()]
        before = re.split(r'[.!?¡¿\n]', before)[-1]  # la negación debe estar en la misma oración
        # El único descuento real es el de contado, calculado por el sistema (sus montos y porcentaje se verifican aparte).
        if m.group(0).lower() == 'descuento' and 'contado' in _sentence(text, m.start()).lower():
            continue
        if not NEGATION.search(before):
            found.append(m.group(0).lower())
    return found


def _sentence(text: str, pos: int) -> str:
    start = max(text.rfind(c, 0, pos) for c in '.!?¡¿\n') + 1
    ends = [i for i in (text.find(c, pos) for c in '.!?\n') if i != -1]
    return text[start: min(ends) if ends else len(text)]
