"""Orquesta un turno de conversación: historial, streaming, herramientas, consumo y límites."""
import logging
import uuid
from typing import Iterator

from django.conf import settings

from . import guard, limits, prompts
from .models import ChatMessage, ChatSession
from .openrouter import AiUnavailable, stream_chat
from .tools import execute_tool, tool_definitions

logger = logging.getLogger('angside_ai')

MAX_ROUNDS = 5  # classify_client + propose_options + (pagos / registro) + respuesta final
HISTORY_LIMIT = 40
FALLBACK_TEXT = 'Disculpa, no logré responder bien esa consulta. ¿Puedes contármela de otra forma?'


def build_messages(session: ChatSession) -> list[dict]:
    window = list(session.messages.order_by('-id')[:HISTORY_LIMIT])[::-1]
    # La ventana no puede empezar con resultados de herramientas huérfanos.
    while window and (window[0].role == 'tool' or (window[0].role == 'assistant' and window[0].meta.get('tool_calls'))):
        window.pop(0)

    out: list[dict] = [{'role': 'system', 'content': prompts.build_system_prompt(session.lead)}]
    for m in window:
        if m.role == 'user':
            out.append({'role': 'user', 'content': m.content})
        elif m.role == 'assistant':
            if not m.content and not m.meta.get('tool_calls'):
                continue  # marcadores internos (p. ej. aviso del guardia de precios)
            msg: dict = {'role': 'assistant', 'content': m.content or None}
            if m.meta.get('tool_calls'):
                msg['tool_calls'] = m.meta['tool_calls']
            out.append(msg)
        else:
            out.append({'role': 'tool', 'tool_call_id': m.meta.get('tool_call_id', ''), 'content': m.content})
    return out


def _over_limits(session: ChatSession, ip_hash: str = '') -> str | None:
    if session.total_tokens >= settings.AI_MAX_TOKENS_PER_SESSION or limits.session_cost_exceeded(session):
        return 'session_limit'
    if not limits.ip_quota_available(ip_hash):
        return 'ip_quota'
    if not limits.budget_available():
        return 'budget_exhausted'
    return None


LIMIT_MESSAGES = {
    'session_limit': 'Llegamos al límite de esta conversación. Puedes dejar que Angside te contacte para continuar con una propuesta personalizada.',
    'ip_quota': 'Alcanzaste el uso diario del asistente desde esta conexión. Puedes usar el cotizador o dejar que Angside te contacte.',
    'budget_exhausted': 'El asistente no está disponible por ahora. Puedes usar el cotizador o pedir que Angside te contacte.',
    'ai_unavailable': 'No pude conectar con el asistente en este momento. Intenta de nuevo en unos minutos o solicita que te contactemos.',
}


OFF_TOPIC_TEXT = 'Solo puedo ayudarte con los servicios de Angside: páginas web, tiendas online, sistemas y automatizaciones. ¿Qué necesita tu negocio?'
OFF_TOPIC_CLOSED_TEXT = 'Esta conversación se cerró porque los mensajes no están relacionados con los servicios de Angside. Si necesitas algo de tu negocio, usa el cotizador o escríbenos por WhatsApp.'


