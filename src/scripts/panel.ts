import {
  ApiError, createPanelApi,
  type LeadDetail, type LeadRow, type Overview, type PanelUser,
} from '../lib/panel-api';

const root = document.querySelector<HTMLElement>('#panel')!;
const $ = <T extends HTMLElement = HTMLElement>(sel: string) => root.querySelector<T>(sel)!;
/**
 * La cookie de sesión es SameSite=Lax: el sitio y la API deben compartir el mismo "sitio" (p. ej. angside.com y api.angside.com).
 * En desarrollo, localhost y 127.0.0.1 son sitios distintos; se alinea la API con el host con que se abrió el panel.
 */
function resolveApiBase(configured: string): string {
  try {
    const url = new URL(configured);
    const local = ['localhost', '127.0.0.1'];
    if (local.includes(url.hostname) && local.includes(location.hostname)) url.hostname = location.hostname;
    return url.origin;
  } catch {
    return configured;
  }
}

const api = createPanelApi(resolveApiBase(root.dataset.api ?? ''));

type Tab = 'overview' | 'leads' | 'quotes';
const MODE_LABEL: Record<string, string> = { cash: 'Contado', m3: '3 meses', m6: '6 meses', m9: '9 meses' };
const TIER_LABEL: Record<string, string> = { essential: 'Esencial', recommended: 'Recomendada', complete: 'Completa' };

let tab: Tab = 'overview';
let leadsPage = 1;
let quotesPage = 1;
let statuses: { value: string; label: string }[] = [];
let opener: HTMLElement | null = null;

// --- Utilidades de DOM (todo el texto entra por textContent: nada de HTML de terceros) ---
type Child = Node | string | null | undefined | false;
function h<K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, unknown> = {}, ...children: Child[]): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') node.className = String(v);
    else if (k === 'text') node.textContent = String(v);
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    else node.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children) if (c) node.append(c);
  return node;
}

