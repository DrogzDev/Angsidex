"""Cliente de OpenRouter con streaming. El modelo es configurable por entorno; el frontend no lo conoce."""
import json
import logging
from decimal import Decimal
from typing import Any, Iterator

import httpx
from django.conf import settings

from .textcalls import TextToolCallFilter

logger = logging.getLogger('angside_ai')


class AiUnavailable(Exception):
    """OpenRouter no respondió o devolvió un error."""


def stream_chat(messages: list[dict], tools: list[dict] | None = None) -> Iterator[dict[str, Any]]:
    """
    Emite {'type': 'delta', 'text': str} y, al final, {'type': 'result', 'content', 'tool_calls', 'usage'}.
    `usage` = {'in': int, 'out': int, 'cost': Decimal | None}.
    """
    if not settings.OPENROUTER_API_KEY:
        raise AiUnavailable('OPENROUTER_API_KEY no configurada')

    payload: dict[str, Any] = {
        'model': settings.AI_MODEL,
        'messages': messages,
        'stream': True,
        'max_tokens': settings.AI_MAX_OUTPUT_TOKENS,
        'temperature': 0.4,
        'usage': {'include': True},
    }
    if settings.AI_REASONING_EFFORT:
        # El razonamiento no se muestra al visitante: se excluye de la respuesta y se limita su esfuerzo.
        payload['reasoning'] = {'effort': settings.AI_REASONING_EFFORT, 'exclude': True}
    if settings.AI_FALLBACK_MODELS:
        payload['models'] = [settings.AI_MODEL, *settings.AI_FALLBACK_MODELS]
    if tools:
        payload['tools'] = tools
        payload['tool_choice'] = 'auto'
        # Solo proveedores que soporten realmente todos los parámetros (incluidas las herramientas).
        payload['provider'] = {'require_parameters': True}

    headers = {
        'Authorization': f'Bearer {settings.OPENROUTER_API_KEY}',
        'Content-Type': 'application/json',
        'HTTP-Referer': settings.AI_SITE_URL,
        'X-Title': settings.AI_SITE_NAME,
    }

    text_filter = TextToolCallFilter()
    content_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] = {'in': 0, 'out': 0, 'cost': None}

    try:
        with httpx.stream('POST', f'{settings.OPENROUTER_BASE_URL}/chat/completions', json=payload, headers=headers,
                          timeout=httpx.Timeout(connect=5.0, read=45.0, write=10.0, pool=5.0)) as resp:
            if resp.status_code != 200:
                resp.read()
                # No se registra el cuerpo completo ni cabeceras: podrían contener datos sensibles.
                logger.warning('OpenRouter respondió %s', resp.status_code)
                raise AiUnavailable(f'status {resp.status_code}')
            for line in resp.iter_lines():
                if not line or line.startswith(':') or not line.startswith('data:'):
                    continue  # comentarios keep-alive de OpenRouter
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if chunk.get('error'):
                    logger.warning('OpenRouter devolvió un error en el stream')
                    raise AiUnavailable('stream error')
                if chunk.get('usage'):
                    u = chunk['usage']
                    usage['in'] = int(u.get('prompt_tokens') or 0)
                    usage['out'] = int(u.get('completion_tokens') or 0)
                    if u.get('cost') is not None:
                        usage['cost'] = Decimal(str(u['cost']))
                for choice in chunk.get('choices') or []:
                    delta = choice.get('delta') or {}
                    if delta.get('content'):
                        # Si el modelo escribe una herramienta como texto, se retiene aquí y nunca llega al visitante.
                        visible = text_filter.feed(delta['content'])
                        if visible:
                            content_parts.append(visible)
                            yield {'type': 'delta', 'text': visible}
                    for tc in delta.get('tool_calls') or []:
                        slot = tool_calls.setdefault(tc.get('index', 0), {'id': '', 'name': '', 'arguments': ''})
                        if tc.get('id'):
                            slot['id'] = tc['id']
                        fn = tc.get('function') or {}
                        if fn.get('name'):
                            slot['name'] += fn['name']
                        if fn.get('arguments'):
                            slot['arguments'] += fn['arguments']
    except httpx.HTTPError as exc:
        logger.warning('Error de red con OpenRouter: %s', type(exc).__name__)
        raise AiUnavailable('network') from exc

    tail, text_calls = text_filter.finish()
    if tail:
        content_parts.append(tail)
        yield {'type': 'delta', 'text': tail}
    calls = [tool_calls[i] for i in sorted(tool_calls)]
    if text_calls:
        logger.info('El modelo escribió %d llamada(s) a herramientas como texto; se interpretaron.', len(text_calls))
        calls.extend(text_calls)

    yield {
        'type': 'result',
        'content': ''.join(content_parts),
        'tool_calls': calls,
        'usage': usage,
    }
