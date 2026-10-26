"""Rate limiting y control de presupuesto de IA. Todo vive en base de datos: funciona con varios procesos."""
import hashlib
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import AiUsageDay, RateEvent


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__('rate limited')
        self.retry_after = retry_after


def client_ip(request) -> str:
    if settings.TRUST_CF_CONNECTING_IP:
        cf = request.META.get('HTTP_CF_CONNECTING_IP')
        if cf:
            return cf.strip()
    return request.META.get('REMOTE_ADDR', '') or 'unknown'


def digest(value: str) -> str:
    """Hash con sal del proyecto: no se guardan IP ni contactos en claro en las tablas de límites."""
    return hashlib.sha256(f'{settings.SECRET_KEY}:{value}'.encode()).hexdigest()


def hit(name: str, subject: str) -> None:
    """Registra un evento y lanza RateLimited si se supera el límite configurado en RATE_LIMITS[name]."""
    limit, window = settings.RATE_LIMITS[name]
    key = f'{name}:{digest(subject)[:40]}'
    now = timezone.now()
    with transaction.atomic():
        since = now - timedelta(seconds=window)
        events = RateEvent.objects.filter(key=key, created_at__gte=since).order_by('created_at')
        count = events.count()
        if count >= limit:
            oldest = events.first()
            retry = int((oldest.created_at + timedelta(seconds=window) - now).total_seconds()) + 1 if oldest else window
            raise RateLimited(max(retry, 1))
        RateEvent.objects.create(key=key)
    if random.random() < 0.02:
        RateEvent.objects.filter(created_at__lt=now - timedelta(days=1)).delete()


# --- Presupuesto de IA ---

def _today():
    return timezone.localdate()


def spent_today() -> Decimal:
    row = AiUsageDay.objects.filter(day=_today()).first()
    return row.cost_usd if row else Decimal(0)


def spent_this_month() -> Decimal:
    today = _today()
    total = AiUsageDay.objects.filter(day__year=today.year, day__month=today.month).aggregate(s=Sum('cost_usd'))['s']
    return total or Decimal(0)


def budget_available() -> bool:
    return spent_today() < Decimal(str(settings.AI_DAILY_BUDGET_USD)) and spent_this_month() < Decimal(str(settings.AI_MONTHLY_BUDGET_USD))


def estimate_cost(tokens_in: int, tokens_out: int) -> Decimal:
    cost = tokens_in * settings.AI_PRICE_IN_PER_M / 1_000_000 + tokens_out * settings.AI_PRICE_OUT_PER_M / 1_000_000
    return Decimal(str(round(cost, 6)))


def record_usage(session, tokens_in: int, tokens_out: int, cost: Decimal | None) -> None:
    """Suma el consumo a la sesión y al día. `cost` es el informado por OpenRouter; si falta, se estima."""
    cost = cost if cost is not None else estimate_cost(tokens_in, tokens_out)
    tokens = tokens_in + tokens_out
    with transaction.atomic():
        row, _ = AiUsageDay.objects.get_or_create(day=_today())
        AiUsageDay.objects.filter(pk=row.pk).update(cost_usd=F('cost_usd') + cost, tokens=F('tokens') + tokens)
        type(session).objects.filter(pk=session.pk).update(total_tokens=F('total_tokens') + tokens, cost_usd=F('cost_usd') + cost)
    session.refresh_from_db(fields=['total_tokens', 'cost_usd'])