const money = (n: number | null | undefined) => (n == null ? '—' : `$${n.toLocaleString('es-VE', { maximumFractionDigits: 2 })}`);
const when = (iso: string) => new Date(iso).toLocaleString('es-VE', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
const day = (iso: string) => new Date(iso).toLocaleDateString('es-VE', { day: '2-digit', month: 'short', year: 'numeric' });
const contactOf = (l: Pick<LeadRow, 'whatsapp' | 'phone' | 'email'>) => [l.whatsapp || l.phone, l.email].filter(Boolean);

function setNotice(text = '') {
  const n = $('#notice');
  n.textContent = text;
  n.hidden = !text;
}

function table(headers: string[], rows: HTMLElement[], empty: string): HTMLElement {
  if (!rows.length) return h('p', { class: 'card empty', text: empty });
  return h('div', { class: 'card table-wrap' }, h('table', { class: 't' },
    h('thead', {}, h('tr', {}, ...headers.map((t) => h('th', { scope: 'col', text: t })))),
    h('tbody', {}, ...rows)));
}

function pager(host: HTMLElement, page: number, pages: number, total: number, go: (p: number) => void) {
  host.replaceChildren();
  if (pages <= 1) {
    if (total) host.append(h('span', { text: `${total} en total` }));
    return;
  }
  host.append(
    h('button', { type: 'button', text: 'Anterior', disabled: page <= 1, onclick: () => go(page - 1) }),
    h('span', { text: `Página ${page} de ${pages} · ${total} en total` }),
    h('button', { type: 'button', text: 'Siguiente', disabled: page >= pages, onclick: () => go(page + 1) }),
  );
}

// --- Sesión ---
function showLogin(message = '') {
  $('#boot').hidden = true;
  $('#app').hidden = true;
  $('#login').hidden = false;
  $('#login-error').textContent = message;
  const form = $<HTMLFormElement>('#login-form');
  (form.elements.namedItem('password') as HTMLInputElement).value = '';
  (form.elements.namedItem('username') as HTMLInputElement).focus();
}

function showApp(u: PanelUser) {
  $('#boot').hidden = true;
  $('#login').hidden = true;
  $('#app').hidden = false;
  $('#who-name').textContent = u.name;
  const staff = u.role === 'staff';
  $('#tabs').hidden = !staff;
  if (staff) selectTab('overview');
  else setViews('client');
}

/** Cualquier 401 devuelve al inicio de sesión (la sesión venció o se cerró en otro lugar). */
function handleError(err: unknown) {
  if (err instanceof ApiError && err.status === 401) return showLogin('Tu sesión venció. Vuelve a ingresar.');
  setNotice(err instanceof ApiError ? err.message : 'Ocurrió un error inesperado.');
}

function setViews(name: string) {
  root.querySelectorAll<HTMLElement>('[data-view]').forEach((v) => { v.hidden = v.dataset.view !== name; });
}

function selectTab(next: Tab) {
  tab = next;
  setNotice();
  root.querySelectorAll<HTMLElement>('#tabs [data-tab]').forEach((b) => {
    if (b.dataset.tab === next) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
  setViews(next);
  if (next === 'overview') loadOverview();
  if (next === 'leads') loadLeads();
  if (next === 'quotes') loadQuotes();
}

// --- Resumen ---
function kpi(label: string, value: string, hint = '') {
  return h('div', { class: 'card kpi' }, h('span', { class: 'mono', text: label }), h('strong', { text: value }), hint && h('small', { text: hint }));
}

function bars(items: { label: string; count: number }[]) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return h('div', { class: 'bars' }, ...items.map((i) => h('div', { class: 'bar-row' },
    h('span', { text: i.label }),
    h('span', { class: 'track' }, h('span', { class: 'fill', style: `display:block;width:${(i.count / max) * 100}%` })),
    h('span', { class: 'num', text: String(i.count) }))));
}

function renderOverview(o: Overview) {
  const view = $('#view-overview');
  view.replaceChildren(
    h('div', { class: 'kpis' },
      kpi('Prospectos', String(o.leads.total), `${o.leads.today} hoy`),
      kpi('Últimos 7 días', String(o.leads.last_7_days)),
      kpi('En negociación', String(o.leads.negotiating)),
      kpi('Cotizaciones WhatsApp', String(o.quotes.total), `${o.quotes.last_7_days} en 7 días`),
      kpi('IA hoy', money(o.ai.spent_today_usd), `de ${money(o.ai.daily_budget_usd)} diarios`),
      kpi('IA este mes', money(o.ai.spent_month_usd), `de ${money(o.ai.monthly_budget_usd)} mensuales`)),
    h('div', { class: 'cols' },
      h('section', { class: 'card box' }, h('h3', { text: 'Prospectos por estado' }), bars(o.leads.by_status.map((s) => ({ label: s.label, count: s.count })))),
      h('section', { class: 'card box' }, h('h3', { text: 'Modalidad de pago elegida' }),
        bars(o.payment_modes.map((m) => ({ label: MODE_LABEL[m.mode] ?? m.mode, count: m.count }))),
        h('p', { class: 'hint', text: 'Cuenta propuestas del asesor de IA donde el visitante eligió una modalidad.' }))),
    h('h3', { text: 'Últimos prospectos', style: 'margin:0 0 10px;font-size:13px' }),
    leadsTable(o.recent_leads, 'Todavía no hay prospectos.'));
}

async function loadOverview() {
  try { renderOverview(await api.overview()); } catch (e) { handleError(e); }
}

// --- Prospectos ---
function leadsTable(items: LeadRow[], empty: string) {
  const rows = items.map((l) => {
    const tr = h('tr', { 'data-id': l.id, tabindex: 0, role: 'button', 'aria-label': `Abrir ${l.business}` },
      h('td', { text: day(l.created_at) }),
      h('td', {}, h('strong', { text: l.business }), h('small', { text: l.name })),
      h('td', {}, ...contactOf(l).map((c) => h('small', { text: c, style: 'color:inherit' }))),
      h('td', { text: l.budget_range || '—' }, h('small', { text: l.budget_calculated_usd ? `Calculado: ${money(l.budget_calculated_usd)}` : '' })),
      h('td', { text: l.complexity_label || '—' }),
      h('td', {}, ...(l.payment_modes.length ? l.payment_modes.map((m) => h('span', { class: 'pill', text: MODE_LABEL[m] ?? m })) : [h('span', { text: '—' })])),
      h('td', {}, h('span', { class: `pill${l.negotiation_requested ? ' on' : ''}`, text: l.negotiation_requested ? `${l.status_label} · negocia` : l.status_label })));
    const open = () => openLead(l.id, tr);
    tr.addEventListener('click', open);
    tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
    return tr;
  });
  return table(['Fecha', 'Negocio', 'Contacto', 'Presupuesto', 'Complejidad', 'Pago', 'Estado'], rows, empty);
}

async function loadLeads() {
  const q = $<HTMLInputElement>('#f-q').value.trim();
  const status = $<HTMLSelectElement>('#f-status').value;
  try {
    const data = await api.leads({ q, status, page: leadsPage });
    if (!statuses.length) {
      statuses = data.statuses;
      $<HTMLSelectElement>('#f-status').append(...statuses.map((s) => h('option', { value: s.value, text: s.label })));
    }
    $('#leads-table').replaceChildren(leadsTable(data.items, q || status ? 'Ningún prospecto coincide con la búsqueda.' : 'Todavía no hay prospectos.'));
    pager($('#leads-pager'), data.page, data.pages, data.total, (p) => { leadsPage = p; loadLeads(); });
  } catch (e) { handleError(e); }
}

async function loadQuotes() {
  try {
    const data = await api.quotes(quotesPage);
    const rows = data.items.map((q) => h('tr', {},
      h('td', {}, h('strong', { text: q.reference })),
      h('td', { text: when(q.created_at) }),
      h('td', { text: MODE_LABEL[q.payment_mode] ?? 'Dos partes' }),
      h('td', { text: money(q.development_original) }),
      h('td', { text: money(q.development_total) }),
      h('td', { text: `v${q.pricing_version}` }),
      h('td', {}, h('small', { text: q.config, style: 'overflow-wrap:anywhere' }))));
    $('#quotes-table').replaceChildren(table(['Referencia', 'Fecha', 'Pago', 'Original', 'Total desarrollo', 'Precios', 'Configuración'], rows, 'Aún no se han registrado cotizaciones.'));
    pager($('#quotes-pager'), data.page, data.pages, data.total, (p) => { quotesPage = p; loadQuotes(); });
  } catch (e) { handleError(e); }
}

// --- Detalle del prospecto ---
function dl(pairs: [string, Child][]) {
  return h('dl', { class: 'dl' }, ...pairs.flatMap(([k, v]) => (v ? [h('dt', { text: k }), h('dd', {}, v)] : [])));
}

function renderLead(d: LeadDetail) {
  $('#drawer-title').textContent = d.business;
  const wa = (d.whatsapp || d.phone).replace(/\D/g, '');
  const statusSel = h('select', { id: 'd-status', 'aria-label': 'Estado' }, ...statuses.map((s) => h('option', { value: s.value, text: s.label, selected: s.value === d.status })));
  const notes = h('textarea', { id: 'd-notes', maxlength: 4000, 'aria-label': 'Notas internas' });
  notes.value = d.notes;
  const msg = h('p', { class: 'hint', role: 'status' });
  const save = h('button', {
    type: 'button', class: 'btn btn-dark', text: 'Guardar',
    onclick: async () => {
      save.disabled = true;
      msg.textContent = 'Guardando…';
      try {
        await api.updateLead(d.id, { status: statusSel.value, notes: notes.value });
        msg.textContent = 'Guardado.';
        loadLeads();
        if (tab === 'overview') loadOverview();
      } catch (e) { msg.textContent = e instanceof ApiError ? e.message : 'No se pudo guardar.'; handleError(e); } finally { save.disabled = false; }
    },
  });

  const body = $('#drawer-body');
  body.replaceChildren(
    h('section', { class: 'card box' }, h('h3', { text: 'Contacto' }), dl([
      ['Nombre', d.name], ['Correo', d.email], ['Teléfono', d.phone], ['WhatsApp', d.whatsapp],
      ['Ubicación', d.location], ['Registrado', when(d.created_at)],
      ['Contacto comercial', d.marketing_consent ? 'Autorizado' : 'No autorizado'],
    ]), wa && h('a', { class: 'btn', href: `https://wa.me/${wa}`, target: '_blank', rel: 'noopener', text: 'Escribir por WhatsApp' })),
    h('section', { class: 'card box' }, h('h3', { text: 'Seguimiento' }),
      h('div', { class: 'row-actions' }, h('label', {}, 'Estado', statusSel), save),
      h('label', {}, 'Notas internas', notes), msg),
    h('section', { class: 'card box' }, h('h3', { text: 'Lo que declaró' }), dl([
      ['Sector', d.sector], ['Necesidad', d.need], ['Resumen del asesor', d.needs_summary],
      ['Sitio web', d.has_website === 'yes' ? 'Sí' : d.has_website === 'no' ? 'No' : ''],
      ['Presupuesto', d.budget_range], ['Presupuesto indicado', d.budget_stated_usd ? money(d.budget_stated_usd) : ''],
      ['Cuándo empezar', d.start_when], ['Tamaño', d.business_size], ['Complejidad', d.complexity_label],
      ['Funcionalidades', d.recommended_features.join(', ')],
    ])),
    ...(d.negotiation.requested ? [h('section', { class: 'card box' }, h('h3', { text: 'Negociación' }), dl([
      ['Presupuesto inicial', d.negotiation.initial_budget ? money(d.negotiation.initial_budget) : ''],
      ['Presupuesto ideal', d.negotiation.ideal_budget ? money(d.negotiation.ideal_budget) : ''],
      ['Motivo', d.negotiation.reason],
      ['Objeciones', d.objections.map((o) => `${o.category ?? ''}: ${o.detail ?? ''}`).join(' · ')],
    ]))] : []),
    h('section', { class: 'card box' }, h('h3', { text: `Propuestas (${d.proposals_detail.length})` }),
      d.proposals_detail.length
        ? h('div', { class: 'props' }, ...d.proposals_detail.map((p) => h('div', { class: 'prop' },
          h('strong', { text: `${TIER_LABEL[p.tier] ?? p.tier} · ${money(p.development_total)}${p.requested ? ' · solicitada' : ''}` }),
          h('span', { text: `Pago: ${p.payment_mode ? MODE_LABEL[p.payment_mode] ?? p.payment_mode : 'sin elegir'} · precios v${p.pricing_version ?? '—'} · ${day(p.created_at)}` }),
          p.features.length ? h('span', { class: 'hint', text: p.features.join(', ') }) : null)))
        : h('p', { class: 'hint', text: 'El asesor aún no le presentó propuestas.' })),
    ...d.conversations.map((c) => h('section', { class: 'card box' },
      h('h3', { text: `Conversación con el asesor · ${when(c.started_at)}` }),
      c.messages.length
        ? h('div', { class: 'chat' }, ...c.messages.map((m) => h('div', { class: `msg ${m.role}` }, m.text, h('time', { text: `${m.role === 'user' ? 'Cliente' : 'Asesor IA'} · ${when(m.at)}` }))))
        : h('p', { class: 'hint', text: 'Sin mensajes.' }))));
}

async function openLead(id: number, from?: HTMLElement) {
  opener = from ?? null;
  try {
    const d = await api.lead(id);
    renderLead(d);
    $('#drawer').hidden = false;
    document.documentElement.style.overflow = 'hidden';
    $<HTMLButtonElement>('#drawer button[data-close]').focus();
  } catch (e) { handleError(e); }
}

function closeDrawer() {
  $('#drawer').hidden = true;
  document.documentElement.style.overflow = '';
  opener?.focus();
}

// --- Eventos ---
$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.currentTarget as HTMLFormElement;
  const submit = $<HTMLButtonElement>('#login-submit');
  const username = (form.elements.namedItem('username') as HTMLInputElement).value.trim();
  const password = (form.elements.namedItem('password') as HTMLInputElement).value;
  if (!username || !password) { $('#login-error').textContent = 'Escribe tu usuario y tu contraseña.'; return; }
  submit.disabled = true;
  $('#login-error').textContent = '';
  try {
    showApp(await api.login(username, password));
  } catch (err) {
    $('#login-error').textContent = err instanceof ApiError ? err.message : 'No se pudo iniciar sesión.';
  } finally {
    submit.disabled = false;
  }
});

