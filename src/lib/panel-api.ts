/**
 * Cliente de la API del panel. Sesión por cookie HttpOnly + protección CSRF:
 * el token se pide al backend, vive solo en memoria y viaja en la cabecera X-CSRFToken en cada petición que modifica datos.
 */

export type Role = 'staff' | 'client';

export interface PanelUser {
  username: string;
  name: string;
  role: Role;
}

export interface LeadRow {
  id: number;
  created_at: string;
  name: string;
  business: string;
  email: string;
  phone: string;
  whatsapp: string;
  sector: string;
  budget_range: string;
  complexity: string;
  complexity_label: string;
  budget_calculated_usd: number | null;
  status: string;
  status_label: string;
  negotiation_requested: boolean;
  payment_modes: string[];
  proposals: number;
}

export interface Overview {
  leads: { total: number; today: number; last_7_days: number; negotiating: number; by_status: { status: string; label: string; count: number }[] };
  quotes: { total: number; last_7_days: number };
  payment_modes: { mode: string; count: number }[];
  ai: { spent_today_usd: number; spent_month_usd: number; daily_budget_usd: number; monthly_budget_usd: number; sessions: number };
  recent_leads: LeadRow[];
}

export interface LeadList {
  items: LeadRow[];
  page: number;
  pages: number;
  total: number;
  statuses: { value: string; label: string }[];
}

export interface ConversationMessage {
  role: 'user' | 'assistant';
  at: string;
  text: string;
}

export interface LeadDetail extends LeadRow {
  location: string;
  need: string;
  needs_summary: string;
  has_website: string;
  start_when: string;
  business_size: string;
  budget_stated_usd: number | null;
  recommended_features: string[];
  negotiation: { requested: boolean; initial_budget: number | null; ideal_budget: number | null; reason: string };
  objections: { category?: string; detail?: string }[];
  marketing_consent: boolean;
  notes: string;
  proposals_detail: {
    id: number; round: number; tier: string; created_at: string; development_total: number; payment_mode: string;
    pricing_version: number | null; complexity: string; within_budget: boolean | null; requires_custom_quote: boolean; requested: boolean; features: string[];
  }[];
  conversations: { session_id: string; started_at: string; tokens: number; cost_usd: number; messages: ConversationMessage[] }[];
}

export interface QuoteList {
  items: { reference: string; created_at: string; payment_mode: string; development_original: number; development_total: number; config: string; pricing_version: number }[];
  page: number;
  pages: number;
  total: number;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public retryAfter = 0) {
    super(message);
  }
}

export function createPanelApi(base: string) {
  let csrf = '';

  async function raw(path: string, init: RequestInit & { json?: unknown } = {}): Promise<Response> {
    const method = (init.method ?? 'GET').toUpperCase();
    const headers: Record<string, string> = {};
    if (init.json !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && csrf) headers['X-CSRFToken'] = csrf;
    return fetch(`${base}/api/panel${path}`, {
      method,
      headers,
      credentials: 'include',
      body: init.json !== undefined ? JSON.stringify(init.json) : undefined,
    });
  }

  async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}, retried = false): Promise<T> {
    if (!csrf && (init.method ?? 'GET').toUpperCase() !== 'GET') await refreshCsrf();
    let res: Response;
    try {
      res = await raw(path, init);
    } catch {
      throw new ApiError(0, 'network', 'No se pudo conectar con el servidor.');
    }
    const body = await res.json().catch(() => ({}));
    if (res.ok) return body as T;
    if (res.status === 403 && body.code === 'csrf_failed' && !retried) {
      await refreshCsrf();
      return request<T>(path, init, true);
    }
    throw new ApiError(res.status, body.code ?? 'error', body.detail ?? 'Ocurrió un error inesperado.', Number(body.retry_after ?? 0));
  }

  async function refreshCsrf(): Promise<void> {
    const res = await raw('/csrf');
    const body = await res.json().catch(() => ({}));
    csrf = body.csrf ?? '';
  }

  return {
    /** Consulta la sesión actual; también deja listo el token CSRF. */
    async me(): Promise<PanelUser | null> {
      const body = await request<{ authenticated: boolean; user: PanelUser | null; csrf: string }>('/me');
      csrf = body.csrf;
      return body.authenticated ? body.user : null;
    },
    async login(username: string, password: string): Promise<PanelUser> {
      if (!csrf) await refreshCsrf();
      const body = await request<{ user: PanelUser; csrf: string }>('/login', { method: 'POST', json: { username, password } });
      csrf = body.csrf;
      return body.user;
    },
    async logout(): Promise<void> {
      const body = await request<{ csrf: string }>('/logout', { method: 'POST', json: {} });
      csrf = body.csrf;
    },
    overview: () => request<Overview>('/overview'),
    leads: (p: { q?: string; status?: string; page?: number }) => {
      const qs = new URLSearchParams();
      if (p.q) qs.set('q', p.q);
      if (p.status) qs.set('status', p.status);
      if (p.page && p.page > 1) qs.set('page', String(p.page));
      return request<LeadList>(`/leads${qs.size ? `?${qs}` : ''}`);
    },
    lead: (id: number) => request<LeadDetail>(`/leads/${id}`),
    updateLead: (id: number, patch: { status?: string; notes?: string }) => request<LeadDetail>(`/leads/${id}`, { method: 'PATCH', json: patch }),
    quotes: (page = 1) => request<QuoteList>(`/quotes${page > 1 ? `?page=${page}` : ''}`),
  };
}

export type PanelApi = ReturnType<typeof createPanelApi>;
