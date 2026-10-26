from django.contrib import admin, messages
from django.utils.html import format_html

from . import services
from .models import CommercialSettings, ModuleRule, PaymentPlan, PricingVersion, SavedQuote, UsageTier
from .rates import refresh_rates


class PaymentPlanInline(admin.TabularInline):
    model = PaymentPlan
    extra = 0
    max_num = 3
    can_delete = False
    fields = ('mode_id', 'enabled', 'term_months', 'surcharge_percent', 'initial_percent', 'installments', 'every_months')


class UsageTierInline(admin.TabularInline):
    model = UsageTier
    extra = 0
    max_num = 4
    can_delete = False
    fields = ('tier_id', 'label', 'conversations')


class ModuleRuleInline(admin.TabularInline):
    model = ModuleRule
    extra = 0
    fields = ('item_id', 'excluded_from_discount', 'min_implementation_cost', 'note')


@admin.register(CommercialSettings)
class CommercialSettingsAdmin(admin.ModelAdmin):
    """Una sola fila. Cada guardado registra una nueva versión de precios si algo cambió."""

    inlines = [PaymentPlanInline, UsageTierInline, ModuleRuleInline]
    actions = ['update_rates']
    readonly_fields = ('current_version', 'rates_state', 'rates_updated_at', 'live_price_in_per_m', 'live_price_out_per_m', 'rates_note', 'updated_at')
    fieldsets = (
        ('Versión de precios', {'fields': ('current_version',), 'description': 'Cada cotización guarda la versión con la que se calculó; los presupuestos históricos no cambian.'}),
        ('Descuento de contado', {'fields': ('cash_discount_enabled', 'cash_discount_percent', 'cash_discount_min_development'), 'description': 'Se aplica una sola vez, solo al desarrollo (nunca a mantenimiento, hosting, consumo de IA, dominios, comisiones, impuestos ni servicios externos). Las exclusiones por módulo están al final.'}),
        ('Financiamiento', {'fields': ('financing_min_development',), 'description': 'Los planes (incremento, inicial, cuotas y periodicidad) se editan abajo. Todo plan queda sujeto a aprobación manual de Angside.'}),
        ('Chatbot empresarial · modelo y tarifas', {'fields': ('chatbot_model', 'use_live_rates', 'fallback_price_in_per_m', 'fallback_price_out_per_m', 'rates_state', 'live_price_in_per_m', 'live_price_out_per_m', 'rates_updated_at', 'rates_note'), 'description': 'Independiente del presupuesto de consumo del asesor comercial. Usa la acción «Actualizar tarifas desde OpenRouter» desde el listado.'}),
        ('Chatbot empresarial · estimación de consumo', {'fields': ('queries_per_conversation', 'input_tokens_per_query', 'output_tokens_per_query', 'admin_margin_percent', 'monthly_limit_usd', 'custom_max_conversations')}),
        ('Registro', {'fields': ('updated_at',)}),
    )

    def has_add_permission(self, request):
        return not CommercialSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        services.ensure_settings()
        return super().get_queryset(request)

    def changelist_view(self, request, extra_context=None):
        services.ensure_settings()
        return super().changelist_view(request, extra_context)

    @admin.display(description='Versión vigente')
    def current_version(self, obj):
        return f"v{services.current_config()['version']}" if obj and obj.pk else '—'

    @admin.display(description='Tarifa en uso')
    def rates_state(self, obj):
        price_in, price_out, source = obj.effective_rates
        label = 'OpenRouter (vigente)' if source == 'openrouter' else 'respaldo configurado'
        return format_html('${} entrada / ${} salida por millón de tokens · {}', price_in, price_out, label)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        version = services.publish_version()
        messages.info(request, f'Versión de precios vigente: v{version.pk}.')

    @admin.action(description='Actualizar tarifas desde OpenRouter')
    def update_rates(self, request, queryset):
        ok, message = refresh_rates()
        self.message_user(request, message, messages.SUCCESS if ok else messages.WARNING)
        services.publish_version()


@admin.register(PricingVersion)
class PricingVersionAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at', 'quotes_count')
    readonly_fields = ('content_hash', 'catalog_hash', 'snapshot', 'created_at')

    @admin.display(description='Cotizaciones')
    def quotes_count(self, obj):
        return obj.quotes.count()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SavedQuote)
class SavedQuoteAdmin(admin.ModelAdmin):
    list_display = ('reference', 'created_at', 'payment_mode', 'development_original', 'development_total', 'pricing_version')
    list_filter = ('payment_mode', 'source')
    search_fields = ('reference',)
    readonly_fields = [f.name for f in SavedQuote._meta.fields]

    def has_add_permission(self, request):
        return False
