"""Panel /admin: los prospectos muestran contacto, conversación con el asesor y modalidad de pago elegida."""
import pytest
from django.urls import reverse

from angside_ai.models import ChatMessage, ChatSession
from leads.models import Lead, Proposal

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead():
    lead = Lead.objects.create(
        name='Ana Pérez', business='Panadería Sol', email='ana@sol.co', whatsapp='584141112233', sector='Alimentos',
        need='Quiero vender pan en línea', privacy_version='1',
    )
    session = ChatSession.objects.create(lead=lead)
    ChatMessage.objects.create(session=session, role='user', content='Necesito una tienda para mis pedidos')
    ChatMessage.objects.create(session=session, role='assistant', content='Te recomiendo la tienda online con pedidos')
    ChatMessage.objects.create(session=session, role='tool', content='{"ok": true, "secreto_interno": 1}')
    Proposal.objects.create(
        lead=lead, session=session, tier='recommended', config='b=tienda', development_total=550, complexity='basic', payment_mode='cash',
    )
    return lead


def test_lead_list_shows_contact_and_chosen_payment(admin_client, lead):
    html = admin_client.get(reverse('admin:leads_lead_changelist')).content.decode()
    assert 'Panadería Sol' in html and '584141112233' in html and 'ana@sol.co' in html and 'cash' in html


def test_lead_page_shows_the_conversation_without_tool_noise(admin_client, lead):
    html = admin_client.get(reverse('admin:leads_lead_change', args=[lead.pk])).content.decode()
    assert 'Necesito una tienda para mis pedidos' in html and 'Te recomiendo la tienda online' in html
    assert 'Cliente' in html and 'Asesor IA' in html
    assert 'secreto_interno' not in html


def test_chat_sessions_are_listed_searchable_and_readable(admin_client, lead):
    url = reverse('admin:angside_ai_chatsession_changelist')
    assert 'Panadería Sol' in admin_client.get(url).content.decode()
    assert 'Panadería Sol' in admin_client.get(url, {'q': 'tienda'}).content.decode()
    session = lead.sessions.get()
    html = admin_client.get(reverse('admin:angside_ai_chatsession_change', args=[session.pk])).content.decode()
    assert 'Necesito una tienda para mis pedidos' in html


def test_csv_export_includes_the_chosen_payment_mode(admin_client, lead):
    resp = admin_client.post(reverse('admin:leads_lead_changelist'), {'action': 'export_csv', '_selected_action': [lead.pk]})
    body = resp.content.decode()
    assert resp.status_code == 200 and 'Modalidad de pago elegida' in body and 'cash' in body and 'Ana Pérez' in body


def test_admin_requires_login(client):
    assert client.get(reverse('admin:leads_lead_changelist')).status_code == 302
