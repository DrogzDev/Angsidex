from django.db import models


class Lead(models.Model):
    class Budget(models.TextChoices):
        LT_200 = 'lt200', 'Menos de $200'
        R_200_500 = '200-500', '$200–$500'
        R_500_1000 = '500-1000', '$500–$1.000'
        R_1000_3000 = '1000-3000', '$1.000–$3.000'
        GT_3000 = 'gt3000', 'Más de $3.000'
        UNDEFINED = 'undefined', 'Todavía no tengo presupuesto definido'

    class HasWebsite(models.TextChoices):
        YES = 'yes', 'Sí'
        NO = 'no', 'No'

    class StartWhen(models.TextChoices):
        ASAP = 'asap', 'Lo antes posible'
        MONTH = '1m', 'En el próximo mes'
        QUARTER = '3m', 'En los próximos 3 meses'
        EXPLORING = 'exploring', 'Solo estoy explorando'

    class BusinessSize(models.TextChoices):
        SMALL = 'small', 'Pequeño negocio'
        MEDIUM = 'medium', 'Mediana empresa'
        LARGE = 'large', 'Empresa grande'

    class Complexity(models.TextChoices):
        BASIC = 'basic', 'Básica'
        INTERMEDIATE = 'intermediate', 'Intermedia'
        ADVANCED = 'advanced', 'Avanzada'
        CUSTOM = 'custom', 'Personalizada / requiere evaluación'

    class Status(models.TextChoices):
        NEW = 'new', 'Nuevo'
        NEGOTIATING = 'negotiating', 'En negociación'
        CONTACT_REQUESTED = 'contact_requested', 'Solicitó contacto'
        CONTACTED = 'contacted', 'Contactado'
        WON = 'won', 'Ganado'
        LOST = 'lost', 'Perdido'

    # Obligatorios
    name = models.CharField('nombre', max_length=120)
    business = models.CharField('negocio o proyecto', max_length=160)
    email = models.EmailField('correo', blank=True)
    phone = models.CharField('teléfono', max_length=32, blank=True)
    sector = models.CharField('sector', max_length=120)
    need = models.TextField('necesidad', max_length=1500)

    # Opcionales
    whatsapp = models.CharField(max_length=32, blank=True)
    location = models.CharField('ciudad o país', max_length=120, blank=True)
    has_website = models.CharField(max_length=3, choices=HasWebsite, blank=True)
    budget_range = models.CharField(max_length=12, choices=Budget, blank=True)
    start_when = models.CharField(max_length=12, choices=StartWhen, blank=True)

    # Consentimientos: el comercial es independiente y nunca se marca por defecto.
    marketing_consent = models.BooleanField('autoriza contacto comercial', default=False)
    privacy_version = models.CharField(max_length=20)
    consented_at = models.DateTimeField(auto_now_add=True)

    # --- CRM: lo que la IA descubre en la conversación ---
    # Orientativo (no es un umbral legal) y editable por el visitante o por el equipo. Nunca influye en los precios.
    business_size = models.CharField('tamaño estimado', max_length=8, choices=BusinessSize, blank=True)
    size_confirmed_by_client = models.BooleanField('tamaño corregido por el cliente', default=False)
    complexity = models.CharField('complejidad del proyecto', max_length=12, choices=Complexity, blank=True)
    needs_summary = models.TextField('necesidades declaradas', blank=True)
    # Señales de alcance (usuarios, sucursales, volumen, integraciones…) usadas para evaluar la complejidad.
    signals = models.JSONField('señales de alcance', default=dict, blank=True)
    recommended_features = models.JSONField('funcionalidades recomendadas', default=list, blank=True)
    budget_stated_usd = models.PositiveIntegerField('presupuesto indicado (USD)', null=True, blank=True)
    budget_calculated_usd = models.PositiveIntegerField('presupuesto calculado (USD)', null=True, blank=True)
    objections = models.JSONField('objeciones comerciales', default=list, blank=True)
    negotiation_requested = models.BooleanField('solicitó negociación', default=False)
    negotiation_initial_budget = models.PositiveIntegerField('presupuesto inicial (USD)', null=True, blank=True)
    negotiation_ideal_budget = models.PositiveIntegerField('presupuesto ideal del cliente (USD)', null=True, blank=True)
    negotiation_reason = models.TextField('motivo de la negociación', blank=True)

    status = models.CharField(max_length=20, choices=Status, default=Status.NEW)
    notes = models.TextField('notas', blank=True)
    ip_hash = models.CharField(max_length=64, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(email='', phone=''),
                name='lead_has_email_or_phone',
            )
        ]

    def __str__(self) -> str:
        return f'{self.name} · {self.business}'

    BUDGET_CEILING = {'lt200': 200, '200-500': 500, '500-1000': 1000, '1000-3000': 3000}

    @property
    def budget_ceiling_usd(self) -> int | None:
        """Tope de presupuesto conocido: el monto ideal de una negociación, el que dijo en la conversación o el límite de su rango."""
        return self.negotiation_ideal_budget or self.budget_stated_usd or self.BUDGET_CEILING.get(self.budget_range)


class Proposal(models.Model):
    """Propuesta generada por la IA y validada/calculada por el motor de cotización (nunca texto libre)."""

    class Tier(models.TextChoices):
        ESSENTIAL = 'essential', 'Esencial'
        RECOMMENDED = 'recommended', 'Recomendada'
        COMPLETE = 'complete', 'Completa'
        ADJUSTED = 'adjusted', 'Ajustada a tu presupuesto'

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='proposals')
    session = models.ForeignKey('angside_ai.ChatSession', on_delete=models.SET_NULL, null=True, blank=True, related_name='proposals')
    round = models.PositiveSmallIntegerField('ronda', default=1)
    tier = models.CharField(max_length=12, choices=Tier)
    config = models.CharField('configuración del cotizador', max_length=400)
    development_total = models.PositiveIntegerField('desarrollo (USD)')
    payload = models.JSONField('datos mostrados al visitante', default=dict)
    requires_custom_quote = models.BooleanField('requiere cotización personalizada', default=False)
    complexity = models.CharField(max_length=12, choices=Lead.Complexity)
    within_budget = models.BooleanField(null=True, blank=True)
    requested = models.BooleanField('el visitante la solicitó', default=False)
    # Modalidad de pago elegida (contado o plan financiado) y versión de precios con la que se calcularon los importes.
    payment_mode = models.CharField('modalidad de pago', max_length=6, blank=True)
    pricing_version = models.PositiveIntegerField('versión de precios', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['round', 'id']

    def __str__(self) -> str:
        return f'{self.get_tier_display()} · ${self.development_total}'
