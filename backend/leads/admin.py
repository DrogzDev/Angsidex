import csv
import json

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html, format_html_join

from angside_ai.admin import transcript_html

from .models import Lead, Proposal


@admin.action(description='Exportar seleccionados a CSV')
def export_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="prospectos.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Fecha', 'Nombre', 'Negocio', 'Correo', 'Teléfono', 'WhatsApp', 'Sector', 'Necesidad', 'Tamaño', 'Complejidad',
        'Presupuesto (rango)', 'Presupuesto indicado USD', 'Presupuesto calculado USD', 'Funcionalidades recomendadas',
        'Negociación', 'Presupuesto ideal USD', 'Motivo negociación', 'Objeciones', 'Modalidad de pago elegida', 'Estado', 'Contacto comercial',
    ])
    for lead in queryset:
        writer.writerow([
            lead.created_at.isoformat(), lead.name, lead.business, lead.email, lead.phone, lead.whatsapp, lead.sector, lead.need,
            lead.get_business_size_display(), lead.get_complexity_display(), lead.get_budget_range_display(),
            lead.budget_stated_usd or '', lead.budget_calculated_usd or '', '; '.join(lead.recommended_features),
            'sí' if lead.negotiation_requested else 'no', lead.negotiation_ideal_budget or '', lead.negotiation_reason,
            '; '.join(f"{o.get('category')}: {o.get('detail')}" for o in lead.objections),
            '; '.join(sorted({p.payment_mode for p in lead.proposals.all() if p.payment_mode})),
            lead.get_status_display(), 'sí' if lead.marketing_consent else 'no',
        ])
    return response


class ProposalInline(admin.TabularInline):
    model = Proposal
    extra = 0
    can_delete = False
    fields = ('round', 'tier', 'development_total', 'payment_mode', 'pricing_version', 'complexity', 'within_budget', 'requires_custom_quote', 'requested', 'config')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'name', 'business', 'contact', 'sector', 'budget_range', 'complexity', 'budget_calculated_usd', 'chosen_payment', 'status', 'negotiation_requested')
    date_hierarchy = 'created_at'
    list_per_page = 50
    list_filter = ('status', 'business_size', 'complexity', 'negotiation_requested', 'budget_range', 'marketing_consent', 'has_website')
    search_fields = ('name', 'business', 'email', 'phone', 'whatsapp', 'sector')
    readonly_fields = ('created_at', 'updated_at', 'consented_at', 'privacy_version', 'signals_pretty', 'objections_pretty', 'conversation')
    inlines = [ProposalInline]
    actions = [export_csv]
    fieldsets = (
        ('Contacto', {'fields': ('name', 'business', 'email', 'phone', 'whatsapp', 'location', 'status', 'notes')}),
        ('Lo que declaró', {'fields': ('sector', 'need', 'needs_summary', 'has_website', 'budget_range', 'budget_stated_usd', 'start_when')}),
        ('Clasificación (editable; no afecta los precios)', {'fields': ('business_size', 'size_confirmed_by_client', 'complexity', 'signals_pretty')}),
        ('Conversación con el asesor de IA', {'fields': ('conversation',)}),
        ('Propuesta', {'fields': ('recommended_features', 'budget_calculated_usd')}),
        ('Negociación y objeciones', {'fields': ('negotiation_requested', 'negotiation_initial_budget', 'negotiation_ideal_budget', 'negotiation_reason', 'objections_pretty')}),
        ('Consentimiento', {'fields': ('marketing_consent', 'privacy_version', 'consented_at', 'created_at', 'updated_at')}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('proposals', 'sessions__messages')

    @admin.display(description='Contacto')
    def contact(self, obj):
        return ' · '.join(x for x in (obj.whatsapp or obj.phone, obj.email) if x) or '—'

    @admin.display(description='Pago elegido')
    def chosen_payment(self, obj):
        modes = sorted({p.payment_mode for p in obj.proposals.all() if p.payment_mode})
        return ', '.join(modes) or '—'

    @admin.display(description='Conversación')
    def conversation(self, obj):
        sessions = list(obj.sessions.all())
        if not sessions:
            return '—'
        return format_html_join('', '<div style="margin-bottom:16px">{}</div>', ((transcript_html(s),) for s in sessions))

    @admin.display(description='Señales de alcance')
    def signals_pretty(self, obj):
        return format_html('<pre style="margin:0">{}</pre>', json.dumps(obj.signals, ensure_ascii=False, indent=2) if obj.signals else '—')

    @admin.display(description='Objeciones')
    def objections_pretty(self, obj):
        if not obj.objections:
            return '—'
        return format_html('<pre style="margin:0">{}</pre>', '\n'.join(f"[{o.get('at', '')}] {o.get('category')}: {o.get('detail')}" for o in obj.objections))


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'lead', 'round', 'tier', 'development_total', 'payment_mode', 'complexity', 'within_budget', 'requires_custom_quote', 'requested')
    list_filter = ('tier', 'complexity', 'requested', 'requires_custom_quote')
    search_fields = ('lead__name', 'lead__business')
    readonly_fields = [f.name for f in Proposal._meta.fields]

    def has_add_permission(self, request):
        return False
