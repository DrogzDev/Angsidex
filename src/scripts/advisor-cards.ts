/**
 * Tarjetas de propuesta del asistente. Todo el contenido llega de la respuesta estructurada validada por Django
 * y se inserta con textContent: nunca se interpreta HTML ni texto libre del modelo como datos de la tarjeta.
 */
import type { BusinessSize, PaymentMode, PaymentOption, ProfileInfo, ProposalCard, ProposalsEvent } from '../lib/advisor-api';
import { paymentCopy } from '../data/commercial';
import { formatUSD } from '../lib/quote-engine';

export interface CardHandlers {
  onApply: (card: ProposalCard) => void;
  onRequest: (card: ProposalCard, button: HTMLButtonElement) => void;
  onNegotiate: (card: ProposalCard) => void;
  onPaymentMode: (card: ProposalCard, mode: PaymentMode) => Promise<void>;
  onSizeChange: (size: BusinessSize) => Promise<void>;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

const SIZES: { value: BusinessSize; label: string }[] = [
  { value: 'small', label: 'Pequeño negocio' },
  { value: 'medium', label: 'Mediana empresa' },
  { value: 'large', label: 'Empresa grande' },
];

/** Chip de clasificación con opción de corregirla. Es orientativa y no cambia los precios. */
export function renderProfile(profile: ProfileInfo, handlers: Pick<CardHandlers, 'onSizeChange'>): HTMLElement {
  const box = el('div', 'adv-profile');
  box.dataset.profile = '';
  const summary = el('p', 'adv-profile-line');
  const size = el('span', '', profile.size_label || 'Sin clasificar');
  size.dataset.profileSize = '';
  summary.append(el('span', 'mono', 'Clasificación'), size);
  if (profile.complexity_label) {
    const cx = el('span', '', profile.complexity_label);
    summary.append(el('span', 'mono', 'Complejidad'), cx);
  }
  const edit = el('button', 'adv-link', 'Corregir');
  edit.type = 'button';
  edit.setAttribute('aria-expanded', 'false');

  const form = el('div', 'adv-profile-edit');
  form.hidden = true;
  const label = el('label', 'sr-only', 'Tamaño de tu negocio');
  const select = el('select');
  select.id = `adv-size-${Math.random().toString(36).slice(2, 8)}`;
  label.htmlFor = select.id;
  for (const s of SIZES) {
    const o = el('option', '', s.label);
    o.value = s.value;
    if (s.value === profile.size) o.selected = true;
    select.appendChild(o);
  }
  const save = el('button', 'btn btn-dark', 'Guardar');
  save.type = 'button';
  const note = el('p', 'adv-profile-note', 'Es una clasificación orientativa: no cambia los precios, que dependen solo de las funcionalidades que elijas.');
  const status = el('p', 'adv-err');
  status.setAttribute('role', 'alert');
  form.append(label, select, save, note, status);

  edit.addEventListener('click', () => {
    form.hidden = !form.hidden;
    edit.setAttribute('aria-expanded', String(!form.hidden));
    if (!form.hidden) select.focus();
  });
  save.addEventListener('click', async () => {
    save.disabled = true;
    status.textContent = '';
    try {
      await handlers.onSizeChange(select.value as BusinessSize);
      size.textContent = SIZES.find((s) => s.value === select.value)?.label ?? '';
      form.hidden = true;
      edit.setAttribute('aria-expanded', 'false');
    } catch {
      status.textContent = 'No pudimos guardar el cambio. Inténtalo de nuevo.';
    } finally {
      save.disabled = false;
    }
  });
  box.append(summary, edit, form);
  return box;
}

const pct = (p: string) => `${Number(Number(p).toFixed(2)).toString().replace('.', ',')} %`;

/** Detalle de una modalidad: mismos conceptos que el cotizador (todo calculado por Django). */
function paymentDetail(o: PaymentOption, from: boolean): HTMLElement {
  const box = el('div', 'adv-pay-detail');
  const row = (label: string, value: string, cls = '') => {
    const r = el('p', `adv-pay-row${cls ? ` ${cls}` : ''}`);
    r.append(el('span', '', label), el('span', '', value));
    box.append(r);
  };
  const prefix = from ? 'Desde ' : '';
  if (!o.available) {
    box.append(el('p', 'adv-card-warn', o.unavailable_reason));
    return box;
  }
  if (o.kind === 'cash') {
    row('Precio original', `${prefix}${formatUSD(o.original)}`, 'muted');
    if (o.discount > 0) {
      row(`Descuento aplicado (${pct(o.discount_percent)})`, `-${formatUSD(o.discount)}`);
      row('Tu ahorro', formatUSD(o.savings));
    } else {
      box.append(el('p', 'adv-card-note', o.unavailable_reason || 'El descuento de contado no aplica a esta propuesta.'));
    }
    row('Total de contado', `${prefix}${formatUSD(o.total)}`, 'total');
    box.append(el('p', 'adv-card-note', paymentCopy.cashNote(pct(o.discount_percent).replace(' %', ''))));
  } else {
    row('Precio base del desarrollo', `${prefix}${formatUSD(o.original)}`, 'muted');
    row(`Incremento por financiar (${pct(o.surcharge_percent)})`, `+${formatUSD(o.surcharge)}`);
    row(`Total del plan a ${o.term_months} meses`, `${prefix}${formatUSD(o.total)}`, 'total');
    row(`Inicial (${pct(o.initial_percent)})`, formatUSD(o.initial));
    row(o.cadence ?? '', `${formatUSD(o.installment)} c/u`);
    box.append(el('p', 'adv-card-note', `${paymentCopy.financingNote} ${paymentCopy.approvalFine}`));
  }
  if (o.schedule.length) {
    const ol = el('ol', 'adv-pay-sched');
    for (const s of o.schedule) {
      const li = el('li');
      li.append(el('span', '', `${s.label} · ${s.due}`), el('b', '', formatUSD(s.amount)));
      ol.append(li);
    }
    box.append(ol);
  }
  return box;
}

const refreshers = new WeakMap<HTMLElement, (mode: PaymentMode) => void>();

/** Muestra en una tarjeta la modalidad elegida (por el visitante o por el asesor mediante la herramienta). */
export function setCardPaymentMode(scope: ParentNode, proposalId: number, mode: PaymentMode): void {
  const root = scope.querySelector<HTMLElement>(`[data-proposal-id="${proposalId}"]`);
  if (root) refreshers.get(root)?.(mode);
}

function renderPaymentSection(card: ProposalCard, handlers: CardHandlers, root: HTMLElement): HTMLElement {
  const section = el('div', 'adv-card-payment');
  section.append(el('span', 'mono', 'Modalidad de pago'));
  const chips = el('div', 'adv-pay-modes');
  chips.setAttribute('role', 'radiogroup');
  chips.setAttribute('aria-label', 'Modalidad de pago');
  const detail = el('div', 'adv-pay-box');
  detail.setAttribute('aria-live', 'polite');
  const status = el('p', 'adv-err');
  status.setAttribute('role', 'alert');

  const buttons = new Map<PaymentMode, HTMLButtonElement>();
  for (const o of card.payment_options) {
    const b = el('button', 'adv-pay-mode');
    b.type = 'button';
    b.setAttribute('role', 'radio');
    b.disabled = !o.available;
    b.append(el('span', 'n', o.label), el('span', 'p', o.kind === 'cash' ? (o.discount > 0 ? `${pct(o.discount_percent)} de descuento` : 'Pago único') : (o.cadence ?? '')));
    if (!o.available) b.title = o.unavailable_reason;
    b.addEventListener('click', async () => {
      status.textContent = '';
      try {
        await handlers.onPaymentMode(card, o.mode);
      } catch {
        status.textContent = 'No pudimos guardar la modalidad. Inténtalo de nuevo.';
      }
    });
    buttons.set(o.mode, b);
    chips.append(b);
  }

  const show = (mode: PaymentMode | null) => {
    card.payment_mode = mode;
    for (const [m, b] of buttons) b.setAttribute('aria-checked', String(m === mode));
    const chosen = card.payment_options.find((o) => o.mode === mode);
    detail.replaceChildren(chosen ? paymentDetail(chosen, card.development_from) : el('p', 'adv-card-note', 'Elige cómo prefieres pagar el desarrollo.'));
  };
  refreshers.set(root, show);
  show(card.payment_mode);
  section.append(chips, detail, status);
  return section;
}

function renderCard(card: ProposalCard, handlers: CardHandlers): HTMLElement {
  const root = el('article', `adv-card${card.tier === 'recommended' ? ' is-recommended' : ''}`);
  root.dataset.proposalId = String(card.id);
  root.dataset.tier = card.tier;
  const titleId = `adv-card-${card.id}`;
  root.setAttribute('aria-labelledby', titleId);

  // Encabezado: nombre, tipo de solución y complejidad
  const head = el('div', 'adv-card-head');
  const title = el('h3', '', card.name);
  title.id = titleId;
  head.append(title);
  if (card.tier === 'recommended') head.append(el('span', 'adv-badge', 'Mejor equilibrio'));
  const meta = el('p', 'adv-card-meta');
  meta.append(el('span', '', card.recommended_type), el('span', 'mono', `Complejidad ${card.complexity_label.toLowerCase()}`));
  meta.title = card.complexity_factors.join(' · ');

  // Precio y forma de pago
  const price = el('div', 'adv-card-price');
  const amount = el('b', '', `${card.development_from ? 'Desde ' : ''}${formatUSD(card.development_total)}`);
  price.append(el('span', 'mono', 'Desarrollo · 2 pagos'), amount);
  const pay = el('p', 'adv-card-pay');
  pay.append(
    el('span', '', `Para arrancar: ${formatUSD(card.payments.start)}`),
    el('span', '', `Al culminar, con todo funcionando: ${formatUSD(card.payments.delivery)}`),
  );
  price.append(pay);
  if (card.within_budget !== null) {
    price.append(el('span', `adv-fit ${card.within_budget ? 'ok' : 'over'}`, card.within_budget ? 'Dentro de tu presupuesto' : 'Supera tu presupuesto'));
  }

  // Funcionalidades (con el beneficio específico de cada una)
  const details = el('details', 'adv-card-features');
  details.open = card.tier === 'recommended' || card.tier === 'adjusted';
  const count = card.features.filter((f) => f.kind !== 'included').length;
  details.append(el('summary', '', `Funcionalidades (${count}${card.features.some((f) => f.kind === 'included') ? ' + incluidas' : ''})`));
  const list = el('ul');
  for (const f of card.features) {
    const li = el('li');
    const row = el('div', 'row');
    row.append(el('span', '', f.label), el('span', 'price', f.kind === 'included' ? 'incluido' : `${f.from ? 'desde ' : ''}${formatUSD(f.price)}`));
    li.append(row);
    if (f.benefit) li.append(el('p', 'benefit', f.benefit));
    if (f.kind === 'dependency') li.classList.add('dep');
    list.appendChild(li);
  }
  details.append(list);

  root.append(head, meta, price);
  if (card.payment_options?.length) root.append(renderPaymentSection(card, handlers, root));
  root.append(details);

  if (card.requires_custom_quote) {
    const custom = el('div', 'adv-card-custom');
    custom.append(el('b', '', card.custom_quote_text || 'Requiere cotización personalizada'));
    const ul = el('ul');
    for (const item of card.custom_items) ul.append(el('li', '', item));
    custom.append(ul, el('p', '', 'Este desarrollo no está en el cotizador y no tiene precio asignado todavía; el monto de arriba solo incluye lo que sí está cotizado.'));
    root.append(custom);
  }

  // Costos recurrentes, siempre aparte del desarrollo
  const rec = el('div', 'adv-card-monthly');
  rec.append(el('span', 'mono', 'Costos recurrentes · aparte del desarrollo'));
  if (card.monthly_lines.length) {
    const ul = el('ul');
    for (const l of card.monthly_lines) {
      const li = el('li');
      li.append(el('span', '', l.label), el('span', 'price', `${l.from ? 'desde ' : ''}${formatUSD(l.usd)}/mes`));
      ul.append(li);
    }
    rec.append(ul, el('p', 'total', `Total mensual: ${card.monthly.from ? 'desde ' : ''}${formatUSD(card.monthly.total)}/mes`));
  } else {
    rec.append(el('p', 'total', 'Sin costos mensuales con Angside en esta opción.'));
  }
  root.append(rec);

  if (card.ai_usage) {
    const ai = el('div', 'adv-card-monthly');
    ai.append(el('span', 'mono', 'Consumo de IA del chatbot · aparte'));
    const u = card.ai_usage;
    const text = u.monthly === null
      ? 'Variable según uso. Se estima en el cotizador según el volumen de conversaciones.'
      : `Estimado ≈ ${u.under_one_cent ? 'menos de $0,01 USD' : formatUSD(u.monthly)}/mes con ${(u.conversations ?? 0).toLocaleString('de-DE')} conversaciones.`;
    ai.append(el('p', 'total', text), el('p', 'adv-card-note', u.note));
    root.append(ai);
  }

  root.append(el('p', 'adv-card-timeline', `Plazo: ${card.timeline}`));
  if (!card.complete) {
    root.append(el('p', 'adv-card-warn', 'Faltan requisitos por definir en el cotizador para completar esta propuesta.'));
  }
  for (const n of card.notices) root.append(el('p', 'adv-card-note', n));

  // Acciones
  const actions = el('div', 'adv-card-actions');
  const view = el('button', 'btn btn-dark', 'Ver en el cotizador');
  view.type = 'button';
  view.addEventListener('click', () => handlers.onApply(card));
  const request = el('button', 'btn', card.requested ? 'Propuesta solicitada ✓' : 'Solicitar propuesta');
  request.type = 'button';
  request.disabled = card.requested;
  request.addEventListener('click', () => handlers.onRequest(card, request));
  const negotiate = el('button', 'adv-link', 'Negociar esta propuesta');
  negotiate.type = 'button';
  negotiate.addEventListener('click', () => handlers.onNegotiate(card));
  actions.append(view, request, negotiate);
  root.append(actions);
  return root;
}

/** Grupo de tarjetas de una ronda de propuestas (más la clasificación del cliente). */
export function renderProposals(event: ProposalsEvent, handlers: CardHandlers): HTMLElement {
  const group = el('section', 'adv-proposals');
  group.setAttribute('aria-label', 'Propuestas para tu negocio');
  group.dataset.round = String(event.round);
  group.append(renderProfile(event.profile, handlers));
  for (const card of event.proposals) group.append(renderCard(card, handlers));
  return group;
}
