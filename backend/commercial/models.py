from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

PERCENT = dict(max_digits=9, decimal_places=6, validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(1000))])


class CommercialSettings(models.Model):
    """
    Configuración comercial del cotizador (una sola fila). Es la única fuente de verdad: el cotizador de Astro
    la descarga de la API pública y el asesor GLM la lee del mismo lugar. Cada cambio genera una versión de precios.
    """

    # --- Descuento de contado ---
    cash_discount_enabled = models.BooleanField('descuento de contado activo', default=True)
    cash_discount_percent = models.DecimalField(
        'descuento de contado (%)', default=Decimal(50), help_text='Se aplica una sola vez, solo al desarrollo.',
        max_digits=9, decimal_places=6, validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))],
    )
    cash_discount_min_development = models.DecimalField(
        'desarrollo mínimo para el descuento (USD)', max_digits=10, decimal_places=2, default=Decimal(0),
        help_text='0 = sin mínimo. Por debajo de este monto no se aplica el descuento de contado.',
    )
    financing_min_development = models.DecimalField(
        'desarrollo mínimo para financiar (USD)', max_digits=10, decimal_places=2, default=Decimal(0),
        help_text='0 = sin mínimo. Mínimo comercial para ofrecer planes financiados; sujeto a la aprobación de Angside.',
    )

    # --- Chatbot empresarial: modelo y tarifas (independiente del presupuesto del asesor comercial) ---
    chatbot_model = models.CharField('modelo de IA del chatbot', max_length=120, default='z-ai/glm-5.3-flash-20260826')
    fallback_price_in_per_m = models.DecimalField('tarifa de respaldo: entrada (USD por millón de tokens)', max_digits=10, decimal_places=6, default=Decimal('0.15'))
    fallback_price_out_per_m = models.DecimalField('tarifa de respaldo: salida (USD por millón de tokens)', max_digits=10, decimal_places=6, default=Decimal('0.50'))
    use_live_rates = models.BooleanField('usar tarifas de OpenRouter cuando estén disponibles', default=True)
    live_price_in_per_m = models.DecimalField('tarifa vigente: entrada', max_digits=10, decimal_places=6, null=True, blank=True, editable=False)
    live_price_out_per_m = models.DecimalField('tarifa vigente: salida', max_digits=10, decimal_places=6, null=True, blank=True, editable=False)
    rates_updated_at = models.DateTimeField('tarifas actualizadas', null=True, blank=True, editable=False)
    rates_note = models.CharField('último intento de actualización', max_length=200, blank=True, editable=False)
    queries_per_conversation = models.PositiveSmallIntegerField('consultas por conversación', default=4, validators=[MinValueValidator(1)])
    input_tokens_per_query = models.PositiveIntegerField('tokens de entrada por consulta', default=1500)
    output_tokens_per_query = models.PositiveIntegerField('tokens de salida por consulta', default=250)
    admin_margin_percent = models.DecimalField('margen de administración (%)', default=Decimal(0), help_text='Se suma al costo de inferencia estimado. 0 = sin margen.', **PERCENT)
    monthly_limit_usd = models.DecimalField('límite de consumo mensual (USD)', max_digits=10, decimal_places=2, null=True, blank=True, help_text='Opcional. Si el estimado lo supera, el cotizador lo advierte.')
    custom_max_conversations = models.PositiveIntegerField('máximo de conversaciones en uso personalizado', default=100000)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'configuración comercial'
        verbose_name_plural = 'configuración comercial'

    def __str__(self) -> str:
        return 'Configuración comercial del cotizador'

    def save(self, *args, **kwargs):
        self.pk = 1  # fila única
        super().save(*args, **kwargs)

    def clean(self):
        from .services import rule_problems

        problems = rule_problems(self.cash_discount_enabled, self.cash_discount_percent)
        if problems:
            raise ValidationError(problems)

    def delete(self, *args, **kwargs):
        raise ValidationError('La configuración comercial no se puede eliminar; desactiva el descuento si no quieres usarlo.')

    @property
    def effective_rates(self) -> tuple[Decimal, Decimal, str]:
        if self.use_live_rates and self.live_price_in_per_m is not None and self.live_price_out_per_m is not None:
            return self.live_price_in_per_m, self.live_price_out_per_m, 'openrouter'
        return self.fallback_price_in_per_m, self.fallback_price_out_per_m, 'fallback'


