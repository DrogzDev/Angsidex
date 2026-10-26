import json
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import F, Q
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from leads.models import Lead

from leads.models import Proposal

from . import limits, payments, prompts, proposals, turnstile
from .models import ChatMessage, ChatSession
from .serializers import ContactRequestSerializer, MessageSerializer, ProfileUpdateSerializer, SessionCreateSerializer
from .service import run_turn
from .tools import add_note, mark_contact_requested

logger = logging.getLogger('angside_ai')
TOKEN_SALT = 'angside-ai-session'
IDEMPOTENCY_RE = re.compile(r'^[A-Za-z0-9_\-]{8,64}$')
CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def err(code: str, message: str, http: int, **extra) -> Response:
    return Response({'code': code, 'message': message, **extra}, status=http)


def rate_limited(exc: limits.RateLimited) -> Response:
    resp = err('rate_limited', 'Demasiadas solicitudes. Intenta de nuevo en unos minutos.', status.HTTP_429_TOO_MANY_REQUESTS, retry_after=exc.retry_after)
    resp['Retry-After'] = str(exc.retry_after)
    return resp


def make_token(session: ChatSession) -> str:
    return signing.dumps({'sid': str(session.id)}, salt=TOKEN_SALT)


def session_from_request(request, session_id) -> ChatSession | None:
    """Valida el token de sesión (Authorization: Bearer ...) y que corresponda a la sesión de la URL."""
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    try:
        data = signing.loads(header[7:], salt=TOKEN_SALT, max_age=settings.SESSION_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    if data.get('sid') != str(session_id):
        return None
    return ChatSession.objects.select_related('lead').filter(pk=session_id).first()


def session_payload(session: ChatSession, **extra) -> dict:
    """Estado de la sesión para reanudarla: texto y tarjetas de propuesta en el orden original."""
    messages: list[dict] = []
    for m in session.messages.all():
        if m.role in ('user', 'assistant') and m.content:
            messages.append({'role': m.role, 'content': m.content})
        elif m.role == 'tool':
            for ev in m.meta.get('ui_events', []):
                if ev.get('type') == 'proposals':
                    # Se releen de la base para reflejar si el visitante ya la solicitó.
                    ids = [p['id'] for p in ev['proposals']]
                    fresh = {p.id: proposals.proposal_payload(p) for p in Proposal.objects.filter(id__in=ids)}
                    messages.append({'role': 'event', 'event': {**ev, 'proposals': [fresh.get(p['id'], p) for p in ev['proposals']]}})
    return {
        'session_id': str(session.id),
        'token': make_token(session),
        'remaining_messages': max(settings.AI_MAX_USER_MESSAGES_PER_SESSION - session.user_messages, 0),
        'profile': proposals.profile_payload(session.lead),
        'messages': messages,
        **extra,
    }


class SessionCreateView(APIView):
    def post(self, request):
        ip = limits.client_ip(request)
        try:
            limits.hit('session_create_ip', ip)
        except limits.RateLimited as exc:
            return rate_limited(exc)

        # Reintento de la misma solicitud: devuelve la sesión existente sin crear otra.
        key = request.headers.get('Idempotency-Key', '')
        if key:
            if not IDEMPOTENCY_RE.match(key):
                return err('bad_request', 'Idempotency-Key inválida.', 400)
            existing = ChatSession.objects.select_related('lead').filter(idempotency_key=key).first()
            if existing:
                return Response(session_payload(existing), status=status.HTTP_200_OK)

        ser = SessionCreateSerializer(data=request.data)
        if not ser.is_valid():
            return err('validation_error', 'Revisa los campos del formulario.', 400, errors=ser.errors)
        data = ser.validated_data

        if data.get('website_url'):
            # Trampa para bots: respuesta genérica, sin crear nada.
            return err('validation_error', 'Revisa los campos del formulario.', 400)

        contact = (data.get('email') or data.get('phone', '')).lower()
        try:
            limits.hit('session_create_contact', contact)
        except limits.RateLimited as exc:
            return rate_limited(exc)

        # CAPTCHA: verificación real en el servidor; no hay sesión sin pasar este paso.
        if not turnstile.verify(data['turnstile_token'], ip):
            return err('captcha_failed', 'No pudimos verificar que eres una persona. Inténtalo de nuevo.', status.HTTP_403_FORBIDDEN)

        # Mismo contacto con una conversación reciente: se reutiliza en vez de duplicar.
        since = timezone.now() - timedelta(seconds=settings.SESSION_REUSE_WINDOW)
        match = Q()
        if data.get('email'):
            match |= Q(lead__email__iexact=data['email'])
        if data.get('phone'):
            match |= Q(lead__phone=data['phone'])
        recent = ChatSession.objects.select_related('lead').filter(match, created_at__gte=since, closed=False).first()
        if recent:
            return Response(session_payload(recent), status=status.HTTP_200_OK)

        with transaction.atomic():
            lead = Lead.objects.create(
                name=data['name'], business=data['business'], email=data.get('email', ''), phone=data.get('phone', ''),
                sector=data['sector'], need=data['need'], whatsapp=data.get('whatsapp', ''), location=data.get('location', ''),
                has_website=data.get('has_website', ''), budget_range=data.get('budget_range', ''), start_when=data.get('start_when', ''),
                marketing_consent=data.get('marketing_consent', False),
                privacy_version=settings.PRIVACY_POLICY_VERSION, ip_hash=limits.digest(ip),
            )
            session = ChatSession.objects.create(lead=lead, idempotency_key=key or None)
            ChatMessage.objects.create(session=session, role=ChatMessage.Role.ASSISTANT, content=prompts.greeting(lead))
        return Response(session_payload(session), status=status.HTTP_201_CREATED)


class SessionDetailView(APIView):
    def get(self, request, session_id):
        session = session_from_request(request, session_id)
        if not session:
            return err('unauthorized', 'Sesión inválida o expirada.', 401)
        return Response(session_payload(session))


def sse(events):
    for ev in events:
        yield f'data: {json.dumps(ev, ensure_ascii=False)}\n\n'


class MessageView(APIView):
    def post(self, request, session_id):
        session = session_from_request(request, session_id)
        if not session:
            return err('unauthorized', 'Sesión inválida o expirada.', 401)
        if session.closed:
            return err('session_closed', 'Esta conversación ya terminó.', 409)

        ser = MessageSerializer(data=request.data)
        if not ser.is_valid():
            return err('validation_error', 'Escribe un mensaje.', 400)
        text = CONTROL_CHARS.sub('', ser.validated_data['message']).strip()
        if not text:
            return err('validation_error', 'Escribe un mensaje.', 400)
        if len(text) > settings.AI_MAX_USER_MESSAGE_CHARS:
            return err('message_too_long', f'El mensaje es demasiado largo (máximo {settings.AI_MAX_USER_MESSAGE_CHARS} caracteres).', 400)

        try:
            limits.hit('message_ip', limits.client_ip(request))
            limits.hit('message_session', str(session.id))
        except limits.RateLimited as exc:
            return rate_limited(exc)

        # Tope de mensajes: se reserva el cupo de forma atómica para que peticiones paralelas no lo superen.
        reserved = ChatSession.objects.filter(pk=session.pk, user_messages__lt=settings.AI_MAX_USER_MESSAGES_PER_SESSION).update(user_messages=F('user_messages') + 1)
        if not reserved:
            return err('session_limit', 'Llegamos al límite de mensajes de esta conversación. Puedes pedir que Angside te contacte.', 429)
        if not limits.budget_available():
            ChatSession.objects.filter(pk=session.pk).update(user_messages=F('user_messages') - 1)
            return err('budget_exhausted', 'El asistente no está disponible por ahora. Puedes usar el cotizador o pedir que te contactemos.', 503)

        session.refresh_from_db()
        response = StreamingHttpResponse(sse(run_turn(session, text)), content_type='text/event-stream; charset=utf-8')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


class ContactRequestView(APIView):
    def post(self, request, session_id):
        session = session_from_request(request, session_id)
        if not session:
            return err('unauthorized', 'Sesión inválida o expirada.', 401)
        try:
            limits.hit('contact_request_session', str(session.id))
        except limits.RateLimited as exc:
            return rate_limited(exc)
        ser = ContactRequestSerializer(data=request.data)
        if not ser.is_valid():
            return err('validation_error', 'Mensaje inválido.', 400)
        message = ser.validated_data.get('message') or 'Solicitud desde el asistente'
        proposal_id = ser.validated_data.get('proposal_id')
        if proposal_id is not None:
            # Solo propuestas de esta misma conversación.
            proposal = Proposal.objects.filter(pk=proposal_id, session=session).first()
            if not proposal:
                return err('not_found', 'Propuesta no encontrada.', 404)
            proposal.requested = True
            proposal.save(update_fields=['requested'])
            message = f'Solicita la propuesta {proposal.get_tier_display()} (${proposal.development_total} USD). {message}'
        mark_contact_requested(session.lead, message)
        return Response({'ok': True})


class ProfileView(APIView):
    """El visitante corrige su clasificación. Es solo informativa: nunca cambia los precios."""

    def patch(self, request, session_id):
        session = session_from_request(request, session_id)
        if not session:
            return err('unauthorized', 'Sesión inválida o expirada.', 401)
        try:
            limits.hit('profile_session', str(session.id))
        except limits.RateLimited as exc:
            return rate_limited(exc)
        ser = ProfileUpdateSerializer(data=request.data)
        if not ser.is_valid():
            return err('validation_error', 'Clasificación inválida.', 400)
        lead = session.lead
        lead.business_size = ser.validated_data['business_size']
        lead.size_confirmed_by_client = True
        lead.save(update_fields=['business_size', 'size_confirmed_by_client', 'updated_at'])
        add_note(lead, f'El cliente corrigió su tamaño a: {lead.get_business_size_display()}', prefix='CLIENTE')
        return Response({'profile': proposals.profile_payload(lead)})


class ProposalPaymentModeView(APIView):
    """El visitante cambia la modalidad de pago en una tarjeta. Solo elige entre las que el motor ya calculó."""

    def post(self, request, session_id, proposal_id):
        session = session_from_request(request, session_id)
        if not session:
            return err('unauthorized', 'Sesión inválida o expirada.', 401)
        try:
            limits.hit('payment_mode_session', str(session.id))
        except limits.RateLimited as exc:
            return rate_limited(exc)
        proposal = Proposal.objects.filter(pk=proposal_id, session=session).first()
        if not proposal:
            return err('not_found', 'Propuesta no encontrada.', 404)
        mode = request.data.get('mode') if isinstance(request.data, dict) else None
        try:
            if not isinstance(mode, str):
                raise proposals.ToolError('Modalidad inválida.')
            card = payments.set_mode_from_visitor(proposal, mode)
        except proposals.ToolError as exc:
            return err('validation_error', str(exc), 400)
        return Response({'proposal': card})
