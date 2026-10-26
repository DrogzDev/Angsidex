import { billingPlanById, categories, hostingById, modules, type BaseId, type BillingPlanId, type CategoryId, type HostingId, type ModuleId } from '../data/pricing';
import { defaultCommercialConfig, paymentCopy, type CommercialConfig, type PaymentModeId, type UsageTierId } from '../data/commercial';
import {
  buildSummary,
  computeQuote,
  confirmDependencies,
  decodeState,
  encodeState,
  formatCents,
  formatUSD,
  getModuleStatus,
  initialState,
  normalizeState,
  setBase,
  setBillingPlan,
  setChatbotUsage,
  setHosting,
  setMaintenance,
  setPaymentMode,
  toggleModule,
  type Quote,
  type QuoteState,
} from '../lib/quote-engine';
import { cadenceText, modeLabel, type PaymentBreakdown } from '../lib/payment-plans';
import { fetchCommercialConfig, newQuoteReference, registerQuote } from '../lib/commercial-config';
import { buildWhatsAppUrl } from '../lib/whatsapp';

const STORAGE_KEY = 'angside.quote.v1';
const root = document.getElementById('calc');

if (root) init(root);

function init(root: HTMLElement) {
  const $ = <T extends HTMLElement>(sel: string) => root.querySelector<T>(sel)!;
  const all = <T extends HTMLElement>(sel: string) => [...root.querySelectorAll<T>(sel)];
  const phone = root.dataset.phone || null;
  const api = root.dataset.api || '';
  // Condiciones comerciales: las de Django Admin cuando la API responde; si no, los valores por defecto.
  let config: CommercialConfig = defaultCommercialConfig;
  void fetchCommercialConfig(api).then((c) => {
    if (c !== config) {
      config = c;
      render();
    }
  });

  const safeStorage = {
    get(): string | null {
      try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
    },
    set(v: string) {
      try { localStorage.setItem(STORAGE_KEY, v); } catch { /* almacenamiento no disponible */ }
    },
    clear() {
      try { localStorage.removeItem(STORAGE_KEY); } catch { /* idem */ }
    },
  };

  // Prioridad: enlace compartido > configuración guardada > vacío
  const fromUrl = decodeState(location.search);
  let state: QuoteState = fromUrl.baseId ? fromUrl : load();
  let activeTab: CategoryId = categories[0].id;

  function load(): QuoteState {
    const raw = safeStorage.get();
    if (!raw) return initialState;
    try {
      return decodeState(raw);
    } catch {
      return initialState;
    }
  }

  const commit = (next: QuoteState) => {
    state = next;
    safeStorage.set(encodeState(state));
    render();
  };

  const say = (msg: string) => {
    const el = $('#out-status');
    el.textContent = msg;
    window.setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 3500);
  };

  // --- Eventos ---
  root.addEventListener('click', (e) => {
    const t = (e.target as HTMLElement).closest<HTMLElement>('[data-base],[data-module],[data-hosting],[data-billing],[data-tab],[data-mode],[data-usage],#maint,#dep-confirm,#btn-send,#btn-copy,#btn-share,#btn-reset');
    if (!t) return;
    if (t.dataset.base) commit(setBase(state, t.dataset.base as BaseId));
    else if (t.dataset.module) commit(toggleModule(state, t.dataset.module as ModuleId));
    else if (t.dataset.hosting) commit(setHosting(state, t.dataset.hosting as HostingId));
    else if (t.dataset.billing) commit(setBillingPlan(state, t.dataset.billing as BillingPlanId));
    else if (t.dataset.mode) commit(setPaymentMode(state, t.dataset.mode as PaymentModeId));
    else if (t.dataset.usage) {
      const tier = t.dataset.usage as UsageTierId;
      const suggested = config.chatbot.tiers.find((x) => x.id === 'custom')?.conversations ?? null;
      commit(setChatbotUsage(state, tier, tier === 'custom' ? (state.chatbotConversations ?? suggested) : null));
    }
    else if (t.dataset.tab) { activeTab = t.dataset.tab as CategoryId; render(); }
    else if (t.id === 'maint') commit(setMaintenance(state, !state.maintenance));
    else if (t.id === 'dep-confirm') commit(confirmDependencies(state));
    else if (t.id === 'btn-reset') { safeStorage.clear(); commit(initialState); say('Presupuesto reiniciado.'); }
    else if (t.id === 'btn-copy') copy(buildSummary(state, config), 'Presupuesto copiado.');
    else if (t.id === 'btn-share') {
      const url = `${location.origin}${location.pathname}?${encodeState(state)}#calculadora`;
      copy(url, 'Enlace copiado.');
    } else if (t.id === 'btn-send') send();
  });

  // Volumen personalizado del chatbot
  $<HTMLInputElement>('#usage-custom').addEventListener('input', (e) => {
    const n = Math.floor(Number((e.target as HTMLInputElement).value));
    const max = config.chatbot.customMaxConversations;
    commit(setChatbotUsage(state, 'custom', Number.isFinite(n) && n > 0 ? Math.min(n, max) : null));
  });

  // Navegación por teclado en pestañas (flechas)
  $('.tabs').addEventListener('keydown', (e) => {
    const k = (e as KeyboardEvent).key;
    if (k !== 'ArrowRight' && k !== 'ArrowLeft') return;
    const tabs = all<HTMLButtonElement>('[data-tab]');
    const i = tabs.findIndex((b) => b.dataset.tab === activeTab);
    const next = tabs[(i + (k === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    activeTab = next.dataset.tab as CategoryId;
    render();
    next.focus();
  });

  // Desde el asistente de IA: aplica la configuración propuesta (se valida y normaliza igual que un enlace compartido)
  window.addEventListener('angside:apply-quote', (e) => {
    const config = (e as CustomEvent<{ config?: string }>).detail?.config;
    if (typeof config === 'string') commit(decodeState(config));
  });

  // Desde las tarjetas de servicios: preselecciona la base
  document.addEventListener('click', (e) => {
    const el = e.target as HTMLElement;
    const a = el.closest<HTMLElement>('[data-service]');
    if (a?.dataset.service) commit(setBase(state, a.dataset.service as BaseId));
    const h = el.closest<HTMLElement>('[data-pick-hosting]');
    if (h?.dataset.pickHosting) commit(setHosting(state, h.dataset.pickHosting as HostingId));
  });

  async function copy(text: string, ok: string) {
    try {
      await navigator.clipboard.writeText(text);
      say(ok);
    } catch {
      // Respaldo para contextos sin Clipboard API
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        say(ok);
      } catch {
        say('No se pudo copiar automáticamente.');
      }
      ta.remove();
    }
  }

  function send() {
    // La referencia identifica la cotización en el mensaje y en el registro de Django (sin datos personales).
    const reference = newQuoteReference();
    const url = buildWhatsAppUrl(phone, buildSummary(state, config, { reference }));
    if (!url) {
      say('WhatsApp aún no está configurado. Usa "Copiar presupuesto".');
      return;
    }
    window.open(url, '_blank', 'noopener');
    // Registro en segundo plano: WhatsApp no depende de que la API responda. Sin versión de precios (API caída) no se registra.
    if (config.version > 0) void registerQuote(api, { reference, config: encodeState(state), version: config.version });
  }

  // --- Render ---
  function setText(el: HTMLElement, value: string) {
    if (el.textContent !== value) {
      el.textContent = value;
      el.classList.remove('bump');
      void el.offsetWidth;
      el.classList.add('bump');
    }
  }

  function li(label: string, value: string, cls = '') {
    const item = document.createElement('li');
    if (cls) item.className = cls;
    const a = document.createElement('span');
    a.textContent = label;
    const b = document.createElement('span');
    b.textContent = value;
    item.append(a, b);
    return item;
  }

  function render() {
    state = normalizeState(state);
    const q = computeQuote(state, config);
    const hasBase = !!state.baseId;
    const pay = q.payment?.available ? q.payment : null;

    all('[data-base]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.base === state.baseId)));
    all('[data-hosting]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.hosting === state.hostingId)));
    all('[data-billing]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.billing === state.billingPlanId)));
    $('#billing-step').hidden = !state.moduleIds.includes('facturacion');
    $('#maint').setAttribute('aria-checked', String(state.maintenance));
    $('#mods-hint').hidden = hasBase;

    all<HTMLButtonElement>('[data-tab]').forEach((t) => {
      const on = t.dataset.tab === activeTab;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
    });
    for (const c of categories) {
      const n = state.moduleIds.filter((id) => modules.find((m) => m.id === id)?.category === c.id).length;
      const badge = $(`[data-count="${c.id}"]`);
      badge.hidden = n === 0;
      badge.textContent = String(n);
    }

    all<HTMLButtonElement>('[data-module]').forEach((card) => {
      const id = card.dataset.module as ModuleId;
      const status = getModuleStatus(state, id);
      card.hidden = card.dataset.category !== activeTab;
      card.dataset.status = status;
      card.disabled = !hasBase || status === 'included' || status === 'unavailable';
      card.setAttribute('aria-pressed', String(status === 'selected'));
      const tag = card.querySelector<HTMLElement>('[data-tag]')!;
      tag.textContent = status === 'included' ? 'Incluido' : status === 'unavailable' ? (hasBase ? 'No aplica' : '') : '';
    });

    // Dependencias pendientes: se explican y se piden, nunca se suman en silencio
    const dep = $('#dep-box');
    dep.hidden = q.pending.length === 0;
    if (q.pending.length) {
      $('#dep-text').textContent = q.pending
        .map((p) => `${p.requiredBy.join(', ')} requiere "${p.dependency.name}" (${formatUSD(p.dependency.price)}). ${p.dependency.reason}`)
        .join(' ');
    }

    // Resumen: con una modalidad elegida, el total de desarrollo es el de esa modalidad
    const fromTxt = q.developmentFrom ? 'Desde ' : '';
    const devText = pay ? `${fromTxt}${formatCents(pay.totalCents)}` : `${fromTxt}${formatUSD(q.developmentTotal)}`;
    $('#out-dev-label').textContent = !pay ? 'Desarrollo · 2 pagos' : pay.kind === 'cash' ? 'Desarrollo · de contado' : `Desarrollo · plan a ${pay.termMonths} meses`;
    setText($('#out-dev'), devText);
    renderPayment(q);
    renderChatbot(q);
    const mon = $('#out-month');
    const monTxt = `${q.monthlyFrom ? 'Desde ' : ''}${formatUSD(q.monthlyTotal)}`;
    if (mon.firstChild?.textContent !== monTxt) {
      mon.textContent = monTxt;
      const small = document.createElement('small');
      small.textContent = '/mes';
      mon.append(small);
    }

    // Pago del desarrollo en dos partes
    const from = q.developmentFrom ? 'Desde ' : '';
    $('#out-pay').hidden = !hasBase || q.developmentTotal === 0 || !!pay;
    setText($('#out-pay-start'), `${from}${formatUSD(q.payments.start)}`);
    setText($('#out-pay-end'), `${from}${formatUSD(q.payments.delivery)}`);

    const lines = $('#out-lines');
    lines.replaceChildren(
      ...q.lines.map((l) => li(l.label, `${l.from ? 'desde ' : ''}${formatUSD(l.price)}`, l.kind === 'dependency' ? 'dep' : '')),
      ...q.included.map((n) => li(n, 'incluido', 'dep')),
    );
    $('#out-empty').hidden = hasBase;

    const monthly = $('#out-monthly');
    const rows: HTMLElement[] = [];
    if (q.hostingMonthly > 0) {
      const d = document.createElement('div');
      const h = hostingById(state.hostingId);
      d.append(Object.assign(document.createElement('span'), { textContent: h?.name ?? 'Hosting' }), Object.assign(document.createElement('span'), { textContent: `${formatUSD(q.hostingMonthly)}/mes` }));
      rows.push(d);
    }
    const plan = billingPlanById(state.billingPlanId ?? '');
    if (plan) {
      const d = document.createElement('div');
      d.append(Object.assign(document.createElement('span'), { textContent: `Facturación ${plan.name} (fijo)` }), Object.assign(document.createElement('span'), { textContent: `${formatUSD(plan.monthly)}/mes` }));
      rows.push(d);
    }
    if (q.maintenanceMonthly > 0) {
      const d = document.createElement('div');
      d.append(Object.assign(document.createElement('span'), { textContent: 'Mantenimiento básico' }), Object.assign(document.createElement('span'), { textContent: `${formatUSD(q.maintenanceMonthly)}/mes` }));
      rows.push(d);
    }
    monthly.replaceChildren(...rows);
    monthly.hidden = rows.length === 0;

    const warn = $('#out-warn');
    const msgs: string[] = [];
    if (hasBase && q.pending.length) msgs.push('Agrega los requisitos indicados para completar la propuesta.');
    if (q.missingBillingPlan) msgs.push('Elige un plan de facturación para la facturación digital.');
    if (q.hostingNeedsEvaluation) msgs.push('El servidor Xeon compartido está sujeto a disponibilidad y evaluación.');
    if (q.notices.length) msgs.push(...q.notices);
    warn.textContent = msgs.join(' ');
    warn.hidden = msgs.length === 0;

    const send = $<HTMLButtonElement>('#btn-send');
    send.disabled = !q.complete;
    $('#btn-copy').toggleAttribute('disabled', !hasBase);
    $('#btn-share').toggleAttribute('disabled', !hasBase);

    // Barra móvil
    const bar = $('#mbar');
    setText($('#bar-dev'), devText);
    setText($('#bar-mon'), `+ ${formatUSD(q.monthlyTotal).replace(' USD', '')}/mes`);
    bar.dataset.hasBase = String(hasBase);
    updateBar();
  }

  // --- Modalidades de pago ---
  const pctText = (p: string) => `${Number(Number(p).toFixed(2)).toString().replace('.', ',')} %`;

  function row(label: string, value: string, cls = '') {
    const d = document.createElement('div');
    if (cls) d.className = cls;
    d.append(Object.assign(document.createElement('span'), { textContent: label }), Object.assign(document.createElement('span'), { textContent: value }));
    return d;
  }

  function alertRow(text: string) {
    const a = document.createElement('div');
    a.className = 'alert';
    a.textContent = text;
    return a;
  }

  function paymentRows(p: PaymentBreakdown, from: string): HTMLElement[] {
    if (!p.available) return [alertRow(p.unavailableReason)];
    const rows: HTMLElement[] = [];
    if (p.kind === 'cash') {
      rows.push(row('Precio original', `${from}${formatCents(p.originalCents)}`, 'muted'));
      if (p.discountCents > 0) {
        rows.push(row(`Descuento aplicado (${pctText(p.discountPercent)})`, `-${formatCents(p.discountCents)}`, 'neg'));
        rows.push(row('Tu ahorro', formatCents(p.savingsCents)));
      } else {
        rows.push(alertRow(p.unavailableReason || 'El descuento de contado no aplica a esta cotización.'));
      }
      rows.push(row('Total de contado', `${from}${formatCents(p.totalCents)}`, 'total'));
    } else {
      rows.push(row('Precio base del desarrollo', `${from}${formatCents(p.originalCents)}`, 'muted'));
      rows.push(row(`Incremento por financiar (${pctText(p.surchargePercent)})`, `+${formatCents(p.surchargeCents)}`));
      rows.push(row(`Total del plan a ${p.termMonths} meses`, `${from}${formatCents(p.totalCents)}`, 'total'));
      rows.push(row(`Inicial (${pctText(p.initialPercent)})`, formatCents(p.initialCents)));
      rows.push(row(cadenceText(p.installmentCount, p.everyMonths), `${formatCents(p.installmentCents)} c/u`));
    }
    return rows;
  }

  function renderPayment(q: Quote) {
    const box = $('#pay-box');
    const show = !!state.baseId && q.developmentTotal > 0;
    box.hidden = !show;
    if (!show) return;
    const from = q.developmentFrom ? 'Desde ' : '';
    for (const btn of all<HTMLButtonElement>('[data-mode]')) {
      const id = btn.dataset.mode as PaymentModeId;
      const opt = q.paymentOptions.find((o) => o.modeId === id);
      const plan = config.plans.find((p) => p.id === id);
      const off = !opt || (id !== 'cash' && !opt.available);
      btn.hidden = id !== 'cash' && (!plan || !plan.enabled);
      btn.disabled = off;
      btn.setAttribute('aria-checked', String(state.paymentModeId === id));
      btn.title = opt && !opt.available ? opt.unavailableReason : '';
      btn.querySelector('.mn')!.textContent = modeLabel(id, config);
      btn.querySelector('[data-mode-sub]')!.textContent = off
        ? 'No disponible'
        : id === 'cash'
          ? opt.discountCents > 0 ? `${pctText(config.cashDiscount.percent)} de descuento` : 'Pago único'
          : cadenceText(opt.installmentCount, opt.everyMonths);
    }
    const detail = $('#pay-detail');
    const sched = $('#pay-sched');
    const note = $('#pay-note');
    const p = q.payment;
    if (!p) {
      detail.replaceChildren(row('Elige cómo quieres pagar el desarrollo.', '', 'muted'));
      sched.hidden = true;
      note.hidden = true;
      return;
    }
    detail.replaceChildren(...paymentRows(p, from));
    sched.hidden = !p.available || p.schedule.length === 0;
    sched.replaceChildren(
      ...p.schedule.map((s) => {
        const li = document.createElement('li');
        const label = document.createElement('span');
        label.textContent = s.label;
        const due = document.createElement('small');
        due.textContent = s.due;
        const amount = document.createElement('b');
        amount.textContent = formatCents(s.amountCents);
        li.append(label, due, amount);
        return li;
      }),
    );
    note.hidden = false;
    note.textContent = p.kind === 'cash' ? paymentCopy.cashNote(pctText(config.cashDiscount.percent).replace(' %', '')) : `${paymentCopy.financingNote} ${paymentCopy.approvalFine}`;
  }

  // --- Chatbot con IA: consumo estimado (aparte del desarrollo) ---
  function renderChatbot(q: Quote) {
    $('#chatbot-step').hidden = !q.hasChatbot;
    $('#out-ai').hidden = !q.hasChatbot;
    if (!q.hasChatbot) return;
    const ch = config.chatbot;
    for (const btn of all<HTMLButtonElement>('[data-usage]')) {
      const id = btn.dataset.usage as UsageTierId;
      const tier = ch.tiers.find((t) => t.id === id);
      btn.hidden = !tier;
      if (!tier) continue;
      btn.setAttribute('aria-checked', String(state.chatbotUsage === id));
      btn.querySelector('[data-tier-label]')!.textContent = tier.label;
      btn.querySelector('[data-tier-sub]')!.textContent = id === 'custom' ? 'Tú defines el volumen' : `${tier.conversations.toLocaleString('de-DE')} conversaciones/mes`;
    }
    const custom = state.chatbotUsage === 'custom';
    $('#usage-custom-box').hidden = !custom;
    const input = $<HTMLInputElement>('#usage-custom');
    input.max = String(ch.customMaxConversations);
    if (custom && document.activeElement !== input) input.value = state.chatbotConversations ? String(state.chatbotConversations) : '';

    const u = q.usage;
    $('#usage-out').hidden = !u;
    if (!u) {
      $('#out-ai-text').textContent = 'Variable según uso. Elige un volumen en «Chatbot con IA» para estimarlo. No incluido en el total mensual.';
      return;
    }
    const amount = u.underOneCent ? 'menos de $0,01 USD' : formatCents(u.monthlyCents);
    const rates =
      ch.ratesSource === 'openrouter' && ch.ratesUpdatedAt
        ? `tarifas actualizadas el ${new Date(ch.ratesUpdatedAt).toLocaleDateString('es-VE')}`
        : 'tarifas de referencia';
    $('#usage-amount').textContent = `≈ ${amount} al mes`;
    $('#usage-detail').textContent =
      `${u.conversations.toLocaleString('de-DE')} conversaciones ≈ ${u.queries.toLocaleString('de-DE')} consultas y ` +
      `${(u.inputTokens + u.outputTokens).toLocaleString('de-DE')} tokens (${rates}). Estimación que puede variar; no es un compromiso. ` +
      'Se cobra aparte del desarrollo y no recibe descuento.';
    const lim = $('#usage-limit');
    lim.hidden = !u.overLimit;
    if (u.overLimit && u.monthlyLimitCents !== null) lim.textContent = `Supera el límite mensual configurado (${formatCents(u.monthlyLimitCents)}).`;
    $('#out-ai-text').textContent = `Variable según uso. Estimado ≈ ${amount}/mes con ${u.conversations.toLocaleString('de-DE')} conversaciones. No incluido en el total mensual; sin descuento.`;
  }

  // La barra fija solo aparece en móvil, con base elegida y mientras el cotizador está en pantalla
  let inView = false;
  const mq = matchMedia('(max-width: 1023px)');
  function updateBar() {
    const bar = $('#mbar');
    const summary = document.getElementById('quote-summary')!;
    const r = summary.getBoundingClientRect();
    const summaryVisible = r.top < innerHeight && r.bottom > 0;
    bar.hidden = !(mq.matches && inView && bar.dataset.hasBase === 'true' && !summaryVisible);
  }
  new IntersectionObserver((es) => { inView = es[0].isIntersecting; updateBar(); }, { threshold: 0 }).observe(root);
  addEventListener('scroll', updateBar, { passive: true });
  mq.addEventListener('change', updateBar);

  render();
}