class PaymentPlan(models.Model):
    class Mode(models.TextChoices):
        M3 = 'm3', '3 meses'
        M6 = 'm6', '6 meses'
        M9 = 'm9', '9 meses'

    settings = models.ForeignKey(CommercialSettings, on_delete=models.CASCADE, related_name='plans')
    mode_id = models.CharField('plan', max_length=3, choices=Mode, unique=True)
    enabled = models.BooleanField('activo', default=True)
    term_months = models.PositiveSmallIntegerField('duración (meses)', validators=[MinValueValidator(1)])
    surcharge_percent = models.DecimalField('incremento sobre el desarrollo (%)', **PERCENT)
    initial_percent = models.DecimalField('inicial (% del total del plan)', max_digits=9, decimal_places=6, validators=[MinValueValidator(Decimal(0)), MaxValueValidator(Decimal(100))])
    installments = models.PositiveSmallIntegerField('número de cuotas', validators=[MinValueValidator(1), MaxValueValidator(60)])
    every_months = models.PositiveSmallIntegerField('periodicidad (cada cuántos meses)', default=1, validators=[MinValueValidator(1)], help_text='1 = mensual, 3 = trimestral.')

    class Meta:
        ordering = ['term_months']
        verbose_name = 'plan financiado'
        verbose_name_plural = 'planes financiados'

    def __str__(self) -> str:
        return self.get_mode_id_display()

    def clean(self):
        if self.installments and self.every_months and self.term_months and self.installments * self.every_months > self.term_months:
            raise ValidationError('Las cuotas no caben en la duración del plan (cuotas × periodicidad no puede superar los meses).')


class UsageTier(models.Model):
    class Tier(models.TextChoices):
        LOW = 'low', 'Uso bajo'
        MEDIUM = 'medium', 'Uso medio'
        HIGH = 'high', 'Uso alto'
        CUSTOM = 'custom', 'Personalizado'

    settings = models.ForeignKey(CommercialSettings, on_delete=models.CASCADE, related_name='tiers')
    tier_id = models.CharField('nivel', max_length=6, choices=Tier, unique=True)
    label = models.CharField('etiqueta', max_length=40)
    conversations = models.PositiveIntegerField('conversaciones mensuales', help_text='En "Personalizado" es el valor inicial sugerido.')

    class Meta:
        ordering = ['conversations']
        verbose_name = 'nivel de uso del chatbot'
        verbose_name_plural = 'niveles de uso del chatbot'

    def __str__(self) -> str:
        return f'{self.label} ({self.conversations}/mes)'


class ModuleRule(models.Model):
    """Reglas comerciales por módulo o base: exclusión del descuento y costo mínimo de implementación."""

    settings = models.ForeignKey(CommercialSettings, on_delete=models.CASCADE, related_name='module_rules')
    item_id = models.CharField('base o módulo (id del catálogo)', max_length=40, unique=True)
    excluded_from_discount = models.BooleanField('excluir del descuento de contado', default=False)
    min_implementation_cost = models.DecimalField(
        'costo mínimo de implementación (USD)', max_digits=10, decimal_places=2, null=True, blank=True,
        help_text='Lo mínimo que cuesta realmente hacerlo. Si el precio con descuento queda por debajo, hay que excluirlo del descuento o bajar este mínimo.',
    )
    note = models.CharField('nota interna', max_length=200, blank=True)

    class Meta:
        verbose_name = 'regla por módulo'
        verbose_name_plural = 'reglas por módulo'

    def __str__(self) -> str:
        return self.item_id

    def clean(self):
        from .services import catalog_price, discounted_price_problem

        if catalog_price(self.item_id) is None:
            raise ValidationError({'item_id': 'No existe ese id en el catálogo (revisa src/data/pricing.ts).'})
        problem = discounted_price_problem(self.item_id, self.excluded_from_discount, self.min_implementation_cost)
        if problem:
            raise ValidationError(problem)


class PricingVersion(models.Model):
    """Foto inmutable de la configuración comercial. Cada cotización guarda la versión con que se calculó."""

    content_hash = models.CharField(max_length=64, unique=True, editable=False)
    catalog_hash = models.CharField('huella del catálogo de precios', max_length=64, editable=False)
    snapshot = models.JSONField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
        verbose_name = 'versión de precios'
        verbose_name_plural = 'versiones de precios'

    def __str__(self) -> str:
        return f'Versión {self.pk} · {self.created_at:%Y-%m-%d %H:%M}'


class SavedQuote(models.Model):
    """Cotización registrada cuando el visitante la envía por WhatsApp. No contiene datos personales."""

    reference = models.CharField('referencia', max_length=16, unique=True)
    source = models.CharField(max_length=20, default='calculator')
    config_query = models.CharField('configuración del cotizador', max_length=600)
    payment_mode = models.CharField('modalidad de pago', max_length=6, blank=True)
    pricing_version = models.ForeignKey(PricingVersion, on_delete=models.PROTECT, related_name='quotes')
    development_original = models.DecimalField('desarrollo original (USD)', max_digits=12, decimal_places=2)
    development_total = models.DecimalField('desarrollo según la modalidad (USD)', max_digits=12, decimal_places=2)
    breakdown = models.JSONField('detalle calculado', default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'cotización registrada'
        verbose_name_plural = 'cotizaciones registradas'

    def __str__(self) -> str:
        return f'{self.reference} · ${self.development_total}'
