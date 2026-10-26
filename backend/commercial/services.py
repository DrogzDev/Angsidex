"""
Configuración comercial vigente y su versionado.

`current_config()` es el único punto de lectura del cotizador, de la API pública y del asesor GLM: construye el snapshot
desde Django Admin y, si cambió algo, registra una nueva PricingVersion (inmutable). Así los presupuestos históricos
conservan las condiciones con las que se calcularon.
"""
import hashlib
import json
from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction

from . import engine
from .models import CommercialSettings, ModuleRule, PaymentPlan, PricingVersion, UsageTier

TIER_ORDER = engine.USAGE_TIERS


def _quote():
    from angside_ai import quote  # import perezoso: quote.py también usa este módulo

    return quote


def contract_defaults() -> dict[str, Any]:
    """Valores iniciales exportados desde src/data/commercial.ts (npm run export:contract)."""
    return _quote().catalog()['commercialDefaults']


def catalog_price(item_id: str) -> int | float | None:
    c = _quote().catalog()
    item = next((x for x in [*c['bases'], *c['modules']] if x['id'] == item_id), None)
    return item['price'] if item else None


def catalog_hash() -> str:
    c = _quote().catalog()
    data = {k: c[k] for k in ('bases', 'modules', 'dependencies', 'hostingOptions', 'maintenance', 'billingPlans', 'paymentSplit')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def ensure_settings() -> CommercialSettings:
    """Fila única de configuración; la primera vez se siembra con los valores por defecto del contrato."""
    obj = CommercialSettings.objects.filter(pk=1).first()
    if obj:
        return obj
    dflt = contract_defaults()
    cd, ch = dflt['cashDiscount'], dflt['chatbot']
    with transaction.atomic():
        obj, created = CommercialSettings.objects.get_or_create(pk=1, defaults=dict(
            cash_discount_enabled=cd['enabled'], cash_discount_percent=Decimal(cd['percent']),
            cash_discount_min_development=Decimal(cd['minDevelopmentUsd']),
            financing_min_development=Decimal(dflt['financingMinDevelopmentUsd']),
            chatbot_model=ch['model'], fallback_price_in_per_m=Decimal(ch['priceInPerM']), fallback_price_out_per_m=Decimal(ch['priceOutPerM']),
            queries_per_conversation=ch['queriesPerConversation'], input_tokens_per_query=ch['inputTokensPerQuery'],
            output_tokens_per_query=ch['outputTokensPerQuery'], admin_margin_percent=Decimal(ch['marginPercent']),
            monthly_limit_usd=None if ch['monthlyLimitUsd'] is None else Decimal(ch['monthlyLimitUsd']),
            custom_max_conversations=ch['customMaxConversations'],
        ))
        if created:
            for p in dflt['plans']:
                PaymentPlan.objects.create(
                    settings=obj, mode_id=p['id'], enabled=p['enabled'], term_months=p['termMonths'],
                    surcharge_percent=Decimal(p['surchargePercent']), initial_percent=Decimal(p['initialPercent']),
                    installments=p['installments'], every_months=p['everyMonths'],
                )
            for t in ch['tiers']:
                UsageTier.objects.create(settings=obj, tier_id=t['id'], label=t['label'], conversations=t['conversations'])
            for item_id in cd['excludedIds']:
                ModuleRule.objects.create(settings=obj, item_id=item_id, excluded_from_discount=True)
    return obj


def build_snapshot(obj: CommercialSettings | None = None) -> dict[str, Any]:
    """Configuración pública (camelCase, sin `version`): lo que consume el cotizador y el motor."""
    obj = obj or ensure_settings()
    c = engine.clean_decimal
    price_in, price_out, source = obj.effective_rates
    plans = list(obj.plans.all())
    tiers = sorted(obj.tiers.all(), key=lambda t: TIER_ORDER.index(t.tier_id))
    return {
        'cashDiscount': {
            'enabled': obj.cash_discount_enabled,
            'percent': c(obj.cash_discount_percent),
            'minDevelopmentUsd': c(obj.cash_discount_min_development),
            'excludedIds': sorted(r.item_id for r in obj.module_rules.all() if r.excluded_from_discount),
        },
        'financingMinDevelopmentUsd': c(obj.financing_min_development),
        'plans': [
            {
                'id': p.mode_id, 'enabled': p.enabled, 'termMonths': p.term_months, 'surchargePercent': c(p.surcharge_percent),
                'initialPercent': c(p.initial_percent), 'installments': p.installments, 'everyMonths': p.every_months,
            }
            for p in plans
        ],
        'chatbot': {
            'model': obj.chatbot_model,
            'priceInPerM': c(price_in), 'priceOutPerM': c(price_out), 'ratesSource': source,
            'ratesUpdatedAt': obj.rates_updated_at.isoformat() if obj.rates_updated_at and source == 'openrouter' else None,
            'queriesPerConversation': obj.queries_per_conversation,
            'inputTokensPerQuery': obj.input_tokens_per_query, 'outputTokensPerQuery': obj.output_tokens_per_query,
            'marginPercent': c(obj.admin_margin_percent),
            'monthlyLimitUsd': None if obj.monthly_limit_usd is None else c(obj.monthly_limit_usd),
            'tiers': [{'id': t.tier_id, 'label': t.label, 'conversations': t.conversations} for t in tiers],
            'customMaxConversations': obj.custom_max_conversations,
        },
    }


def _hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def publish_version(snapshot: dict[str, Any] | None = None) -> PricingVersion:
    """Devuelve la versión que corresponde a este contenido; crea una nueva solo si es distinto de las anteriores."""
    snapshot = snapshot or build_snapshot()
    digest = _hash(snapshot)
    existing = PricingVersion.objects.filter(content_hash=digest).first()
    if existing:
        return existing
    try:
        with transaction.atomic():
            return PricingVersion.objects.create(content_hash=digest, catalog_hash=catalog_hash(), snapshot=snapshot)
    except IntegrityError:  # otra petición la creó a la vez
        return PricingVersion.objects.get(content_hash=digest)


def current_config() -> dict[str, Any]:
    """Configuración vigente con su número de versión."""
    snapshot = build_snapshot()
    version = publish_version(snapshot)
    return {'version': version.pk, **snapshot}


def config_for_version(number: int | None) -> dict[str, Any] | None:
    """Configuración histórica exacta (para reproducir una cotización antigua)."""
    version = PricingVersion.objects.filter(pk=number).first() if number else None
    return {'version': version.pk, **version.snapshot} if version else None


# --- Validación administrativa del descuento ---

def _discounted_cents(price: Any, percent: Any) -> int:
    cents = engine.to_cents(price)
    return cents - engine.percent_of(cents, percent)


def discounted_price_problem(item_id: str, excluded: bool, min_cost: Any, enabled: bool | None = None, percent: Any = None) -> str:
    """Mensaje si el precio con descuento de un módulo queda por debajo de su costo mínimo de implementación."""
    if excluded or min_cost is None:
        return ''
    price = catalog_price(item_id)
    if price is None:
        return ''
    if enabled is None or percent is None:
        current = CommercialSettings.objects.filter(pk=1).first()
        enabled = current.cash_discount_enabled if current else contract_defaults()['cashDiscount']['enabled']
        percent = current.cash_discount_percent if current else contract_defaults()['cashDiscount']['percent']
    if not enabled:
        return ''
    after = _discounted_cents(price, percent)
    if after < engine.to_cents(min_cost):
        return (
            f'«{item_id}» costaría ${engine.from_cents(after)} con el descuento de contado y su costo mínimo de implementación es '
            f'${min_cost}. Exclúyelo del descuento o baja el mínimo antes de habilitar esta combinación.'
        )
    return ''


def rule_problems(enabled: bool, percent: Any) -> list[str]:
    """Todas las reglas que dejarían de cumplirse con el descuento indicado."""
    out = []
    for rule in ModuleRule.objects.all():
        msg = discounted_price_problem(rule.item_id, rule.excluded_from_discount, rule.min_implementation_cost, enabled, percent)
        if msg:
            out.append(msg)
    return out
