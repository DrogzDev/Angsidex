import {
  ApiError,
  createSession,
  getSession,
  requestContact,
  setProposalPaymentMode,
  streamMessage,
  updateProfile,
  type BusinessSize,
  type ChatLine,
  type LeadForm,
  type PaymentMode,
  type ProposalCard,
  type ProposalsEvent,
  type SessionInfo,
} from '../lib/advisor-api';
import { renderProposals, setCardPaymentMode, type CardHandlers } from './advisor-cards';

const STORAGE_KEY = 'angside.advisor.v1';
const root = document.getElementById('advisor');

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: Record<string, unknown>) => string;
      reset: (id?: string) => void;
    };
  }
}

if (root) init(root);

function init(root: HTMLElement) {
  const $ = <T extends HTMLElement>(sel: string) => root.querySelector<T>(sel)!;
  const panel = $('.adv-panel');
  const form = $<HTMLFormElement>('#adv-form');
  const chat = $('#adv-chat');
  const log = $('#adv-log');
  const composer = $<HTMLFormElement>('#adv-composer');
  const input = $<HTMLTextAreaElement>('#adv-input');
  const sendBtn = $<HTMLButtonElement>('#adv-send');
  const startBtn = $<HTMLButtonElement>('#adv-start');
  const contactBtn = $<HTMLButtonElement>('#adv-contact');
  const remainingEl = $('#adv-remaining');
  const sitekey = root.dataset.sitekey ?? '';

  let session: Pick<SessionInfo, 'session_id' | 'token'> | null = null;
  let remaining = 0;
  let streaming = false;
  let opener: HTMLElement | null = null;
  let tsWidget: string | undefined;
  let tsToken = '';
  let idempotencyKey = crypto.randomUUID();
  let busy = false;
  let focusTimer = 0;

  // --- Almacenamiento (solo ids de sesión, nunca datos personales) ---
  const store = {
    get(): { session_id: string; token: string } | null {
      try {
        const raw = sessionStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
      } catch {
        return null;
      }
    },
    set(v: { session_id: string; token: string }) {
      try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(v)); } catch { /* sin almacenamiento */ }
    },
    clear() {
      try { sessionStorage.removeItem(STORAGE_KEY); } catch { /* idem */ }
    },
  };

  // --- Abrir / cerrar ---
  function open(from?: HTMLElement | null) {
    opener = from ?? (document.activeElement as HTMLElement | null);
    root.hidden = false;
    document.documentElement.classList.add('adv-lock');
    requestAnimationFrame(() => root.classList.add('open'));
    void start();
    window.clearTimeout(focusTimer);
    focusTimer = window.setTimeout(() => {
      if (root.hidden || !root.classList.contains('open')) return; // se cerró antes de tiempo
      (chat.hidden ? form.querySelector<HTMLElement>('input') : input)?.focus();
    }, 320);
  }

  function close() {
    window.clearTimeout(focusTimer);
    root.classList.remove('open');
    document.documentElement.classList.remove('adv-lock');
    window.setTimeout(() => { root.hidden = true; }, 300);
    opener?.focus();
  }

  document.addEventListener('click', (e) => {
    const t = (e.target as HTMLElement).closest<HTMLElement>('[data-open-advisor]');
    if (t) {
      e.preventDefault();
      open(t);
    }
  });
  root.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('[data-adv-close]')) close();
  });
  // En document (no en el panel): si el foco cae en <body> (p. ej. al deshabilitarse un botón) Escape y Tab siguen funcionando.
  document.addEventListener('keydown', (e) => {
    if (root.hidden) return;
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
      return;
    }
    if (e.key !== 'Tab') return;
    // Trampa de foco dentro del panel
    const focusables = [...panel.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([tabindex="-1"]), select, textarea, summary, [tabindex="0"]')]
      .filter((el) => el.offsetParent !== null);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (!active || !panel.contains(active)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
    else if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
  });

  // --- Estado inicial: reanudar sesión o mostrar formulario ---
  async function start() {
    if (session) return;
    const saved = store.get();
    if (saved) {
      try {
        const info = await getSession(saved.session_id, saved.token);
        enterChat({ session_id: info.session_id, token: saved.token }, info);
        return;
      } catch {
        store.clear();
      }
    }
    showForm();
  }

  function showForm() {
    chat.hidden = true;
    form.hidden = false;
    loadTurnstile();
  }

  // --- Turnstile (carga diferida: solo al abrir el formulario) ---
  let tsRequested = false;
  function loadTurnstile() {
    if (!sitekey || tsWidget) return;
    const render = () => {
      if (!window.turnstile || tsWidget) return;
      tsWidget = window.turnstile.render($('#adv-turnstile'), {
        sitekey,
        theme: 'light',
        language: 'es',
        size: window.matchMedia('(max-width: 359px)').matches ? 'compact' : 'normal',
        callback: (token: string) => { tsToken = token; setError('turnstile_token', ''); },
        'expired-callback': () => { tsToken = ''; },
        'error-callback': () => { tsToken = ''; },
      });
    };
    if (window.turnstile) {
      render();
      return;
    }
    if (tsRequested) return;
    tsRequested = true;
    const s = document.createElement('script');
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
    s.async = true;
    s.onload = render;
    document.head.appendChild(s);
  }

  function resetTurnstile() {
    tsToken = '';
    if (window.turnstile && tsWidget) window.turnstile.reset(tsWidget);
  }

  // --- Formulario ---
  const fieldNames = ['name', 'business', 'email', 'phone', 'sector', 'need', 'whatsapp'] as const;

  function setError(field: string, message: string) {
    const el = form.querySelector<HTMLElement>(`[data-err="${field}"]`);
    if (el) el.textContent = message;
    const inputEl = form.elements.namedItem(field) as HTMLElement | null;
    inputEl?.setAttribute('aria-invalid', message ? 'true' : 'false');
  }

  const val = (name: string) => ((form.elements.namedItem(name) as HTMLInputElement | null)?.value ?? '').trim();

  function validate(): boolean {
    let ok = true;
    const need = (name: string, msg: string, min = 2) => {
      if (val(name).length < min) { setError(name, msg); ok = false; } else setError(name, '');
    };
    need('name', 'Escribe tu nombre.');
    need('business', 'Indica el nombre de tu negocio o proyecto.');
    need('sector', 'Indica el tipo de negocio o sector.');
    need('need', 'Cuéntanos con al menos 10 caracteres qué necesitas.', 10);

    const email = val('email');
    const phone = val('phone');
    setError('email', '');
    setError('phone', '');
    if (!email && !phone) {
      setError('email', 'Indica un correo o un teléfono.');
      ok = false;
    } else {
      if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setError('email', 'Correo inválido.'); ok = false; }
      if (phone && !/^\+?[0-9][0-9 ()\-]{5,24}$/.test(phone)) { setError('phone', 'Teléfono inválido.'); ok = false; }
    }
    const wa = val('whatsapp');
    if (wa && !/^\+?[0-9][0-9 ()\-]{5,24}$/.test(wa)) { setError('whatsapp', 'WhatsApp inválido.'); ok = false; } else setError('whatsapp', '');

    if (sitekey && !tsToken) { setError('turnstile_token', 'Completa la verificación de seguridad.'); ok = false; }
    return ok;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (busy) return; // evita envíos duplicados
    $('#adv-form-error').textContent = '';
    if (!validate()) {
      form.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      return;
    }
    busy = true;
    startBtn.disabled = true;
    startBtn.setAttribute('aria-busy', 'true');
    const payload: LeadForm = {
      name: val('name'), business: val('business'), email: val('email'), phone: val('phone'), sector: val('sector'), need: val('need'),
      whatsapp: val('whatsapp'), location: val('location'), has_website: val('has_website') as LeadForm['has_website'],
      budget_range: val('budget_range'), start_when: val('start_when'),
      marketing_consent: (form.elements.namedItem('marketing_consent') as HTMLInputElement).checked,
      website_url: val('website_url'), turnstile_token: tsToken,
    };
    try {
      const info = await createSession(payload, idempotencyKey);
      store.set({ session_id: info.session_id, token: info.token });
      enterChat(info, info);
    } catch (err) {
      const api = err instanceof ApiError ? err : new ApiError('error', 'No pudimos iniciar la conversación.', 0);
      for (const [field, msgs] of Object.entries(api.fieldErrors)) setError(field, msgs[0] ?? '');
      $('#adv-form-error').textContent = api.message;
      idempotencyKey = crypto.randomUUID(); // el token de Turnstile es de un solo uso: nueva verificación y nueva clave
      resetTurnstile();
    } finally {
      busy = false;
      startBtn.disabled = false;
      startBtn.removeAttribute('aria-busy');
    }
  });

  form.addEventListener('input', (e) => {
    const t = e.target as HTMLInputElement;
    if (t.name && t.getAttribute('aria-invalid') === 'true') setError(t.name, '');
  });

  // --- Conversación ---
  function enterChat(s: Pick<SessionInfo, 'session_id' | 'token'>, info: SessionInfo) {
    session = { session_id: s.session_id, token: s.token };
    remaining = info.remaining_messages;
    log.replaceChildren();
    for (const m of info.messages) {
      if (m.role === 'event') addProposals(m.event);
      else addMessage(m.role, m.content);
    }
    updateRemaining();
    form.hidden = true;
    chat.hidden = false;
    scrollLog();
    input.focus();
  }

  /** Los modelos a veces responden con markdown; el chat muestra texto plano limpio. */
  function plain(text: string): string {
    return text
      .replace(/\*\*(.+?)\*\*/gs, '$1')
      .replace(/__(.+?)__/gs, '$1')
      .replace(/\*\*$/g, '') // marcador de negrita a medio llegar durante el streaming
      .replace(/^#{1,6}\s+/gm, '')
      .replace(/^\s*[-*]\s+/gm, '• ');
  }

  function addMessage(role: ChatLine['role'] | 'notice', text: string): HTMLElement {
    const el = document.createElement('div');
    el.className = `adv-msg ${role}`;
    el.textContent = role === 'assistant' ? plain(text) : text; // textContent: nunca HTML del modelo
    log.appendChild(el);
    scrollLog();
    return el;
  }

  function scrollLog() {
    log.scrollTop = log.scrollHeight;
  }

  function updateRemaining() {
    remainingEl.textContent = remaining > 0 ? `${remaining} mensajes disponibles` : 'Límite alcanzado';
    const off = streaming || remaining <= 0;
    sendBtn.disabled = off;
    input.disabled = remaining <= 0;
  }

  // --- Tarjetas de propuesta ---
  const cardHandlers: CardHandlers = {
    onApply(card: ProposalCard) {
      window.dispatchEvent(new CustomEvent('angside:apply-quote', { detail: { config: card.config } }));
      close();
      document.getElementById('calculadora')?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    },
    async onRequest(card: ProposalCard, button: HTMLButtonElement) {
      if (!session) return;
      button.disabled = true;
      try {
        await requestContact(session.session_id, session.token, 'Solicitud desde una tarjeta de propuesta', card.id);
        button.textContent = 'Propuesta solicitada ✓';
        markContactSent();
        addMessage('notice', `Registramos tu solicitud de la propuesta ${card.name}. El equipo de Angside te contactará para continuar.`);
      } catch (err) {
        button.disabled = false;
        addMessage('notice', err instanceof ApiError ? err.message : 'No pudimos registrar tu solicitud. Inténtalo de nuevo.');
      }
    },
    async onPaymentMode(card: ProposalCard, mode: PaymentMode) {
      if (!session) throw new Error('sin sesión');
      await setProposalPaymentMode(session.session_id, session.token, card.id, mode);
      setCardPaymentMode(log, card.id, mode);
    },
    onNegotiate(card: ProposalCard) {
      void sendUserMessage(`Quiero negociar la propuesta ${card.name}: me parece elevado el presupuesto.`);
    },
    async onSizeChange(size: BusinessSize) {
      if (!session) throw new Error('sin sesión');
      const res = await updateProfile(session.session_id, session.token, size);
      // Actualiza las demás etiquetas de clasificación visibles en la conversación.
      log.querySelectorAll<HTMLElement>('[data-profile-size]').forEach((n) => { n.textContent = res.profile.size_label; });
    },
  };

  function addProposals(ev: ProposalsEvent) {
    log.appendChild(renderProposals(ev, cardHandlers));
    scrollLog();
  }

  // --- Envío de mensajes ---
  async function sendUserMessage(text: string) {
    if (!text || streaming || !session || remaining <= 0) return;
    addMessage('user', text);
    const typing = addMessage('assistant', '');
    typing.classList.add('typing');
    let bubble: HTMLElement | null = null; // se crea al llegar texto: las tarjetas quedan antes de la explicación
    let bubbleRaw = '';
    streaming = true;
    remaining -= 1;
    updateRemaining();
    const dropTyping = () => typing.remove();
    try {
      await streamMessage(session.session_id, session.token, text, (ev) => {
        if (ev.type === 'delta') {
          dropTyping();
          if (!bubble) {
            bubble = addMessage('assistant', '');
            bubbleRaw = '';
          }
          bubbleRaw += ev.text;
          bubble.textContent = plain(bubbleRaw);
          scrollLog();
        } else if (ev.type === 'proposals') {
          dropTyping();
          bubble = null;
          addProposals(ev);
        } else if (ev.type === 'payment_mode') {
          setCardPaymentMode(log, ev.proposal_id, ev.mode);
        } else if (ev.type === 'profile') {
          log.querySelectorAll<HTMLElement>('[data-profile-size]').forEach((n) => { n.textContent = ev.profile.size_label; });
        } else if (ev.type === 'contact_requested') {
          markContactSent();
        } else if (ev.type === 'price_notice') {
          addMessage('notice', ev.message);
        } else if (ev.type === 'error') {
          dropTyping();
          addMessage('notice', ev.message);
          if (ev.code === 'session_limit' || ev.code === 'budget_exhausted') remaining = 0;
        }
      });
    } catch (err) {
      const api = err instanceof ApiError ? err : null;
      if (api?.status === 401) {
        store.clear();
        session = null;
        addMessage('notice', 'Tu sesión expiró. Vuelve a abrir el asistente para continuar.');
      } else {
        addMessage('notice', api?.message ?? 'Ocurrió un error. Inténtalo de nuevo.');
      }
      if (api && (api.code === 'session_limit' || api.code === 'budget_exhausted')) remaining = 0;
      else if (api && api.status === 429 && api.code === 'rate_limited') remaining += 1; // no consumió cupo
    } finally {
      dropTyping();
      streaming = false;
      updateRemaining();
      if (remaining > 0) input.focus();
    }
  }

  composer.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || streaming) return;
    input.value = '';
    autosize();
    void sendUserMessage(text);
  });

  function autosize() {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }
  input.addEventListener('input', autosize);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      composer.requestSubmit();
    }
  });

  function markContactSent() {
    contactBtn.disabled = true;
    contactBtn.textContent = 'Solicitud enviada. Te contactaremos.';
  }

  contactBtn.addEventListener('click', async () => {
    if (!session || contactBtn.disabled) return;
    contactBtn.disabled = true;
    try {
      await requestContact(session.session_id, session.token, 'Solicitud desde el botón del asistente');
      markContactSent();
      addMessage('notice', 'Listo, registramos tu solicitud. El equipo de Angside te contactará con una propuesta personalizada.');
    } catch (err) {
      contactBtn.disabled = false;
      addMessage('notice', err instanceof ApiError ? err.message : 'No pudimos registrar tu solicitud. Inténtalo de nuevo.');
    }
  });
}
