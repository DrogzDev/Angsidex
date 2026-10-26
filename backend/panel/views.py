"""
API del panel interno (y, más adelante, del portal de clientes).

Autenticación por sesión de Django con protección CSRF:
  1. GET  /api/panel/csrf   → fija la cookie `csrftoken` y devuelve el token.
  2. POST /api/panel/login  → exige el token en la cabecera X-CSRFToken; abre la sesión (cookie HttpOnly).
  3. El resto de endpoints exigen sesión; los de administración, además, `is_staff`.
Todas las vistas son JSON. Los errores de inicio de sesión son genéricos para no revelar qué usuarios existen.
"""
import json
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from angside_ai import limits
from angside_ai.models import ChatSession
from commercial.models import SavedQuote
from leads.models import Lead, Proposal

PAGE_SIZE = 20
SESSION_SECONDS = 60 * 60 * 8


def csrf_failure(request, reason=''):
    """Fallo CSRF: JSON para la API del panel, página estándar de Django para el resto."""
    if request.path.startswith('/api/'):
        return JsonResponse({'code': 'csrf_failed', 'detail': 'Sesión de seguridad vencida. Recarga la página e inténtalo de nuevo.'}, status=403)
    from django.views.csrf import csrf_failure as default

    return default(request, reason=reason)


def _json(request) -> dict:
    try:
        data = json.loads(request.body or b'{}')
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _error(code: str, detail: str, status: int, **extra):
    return JsonResponse({'code': code, 'detail': detail, **extra}, status=status)


def staff_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return _error('unauthenticated', 'Inicia sesión para continuar.', 401)
        if not user.is_staff:
            return _error('forbidden', 'No tienes permiso para ver esto.', 403)
        return view(request, *args, **kwargs)

    return wrapper


def _user_payload(user) -> dict:
    return {
        'username': user.get_username(),
        'name': user.get_full_name() or user.get_username(),
        'role': 'staff' if user.is_staff else 'client',
    }


# --- Sesión ---

@require_GET
@ensure_csrf_cookie
def csrf(request):
    return JsonResponse({'csrf': get_token(request)})


@require_GET
@ensure_csrf_cookie
def me(request):
    user = request.user
    return JsonResponse({'authenticated': user.is_authenticated, 'user': _user_payload(user) if user.is_authenticated else None, 'csrf': get_token(request)})


@require_POST
def login_view(request):
    data = _json(request)
    username = str(data.get('username', '')).strip()[:150]
    password = str(data.get('password', ''))[:256]
    if not username or not password:
        return _error('invalid_credentials', 'Escribe tu usuario y tu contraseña.', 400)
    try:
        limits.hit('panel_login_ip', limits.client_ip(request))
        limits.hit('panel_login_user', username.lower())
    except limits.RateLimited as exc:
        resp = _error('rate_limited', 'Demasiados intentos. Espera unos minutos antes de volver a intentarlo.', 429, retry_after=exc.retry_after)
        resp['Retry-After'] = str(exc.retry_after)
        return resp
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        return _error('invalid_credentials', 'Usuario o contraseña incorrectos.', 401)
    login(request, user)  # rota la sesión y el token CSRF
    request.session.set_expiry(SESSION_SECONDS)
    return JsonResponse({'authenticated': True, 'user': _user_payload(user), 'csrf': get_token(request)})


@require_POST
def logout_view(request):
    logout(request)
    return JsonResponse({'authenticated': False, 'csrf': get_token(request)})


# --- Panel de administración ---

def _choice_label(model_field_choices, value: str) -> str:
    return dict(model_field_choices).get(value, value or '')


def _lead_row(lead: Lead) -> dict:
    modes = sorted({p.payment_mode for p in lead.proposals.all() if p.payment_mode})
    return {
        'id': lead.pk,
        'created_at': lead.created_at.isoformat(),
        'name': lead.name,
        'business': lead.business,
        'email': lead.email,
        'phone': lead.phone,
        'whatsapp': lead.whatsapp,
        'sector': lead.sector,
        'budget_range': _choice_label(Lead.Budget.choices, lead.budget_range),
        'complexity': lead.complexity,
        'complexity_label': _choice_label(Lead.Complexity.choices, lead.complexity),
        'budget_calculated_usd': lead.budget_calculated_usd,
        'status': lead.status,
        'status_label': _choice_label(Lead.Status.choices, lead.status),
        'negotiation_requested': lead.negotiation_requested,
        'payment_modes': modes,
        'proposals': len(lead.proposals.all()),
    }


@require_GET
@staff_required
def overview(request):
    now = timezone.now()
    leads = Lead.objects.all()
    counts = dict(leads.values_list('status').annotate(n=Count('id')))
    modes = dict(Proposal.objects.exclude(payment_mode='').values_list('payment_mode').annotate(n=Count('id')))
    since = now - timedelta(days=7)
    recent = leads.prefetch_related('proposals')[:6]
    return JsonResponse({
        'leads': {
            'total': leads.count(),
            'today': leads.filter(created_at__date=timezone.localdate()).count(),
            'last_7_days': leads.filter(created_at__gte=since).count(),
            'negotiating': leads.filter(negotiation_requested=True).count(),
            'by_status': [{'status': s, 'label': label, 'count': counts.get(s, 0)} for s, label in Lead.Status.choices],
        },
        'quotes': {'total': SavedQuote.objects.count(), 'last_7_days': SavedQuote.objects.filter(created_at__gte=since).count()},
        'payment_modes': [{'mode': m, 'count': modes.get(m, 0)} for m in ('cash', 'm3', 'm6', 'm9')],
        'ai': {
            'spent_today_usd': float(limits.spent_today()),
            'spent_month_usd': float(limits.spent_this_month()),
            'daily_budget_usd': settings.AI_DAILY_BUDGET_USD,
            'monthly_budget_usd': settings.AI_MONTHLY_BUDGET_USD,
            'sessions': ChatSession.objects.count(),
        },
        'recent_leads': [_lead_row(l) for l in recent],
    })


