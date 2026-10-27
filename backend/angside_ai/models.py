import uuid

from django.db import models


class ChatSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey('leads.Lead', on_delete=models.CASCADE, related_name='sessions')
    # Evita crear sesiones duplicadas cuando el cliente reintenta la misma solicitud.
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    user_messages = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    # Mensajes ajenos a los servicios de Angside; al llegar al tope la conversación se cierra.
    off_topic_strikes = models.PositiveSmallIntegerField(default=0)
    closed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = 'user', 'Usuario'
        ASSISTANT = 'assistant', 'Asistente'
        TOOL = 'tool', 'Herramienta'

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=Role)
    content = models.TextField(blank=True)
    # tool_calls (assistant) o tool_call_id (tool), tal como lo exige la API.
    meta = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']


class TurnstileUse(models.Model):
    """Hash de cada token de Turnstile ya consumido: impide reutilizarlo."""

    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AiUsageDay(models.Model):
    day = models.DateField(unique=True)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    tokens = models.PositiveBigIntegerField(default=0)


class IpUsageDay(models.Model):
    """Consumo de IA por IP (hash) y día: una IP no obtiene cupo nuevo creando otra conversación."""

    ip_hash = models.CharField(max_length=64)
    day = models.DateField()
    tokens = models.PositiveBigIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["ip_hash", "day"], name="uniq_ip_usage_day")]


class RateEvent(models.Model):
    key = models.CharField(max_length=160, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
