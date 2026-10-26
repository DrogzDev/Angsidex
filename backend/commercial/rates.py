"""
Tarifas vigentes de OpenRouter para el modelo del chatbot empresarial.
Consulta el listado público de modelos (sin clave y sin consumir créditos) y guarda la fecha de actualización.
Si no se puede obtener la tarifa, se conserva la de respaldo configurada en Django Admin.
"""
import logging
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import httpx
from django.conf import settings
from django.utils import timezone

from . import services
from .models import CommercialSettings

logger = logging.getLogger('angside_ai')
MILLION = Decimal(1_000_000)


def _per_million(value) -> Decimal:
    """OpenRouter informa USD por token (texto); el cotizador usa USD por millón."""
    return (Decimal(str(value)) * MILLION).quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)


def refresh_rates() -> tuple[bool, str]:
    """Actualiza las tarifas vigentes. Devuelve (éxito, mensaje). Nunca lanza por fallos de red."""
    obj: CommercialSettings = services.ensure_settings()
    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/models"
    try:
        res = httpx.get(url, timeout=10)
        res.raise_for_status()
        models = res.json().get('data', [])
        entry = next((m for m in models if m.get('id') == obj.chatbot_model), None)
        if entry is None:
            raise LookupError(f'El modelo «{obj.chatbot_model}» no aparece en OpenRouter.')
        pricing = entry['pricing']
        price_in, price_out = _per_million(pricing['prompt']), _per_million(pricing['completion'])
    except (httpx.HTTPError, ValueError, KeyError, LookupError, InvalidOperation) as exc:
        note = f'Falló la actualización ({type(exc).__name__}): se usa la tarifa de respaldo.'[:200]
        logger.warning('No se pudieron obtener las tarifas de OpenRouter: %s', exc)
        obj.rates_note = note
        obj.save(update_fields=['rates_note', 'updated_at'])
        return False, note
    obj.live_price_in_per_m, obj.live_price_out_per_m = price_in, price_out
    obj.rates_updated_at = timezone.now()
    obj.rates_note = f'Actualizadas desde OpenRouter: ${price_in} / ${price_out} por millón de tokens.'
    obj.save(update_fields=['live_price_in_per_m', 'live_price_out_per_m', 'rates_updated_at', 'rates_note', 'updated_at'])
    return True, obj.rates_note
