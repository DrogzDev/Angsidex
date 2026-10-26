"""Verificación de Cloudflare Turnstile en el servidor. Falla cerrado y no reutiliza tokens."""
import hashlib
import logging

import httpx
from django.conf import settings
from django.db import IntegrityError, transaction

from .models import TurnstileUse

logger = logging.getLogger('angside_ai')
MAX_TOKEN_LEN = 2048
DUMMY_TEST_TOKEN = 'XXXX.DUMMY.TOKEN.XXXX'
ALWAYS_PASS_TEST_SECRET_PREFIX = '1x0000000000000000000000000000000'


def verify(token: str, remote_ip: str = '') -> bool:
    if not settings.TURNSTILE_SECRET:
        logger.error('TURNSTILE_SECRET no está configurado; se rechaza la verificación.')
        return False
    if not token or len(token) > MAX_TOKEN_LEN:
        return False

    # Se consume antes de consultar a Cloudflare: dos solicitudes simultáneas con el mismo token no pasan ambas.
    # Excepción solo de desarrollo: la clave de prueba "siempre pasa" de Cloudflare entrega SIEMPRE el mismo token ficticio.
    if not (token == DUMMY_TEST_TOKEN and settings.TURNSTILE_SECRET.startswith(ALWAYS_PASS_TEST_SECRET_PREFIX)):
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        try:
            with transaction.atomic():
                TurnstileUse.objects.create(token_hash=token_hash)
        except IntegrityError:
            return False

    data = {'secret': settings.TURNSTILE_SECRET, 'response': token}
    if remote_ip:
        data['remoteip'] = remote_ip
    try:
        resp = httpx.post(settings.TURNSTILE_VERIFY_URL, data=data, timeout=5.0)
        resp.raise_for_status()
        return bool(resp.json().get('success'))
    except (httpx.HTTPError, ValueError):
        logger.warning('Turnstile no respondió correctamente; se rechaza.')
        return False
