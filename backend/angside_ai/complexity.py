"""
Evaluación de complejidad de un proyecto. Es determinista y depende del ALCANCE (funcionalidades, usuarios,
integraciones, volumen, seguridad, infraestructura), nunca del tamaño del cliente ni de su presupuesto.
La complejidad informa la conversación y el CRM; los precios salen únicamente del motor de cotización.
"""
from typing import Any

BASIC, INTERMEDIATE, ADVANCED, CUSTOM = 'basic', 'intermediate', 'advanced', 'custom'

LABELS = {BASIC: 'Básica', INTERMEDIATE: 'Intermedia', ADVANCED: 'Avanzada', CUSTOM: 'Personalizada / requiere evaluación'}
SIZE_LABELS = {'small': 'Pequeño negocio', 'medium': 'Mediana empresa', 'large': 'Empresa grande'}

# Peso base por tipo de proyecto
BASE_POINTS = {'landing': 0, 'corporativa': 1, 'catalogo': 1, 'tienda': 2, 'sistema': 3, 'automatizacion': 1}
INTEGRATION_MODULES = {'whatsapp', 'facturacion', 'reservas', 'notificaciones'}
SECURITY_MODULES = {'roles', 'auditoria'}

PROCESS_LEVELS = ('low', 'medium', 'high')

# Señales permitidas que la IA puede reportar (todas opcionales) y su tipo/rango.
SIGNAL_SPEC: dict[str, tuple[str, Any]] = {
    'users_estimate': ('int', (0, 100_000)),
    'branches': ('int', (0, 200)),
    'monthly_transactions_estimate': ('int', (0, 100_000_000)),
    'existing_systems_integration': ('bool', None),
    'special_security': ('bool', None),
    'special_availability': ('bool', None),
    'special_audit': ('bool', None),
    'needs_custom_development': ('bool', None),
    'infrastructure': ('enum', ('standard', 'special')),
    'process_complexity': ('enum', PROCESS_LEVELS),
}


def clean_signals(raw: Any) -> dict[str, Any]:
    """Descarta señales desconocidas o fuera de rango; nunca falla."""
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, (kind, rule) in SIGNAL_SPEC.items():
        if key not in raw:
            continue
        v = raw[key]
        if kind == 'bool' and isinstance(v, bool):
            out[key] = v
        elif kind == 'int' and isinstance(v, int) and not isinstance(v, bool) and rule[0] <= v <= rule[1]:
            out[key] = v
        elif kind == 'enum' and v in rule:
            out[key] = v
    return out


def assess(state: dict, signals: dict[str, Any], custom_items: list[str] | None = None) -> tuple[str, list[str]]:
    """Devuelve (nivel, factores legibles). `state` es el estado normalizado del cotizador."""
    factors: list[str] = []
    modules = list(state.get('moduleIds', []))
    base = state.get('baseId')
    points = BASE_POINTS.get(base, 0)

    if modules:
        points += len(modules) // 2
        factors.append(f'{len(modules)} funcionalidad(es) adicional(es)')
    integrations = [m for m in modules if m in INTEGRATION_MODULES]
    if integrations:
        points += min(3, len(integrations))
        factors.append(f'integraciones: {", ".join(integrations)}')
    security = [m for m in modules if m in SECURITY_MODULES]
    if security:
        points += len(security)
        factors.append(f'usuarios/seguridad: {", ".join(security)}')

    users = signals.get('users_estimate', 0)
    if users > 25:
        points += 2
        factors.append(f'unos {users} usuarios')
    elif users > 5:
        points += 1
        factors.append(f'unos {users} usuarios')

    branches = signals.get('branches', 0)
    if branches >= 3:
        points += 2
        factors.append(f'{branches} sucursales')
    elif branches == 2:
        points += 1
        factors.append('2 sucursales')

    volume = signals.get('monthly_transactions_estimate', 0)
    if volume > 50_000:
        points += 2
        factors.append('volumen alto de operaciones')
    elif volume > 5_000:
        points += 1
        factors.append('volumen moderado de operaciones')

    process = signals.get('process_complexity')
    if process == 'high':
        points += 2
        factors.append('procesos complejos')
    elif process == 'medium':
        points += 1
        factors.append('procesos con varios pasos')

    custom_reasons: list[str] = []
    if custom_items:
        custom_reasons.append('incluye desarrollo que no está en el cotizador')
    if signals.get('needs_custom_development'):
        custom_reasons.append('requiere desarrollo a medida')
    if signals.get('existing_systems_integration'):
        custom_reasons.append('integración con sistemas existentes')
    if signals.get('special_security'):
        custom_reasons.append('requisitos especiales de seguridad')
    if signals.get('special_availability'):
        custom_reasons.append('requisitos especiales de disponibilidad')
    if signals.get('special_audit'):
        custom_reasons.append('requisitos especiales de auditoría')
    if signals.get('infrastructure') == 'special':
        custom_reasons.append('infraestructura especial')
    if branches >= 4:
        custom_reasons.append('más de 3 sucursales')
    if users > 200:
        custom_reasons.append('muy alto número de usuarios')

    if custom_reasons:
        return CUSTOM, factors + custom_reasons
    if points >= 7:
        return ADVANCED, factors
    if points >= 3:
        return INTERMEDIATE, factors
    return BASIC, factors