def _page(request) -> int:
    try:
        return max(1, int(request.GET.get('page', '1')))
    except ValueError:
        return 1


@require_GET
@staff_required
def leads_list(request):
    qs = Lead.objects.prefetch_related('proposals').order_by('-created_at')
    status = request.GET.get('status', '')
    if status in Lead.Status.values:
        qs = qs.filter(status=status)
    q = request.GET.get('q', '').strip()[:100]
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(business__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q) | Q(whatsapp__icontains=q) | Q(sector__icontains=q))
    page = Paginator(qs, PAGE_SIZE).get_page(_page(request))
    return JsonResponse({
        'items': [_lead_row(l) for l in page.object_list],
        'page': page.number,
        'pages': page.paginator.num_pages,
        'total': page.paginator.count,
        'statuses': [{'value': v, 'label': label} for v, label in Lead.Status.choices],
    })


def _conversation(lead: Lead) -> list[dict]:
    out = []
    for session in lead.sessions.all():
        messages = [
            {'role': m.role, 'at': m.created_at.isoformat(), 'text': m.content}
            for m in session.messages.all()
            if m.role in ('user', 'assistant') and m.content.strip()
        ]
        out.append({'session_id': str(session.pk), 'started_at': session.created_at.isoformat(), 'tokens': session.total_tokens, 'cost_usd': float(session.cost_usd), 'messages': messages})
    return out


def _proposal(p: Proposal) -> dict:
    features = [f.get('label', '') for f in (p.payload or {}).get('features', []) if isinstance(f, dict)]
    return {
        'id': p.pk, 'round': p.round, 'tier': p.tier, 'created_at': p.created_at.isoformat(), 'development_total': p.development_total,
        'payment_mode': p.payment_mode, 'pricing_version': p.pricing_version, 'complexity': p.complexity, 'within_budget': p.within_budget,
        'requires_custom_quote': p.requires_custom_quote, 'requested': p.requested, 'features': features,
    }


def _lead_detail(lead: Lead) -> dict:
    return {
        **_lead_row(lead),
        'location': lead.location,
        'need': lead.need,
        'needs_summary': lead.needs_summary,
        'has_website': lead.has_website,
        'start_when': _choice_label(Lead.StartWhen.choices, lead.start_when),
        'business_size': _choice_label(Lead.BusinessSize.choices, lead.business_size),
        'budget_stated_usd': lead.budget_stated_usd,
        'recommended_features': lead.recommended_features,
        'negotiation': {
            'requested': lead.negotiation_requested, 'initial_budget': lead.negotiation_initial_budget,
            'ideal_budget': lead.negotiation_ideal_budget, 'reason': lead.negotiation_reason,
        },
        'objections': lead.objections,
        'marketing_consent': lead.marketing_consent,
        'notes': lead.notes,
        'updated_at': lead.updated_at.isoformat(),
        'proposals_detail': [_proposal(p) for p in lead.proposals.all().order_by('created_at')],
        'conversations': _conversation(lead),
    }


@require_http_methods(['GET', 'PATCH'])
@staff_required
def lead_detail(request, pk: int):
    lead = Lead.objects.prefetch_related('proposals', 'sessions__messages').filter(pk=pk).first()
    if lead is None:
        return _error('not_found', 'Prospecto no encontrado.', 404)
    if request.method == 'PATCH':
        data = _json(request)
        fields = []
        if 'status' in data:
            if data['status'] not in Lead.Status.values:
                return _error('invalid_status', 'Estado no válido.', 400)
            lead.status = data['status']
            fields.append('status')
        if 'notes' in data:
            if not isinstance(data['notes'], str) or len(data['notes']) > 4000:
                return _error('invalid_notes', 'Las notas deben ser texto de hasta 4.000 caracteres.', 400)
            lead.notes = data['notes']
            fields.append('notes')
        if fields:
            lead.save(update_fields=[*fields, 'updated_at'])
    return JsonResponse(_lead_detail(lead))


@require_GET
@staff_required
def quotes_list(request):
    page = Paginator(SavedQuote.objects.order_by('-created_at'), PAGE_SIZE).get_page(_page(request))
    return JsonResponse({
        'items': [
            {
                'reference': q.reference, 'created_at': q.created_at.isoformat(), 'payment_mode': q.payment_mode,
                'development_original': float(q.development_original), 'development_total': float(q.development_total),
                'config': q.config_query, 'pricing_version': q.pricing_version_id,
            }
            for q in page.object_list
        ],
        'page': page.number, 'pages': page.paginator.num_pages, 'total': page.paginator.count,
    })
