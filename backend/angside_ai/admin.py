from django.contrib import admin
from django.utils.html import format_html, format_html_join

from .models import ChatSession

ROLE_LABEL = {'user': 'Cliente', 'assistant': 'Asesor IA', 'tool': 'Herramienta'}


def transcript_html(session: ChatSession, with_tools: bool = False):
    """Conversación legible: solo lo que se dijeron el cliente y el asesor (las herramientas se ocultan por defecto)."""
    rows = [
        (ROLE_LABEL.get(m.role, m.role), m.created_at.strftime('%d/%m/%Y %H:%M'), m.content, m.role)
        for m in session.messages.all()
        if m.content.strip() and (with_tools or m.role != 'tool')
    ]
    if not rows:
        return format_html('<em>Sin mensajes.</em>')
    return format_html(
        '<div style="max-width:760px;display:grid;gap:8px">{}</div>',
        format_html_join(
            '',
            '<div style="padding:8px 12px;border-radius:6px;background:{};white-space:pre-wrap">'
            '<b>{}</b> <span style="color:#777;font-size:11px">{}</span><br>{}</div>',
            (('#eef4ff' if role == 'user' else '#f4f4f4', who, when, text) for who, when, text, role in rows),
        ),
    )


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'lead', 'business', 'user_messages', 'total_tokens', 'cost_usd', 'closed')
    list_filter = ('closed', 'created_at')
    search_fields = ('lead__name', 'lead__business', 'lead__email', 'messages__content')
    list_select_related = ('lead',)
    readonly_fields = ('id', 'lead', 'user_messages', 'total_tokens', 'cost_usd', 'closed', 'created_at', 'conversation')
    fields = readonly_fields

    @admin.display(description='Negocio')
    def business(self, obj):
        return obj.lead.business

    @admin.display(description='Conversación')
    def conversation(self, obj):
        return transcript_html(obj)

    def has_add_permission(self, request):
        return False
