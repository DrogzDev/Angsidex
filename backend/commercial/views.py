import re
from decimal import Decimal

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from angside_ai import limits, quote

from . import engine, services
from .models import SavedQuote

REFERENCE_RE = re.compile(r'^ANG-[A-Z0-9]{6,10}$')


def err(code: str, message: str, http: int) -> Response:
    return Response({'code': code, 'message': message}, status=http)


class ConfigView(APIView):
    """Condiciones comerciales vigentes: el cotizador de Astro las descarga al cargar (no hay una segunda fuente de verdad)."""

    def get(self, request):
        try:
            limits.hit('config_read_ip', limits.client_ip(request))
        except limits.RateLimited as exc:
            resp = err('rate_limited', 'Demasiadas solicitudes.', status.HTTP_429_TOO_MANY_REQUESTS)
            resp['Retry-After'] = str(exc.retry_after)
            return resp
        resp = Response(services.current_config())
        resp['Cache-Control'] = 'public, max-age=60'
        return resp


def quote_breakdown(q: dict, config: dict) -> dict:
    payment = q['payment']
    return {
        'state': q['state'],
        'lines': q['lines'],
        'pricing_version': config['version'],
        'payment': engine.present_payment(payment, config) if payment else None,
        'monthly': {'hosting': q['hostingMonthly'], 'billing': q['billingMonthly'], 'maintenance': q['maintenanceMonthly'], 'total': q['monthlyTotal']},
        'ai_usage_estimate': (
            {'conversations': q['usage']['conversations'], 'monthly_usd': engine.from_cents(q['usage']['monthlyCents']), 'model': config['chatbot']['model']}
            if q['usage'] else None
        ),
    }


class QuoteRegisterView(APIView):
    """
    Registra una cotización que el visitante envía por WhatsApp. Solo guarda la configuración del cotizador y su
    resultado: ningún dato personal. Los importes se recalculan aquí; no se confía en los que envía el navegador.
    """

    def post(self, request):
        try:
            limits.hit('quote_register_ip', limits.client_ip(request))
        except limits.RateLimited as exc:
            resp = err('rate_limited', 'Demasiadas solicitudes.', status.HTTP_429_TOO_MANY_REQUESTS)
            resp['Retry-After'] = str(exc.retry_after)
            return resp

        data = request.data if isinstance(request.data, dict) else {}
        reference, config_query, version = data.get('reference'), data.get('config'), data.get('version')
        if not isinstance(reference, str) or not REFERENCE_RE.match(reference):
            return err('validation_error', 'Referencia inválida.', 400)
        if not isinstance(config_query, str) or len(config_query) > 600:
            return err('validation_error', 'Configuración inválida.', 400)
        if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
            return err('validation_error', 'Versión inválida.', 400)

        existing = SavedQuote.objects.filter(reference=reference).first()
        if existing:
            return Response(self._payload(existing))

        state = quote.decode_state(config_query)
        latest = services.current_config()
        # Se calcula con la versión que el visitante estaba viendo si todavía existe: así el total coincide con su pantalla.
        config = services.config_for_version(version) or latest
        q = quote.compute_quote(state, config)
        if not q['complete']:
            return err('incomplete_quote', 'La cotización está incompleta.', 400)

        payment = q['payment']
        original = Decimal(payment['originalCents'] if payment else engine.to_cents(q['developmentTotal'])) / 100
        total = Decimal(payment['totalCents'] if payment else engine.to_cents(q['developmentTotal'])) / 100
        saved = SavedQuote.objects.create(
            reference=reference, config_query=quote.encode_state(q['state']), payment_mode=q['state']['paymentModeId'] or '',
            pricing_version_id=config['version'], development_original=original, development_total=total,
            breakdown=quote_breakdown(q, config),
        )
        return Response({**self._payload(saved), 'is_latest': config['version'] == latest['version']}, status=status.HTTP_201_CREATED)

    @staticmethod
    def _payload(saved: SavedQuote) -> dict:
        return {
            'reference': saved.reference, 'pricing_version': saved.pricing_version_id, 'payment_mode': saved.payment_mode,
            'development_original': float(saved.development_original), 'development_total': float(saved.development_total),
        }