$('#pw-toggle').addEventListener('click', (e) => {
  const input = $<HTMLFormElement>('#login-form').elements.namedItem('password') as HTMLInputElement;
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  (e.currentTarget as HTMLElement).textContent = show ? 'Ocultar' : 'Mostrar';
  (e.currentTarget as HTMLElement).setAttribute('aria-pressed', String(show));
});

$('#logout').addEventListener('click', async () => {
  try { await api.logout(); } catch { /* la sesión se descarta igual en pantalla */ }
  closeDrawer();
  showLogin();
});

$('#tabs').addEventListener('click', (e) => {
  const b = (e.target as HTMLElement).closest<HTMLElement>('[data-tab]');
  if (b) selectTab(b.dataset.tab as Tab);
});

$('#drawer').addEventListener('click', (e) => { if ((e.target as HTMLElement).closest('[data-close]')) closeDrawer(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#drawer').hidden) closeDrawer(); });

let searchTimer = 0;
$('#filters').addEventListener('submit', (e) => e.preventDefault());
$('#f-q').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { leadsPage = 1; loadLeads(); }, 300); });
$('#f-status').addEventListener('change', () => { leadsPage = 1; loadLeads(); });

// --- Arranque ---
(async () => {
  if (!root.dataset.api) {
    $('#boot').hidden = true;
    $('#login').hidden = false;
    $('#login-form').hidden = true;
    $('#no-api').hidden = false;
    return;
  }
  try {
    const me = await api.me();
    if (me) showApp(me);
    else showLogin();
  } catch (e) {
    $('#boot').hidden = true;
    showLogin(e instanceof ApiError ? e.message : 'No se pudo conectar con el servidor.');
  }
})();