def run_turn(session: ChatSession, user_text: str, ip_hash: str = '') -> Iterator[dict]:
    ChatMessage.objects.create(session=session, role=ChatMessage.Role.USER, content=user_text)
    produced_text = False
    texts: list[str] = []

    for round_no in range(MAX_ROUNDS):
        problem = _over_limits(session, ip_hash)
        if problem:
            yield {'type': 'error', 'code': problem, 'message': LIMIT_MESSAGES[problem]}
            return

        # La última ronda no ofrece herramientas: obliga al modelo a cerrar con texto.
        tools = tool_definitions() if round_no < MAX_ROUNDS - 1 else None
        result = None
        try:
            for ev in stream_chat(build_messages(session), tools):
                if ev['type'] == 'delta':
                    produced_text = True
                    texts.append(ev['text'])
                    yield ev
                else:
                    result = ev
        except AiUnavailable:
            yield {'type': 'error', 'code': 'ai_unavailable', 'message': LIMIT_MESSAGES['ai_unavailable']}
            return
        if result is None:
            yield {'type': 'error', 'code': 'ai_unavailable', 'message': LIMIT_MESSAGES['ai_unavailable']}
            return

        u = result['usage']
        limits.record_usage(session, u['in'], u['out'], u['cost'], ip_hash)

        calls = [
            {'id': tc['id'] or f'call_{uuid.uuid4().hex[:12]}', 'type': 'function', 'function': {'name': tc['name'], 'arguments': tc['arguments'] or '{}'}}
            for tc in result['tool_calls'] if tc['name']
        ]
        ChatMessage.objects.create(
            session=session, role=ChatMessage.Role.ASSISTANT, content=result['content'],
            meta={'tool_calls': calls} if calls else {},
        )
        if not calls:
            break
        for call in calls:
            outcome, evs = execute_tool(call['function']['name'], call['function']['arguments'], session)
            meta: dict = {'tool_call_id': call['id']}
            # Las tarjetas se guardan junto al resultado de la herramienta para poder reconstruir la conversación.
            ui = [e for e in evs if e['type'] in ('proposals', 'profile')]  # payment_mode no se guarda: la modalidad vive en Proposal.payment_mode
            if ui:
                meta['ui_events'] = ui
            ChatMessage.objects.create(session=session, role=ChatMessage.Role.TOOL, content=_dump(outcome), meta=meta)
            yield from evs

        if any(c['function']['name'] == 'mark_off_topic' for c in calls):
            # Mensaje ajeno al negocio: se corta aquí (sin otra ronda de IA) y, si el modelo no escribió respuesta, se usa texto fijo.
            session.refresh_from_db(fields=['off_topic_strikes'])
            if session.off_topic_strikes >= settings.AI_MAX_OFFTOPIC_STRIKES:
                ChatSession.objects.filter(pk=session.pk).update(closed=True)
                ChatMessage.objects.create(session=session, role=ChatMessage.Role.ASSISTANT, content=OFF_TOPIC_CLOSED_TEXT)
                yield {'type': 'error', 'code': 'session_closed', 'message': OFF_TOPIC_CLOSED_TEXT}
                return
            if not produced_text:
                ChatMessage.objects.create(session=session, role=ChatMessage.Role.ASSISTANT, content=OFF_TOPIC_TEXT)
                yield {'type': 'delta', 'text': OFF_TOPIC_TEXT}
            yield _done(session)
            return

    if not produced_text:
        ChatMessage.objects.create(session=session, role=ChatMessage.Role.ASSISTANT, content=FALLBACK_TEXT)
        yield {'type': 'delta', 'text': FALLBACK_TEXT}
    else:
        notice = _price_notice(session, ''.join(texts))
        if notice:
            yield notice
    yield _done(session)


def _done(session: ChatSession) -> dict:
    session.refresh_from_db(fields=['user_messages', 'total_tokens', 'cost_usd'])
    return {'type': 'done', 'remaining_messages': limits.remaining_messages(session)}


def _price_notice(session: ChatSession, text: str) -> dict | None:
    """Si el texto libre menciona montos no verificables o descuentos, avisa y deja constancia (los oficiales están en las tarjetas)."""
    found = guard.unverified(text, session)
    if not found['amounts'] and not found['discount_words'] and not found['percents']:
        return None
    logger.warning('Texto del asistente con montos no verificados: %s', found)
    ChatMessage.objects.create(session=session, role=ChatMessage.Role.ASSISTANT, content='', meta={'guard': found})
    return {
        'type': 'price_notice',
        'message': 'Los precios oficiales son los que aparecen en las tarjetas de propuesta, calculados por el cotizador de Angside. '
                   'El asistente no puede inventar descuentos ni cambiar montos; las modalidades de pago vigentes son las de las tarjetas y cualquier condición especial la define una persona del equipo.',
    }


def _dump(data: dict) -> str:
    import json
    return json.dumps(data, ensure_ascii=False)
