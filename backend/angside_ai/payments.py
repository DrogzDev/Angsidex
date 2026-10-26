"""
Herramientas de modalidades de pago del asesor. Todos los importes salen del motor determinista (commercial.engine),
calculados cuando se creó la propuesta con una versión de precios fija. El modelo solo elige la propuesta y la modalidad:
no puede aportar porcentajes, descuentos ni condiciones.
"""
from typing import Any

from leads.models import Lead, Proposal

from commercial import engine

from .proposals import ToolError, clean_text, proposal_payload

MAX_PLAN_NOTE = 400


def _latest_round(lead: Lead) -> list[Proposal]:
    last = lead.proposals.order_by('-round').first()
    return list(lead.proposals.filter(round=last.round)) if last else []


def pick_proposal(lead: Lead, tier: str | None) -> Proposal:
    """Propuesta de la ronda más reciente: la del tier indicado, o la recomendada / primera."""
    current = _latest_round(lead)
    if not current:
        raise ToolError('Todavía no hay propuestas. Primero usa propose_options para calcular una.')
    if tier:
        found = next((p for p in current if p.tier == tier), None)
        if not found:
            raise ToolError(f"No hay una propuesta '{tier}' en la ronda más reciente: {[p.tier for p in current]}")
        return found
    return next((p for p in current if p.tier == 'recommended'), current[0])


def get_payment_options(args: dict, session, expect) -> tuple[dict, list[dict]]:
    expect(args, {'tier', 'budget_usd'}, set())
    proposal = pick_proposal(session.lead, args.get('tier'))
    budget = args.get('budget_usd')
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or not 0 <= budget <= 10_000_000):
        raise ToolError('budget_usd debe ser un entero entre 0 y 10000000')
    ceiling = budget if budget is not None else session.lead.budget_ceiling_usd
    options = proposal.payload.get('payment_options', [])
    rows = []
    for o in options:
        row: dict[str, Any] = {
            'modalidad': o['mode'], 'nombre': o['label'], 'disponible': o['available'],
            'total_desarrollo_usd': o['total'], 'precio_original_usd': o['original'],
        }
        if not o['available']:
            row['motivo_no_disponible'] = o['unavailable_reason']
        if o['kind'] == 'cash':
            row.update(descuento_porcentaje=o['discount_percent'], descuento_usd=o['discount'], ahorro_usd=o['savings'], pago='único, al confirmar el proyecto')
        else:
            row.update(
                incremento_porcentaje=o['surcharge_percent'], incremento_usd=o['surcharge'], inicial_porcentaje=o['initial_percent'],
                inicial_usd=o['initial'], cuotas=o['cadence'], cuota_usd=o['installment'],
                calendario=[{'pago': s['label'], 'vence': s['due'], 'usd': s['amount']} for s in o['schedule']],
                descuento_de_contado='no aplica en planes financiados', sujeto_a_aprobacion_de_angside=True,
            )
        if ceiling:
            row['total_cabe_en_el_presupuesto'] = o['total'] <= ceiling
            row['inicial_cabe_en_el_presupuesto'] = (o['initial'] if o['kind'] == 'financing' else o['total']) <= ceiling
        rows.append(row)
    return {
        'ok': True,
        'propuesta': proposal.tier,
        'presupuesto_del_cliente_usd': ceiling,
        'modalidades': rows,
        'modalidad_elegida': proposal.payment_mode or None,
        'reglas': (
            'El descuento de contado aplica solo al desarrollo y una sola vez; los planes financiados cuestan más en total y no reciben descuento. '
            'Hosting, mantenimiento, consumo de IA, dominios y terceros no tienen descuento ni incremento. '
            'Todo plan financiado está sujeto a evaluación, aprobación manual de Angside y contrato. '
            'Si el cliente quiere otro plazo o condiciones, usa request_payment_plan_negotiation; no los inventes.'
        ),
    }, []


def select_payment_mode(args: dict, session, expect) -> tuple[dict, list[dict]]:
    expect(args, {'tier', 'mode'}, {'mode'})
    mode = args['mode']
    if mode not in engine.PAYMENT_MODES:
        raise ToolError(f'mode debe ser uno de {engine.PAYMENT_MODES}')
    proposal = pick_proposal(session.lead, args.get('tier'))
    option = next((o for o in proposal.payload.get('payment_options', []) if o['mode'] == mode), None)
    if not option or not option['available']:
        raise ToolError(option['unavailable_reason'] if option else 'Modalidad no disponible para esta propuesta.')
    proposal.payment_mode = mode
    proposal.save(update_fields=['payment_mode'])
    event = {'type': 'payment_mode', 'proposal_id': proposal.id, 'mode': mode}
    return {
        'ok': True, 'propuesta': proposal.tier, 'modalidad': option['label'], 'total_desarrollo_usd': option['total'],
        'nota': 'La tarjeta ya muestra el calendario de pagos. Recuérdale que los planes financiados quedan sujetos a aprobación de Angside.',
    }, [event]


def request_plan_negotiation(args: dict, session, expect, mark_contact_requested, add_note) -> tuple[dict, list[dict]]:
    expect(args, {'desired_months', 'desired_initial_percent', 'note'}, {'note'})
    lead = session.lead
    note = clean_text(args['note'], 'note', MAX_PLAN_NOTE)
    parts = [note]
    for key, label, high in (('desired_months', 'plazo deseado (meses)', 120), ('desired_initial_percent', 'inicial deseada (%)', 100)):
        if key in args:
            v = args[key]
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= high:
                raise ToolError(f'{key} debe ser un entero entre 0 y {high}')
            parts.append(f'{label}: {v}')
    detail = ' · '.join(parts)
    lead.negotiation_requested = True
    lead.negotiation_reason = f'Plan de pago distinto: {detail}'[:1000]
    if lead.status == Lead.Status.NEW:
        lead.status = Lead.Status.NEGOTIATING
    lead.save()
    add_note(lead, f'Solicita un plan de pago diferente: {detail}', prefix='NEGOCIACIÓN')
    mark_contact_requested(lead, f'Plan de pago personalizado: {detail}')
    return {
        'ok': True,
        'mensaje': 'Solicitud registrada y derivada al equipo de Angside. Solo una persona puede aprobar un plan distinto; no prometas plazos, porcentajes ni condiciones.',
    }, [{'type': 'negotiation'}, {'type': 'contact_requested'}]


def set_mode_from_visitor(proposal: Proposal, mode: str) -> dict:
    """El visitante cambia la modalidad en una tarjeta. Mismas validaciones que la herramienta del asesor."""
    option = next((o for o in proposal.payload.get('payment_options', []) if o['mode'] == mode), None)
    if not option or not option['available']:
        raise ToolError('Modalidad no disponible para esta propuesta.')
    proposal.payment_mode = mode
    proposal.save(update_fields=['payment_mode'])
    return proposal_payload(proposal)
