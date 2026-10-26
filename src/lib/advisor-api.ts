/** Cliente tipado de la API de Angside AI Advisor. La clave de OpenRouter vive solo en el backend. */

export interface LeadForm {
  name: string;
  business: string;
  email: string;
  phone: string;
  sector: string;
  need: string;
  whatsapp: string;
  location: string;
  has_website: '' | 'yes' | 'no';
  budget_range: string;
  start_when: string;
  marketing_consent: boolean;
  website_url: string;
  turnstile_token: string;
}

export type BusinessSize = 'small' | 'medium' | 'large';

/** Clasificación orientativa del cliente. Es editable y nunca cambia los precios. */
export interface ProfileInfo {
  size: BusinessSize | '';
  size_label: string;
  size_confirmed: boolean;
  complexity: string;
  complexity_label: string;
}

export interface ProposalFeature {
  id: string;
  kind: 'base' | 'module' | 'dependency' | 'included';
  label: string;
  price: number;
  from: boolean;
  benefit: string;
}

export type PaymentMode = 'cash' | 'm3' | 'm6' | 'm9';

/** Modalidad de pago calculada por Django (importes en USD). */
export interface PaymentOption {
  mode: PaymentMode;
  label: string;
  kind: 'cash' | 'financing';
  available: boolean;
  unavailable_reason: string;
  original: number;
  discount_percent: string;
  discount: number;
  surcharge_percent: string;
  surcharge: number;
  total: number;
  savings: number;
  initial_percent: string;
  initial: number;
  installment_count: number;
  installment: number;
  every_months: number;
  term_months: number;
  cadence?: string;
  requires_approval: boolean;
  schedule: { label: string; due: string; amount: number }[];
}

/** Tarjeta de propuesta: datos calculados y validados por Django (nunca texto libre del modelo). */
export interface ProposalCard {
  id: number;
  round: number;
  tier: 'essential' | 'recommended' | 'complete' | 'adjusted';
  name: string;
  recommended_type: string;
  config: string;
  development_total: number;
  development_from: boolean;
  payments: { start: number; delivery: number };
  monthly: { hosting: number; billing: number; maintenance: number; total: number; from: boolean };
  monthly_lines: { label: string; usd: number; from: boolean }[];
  features: ProposalFeature[];
  custom_items: string[];
  requires_custom_quote: boolean;
  custom_quote_text: string;
  complexity: string;
  complexity_label: string;
  complexity_factors: string[];
  within_budget: boolean | null;
  budget_ceiling: number | null;
  timeline: string;
  notices: string[];
  complete: boolean;
  requested: boolean;
  payment_options: PaymentOption[];
  /** Modalidad elegida (null = todavía sin elegir). */
  payment_mode: PaymentMode | null;
  pricing_version: number | null;
  /** Solo si la propuesta incluye el chatbot con IA: consumo variable, aparte del desarrollo. */
  ai_usage: { model: string; conversations: number | null; monthly: number | null; under_one_cent: boolean; note: string } | null;
}

export interface ProposalsEvent {
  type: 'proposals';
  round: number;
  profile: ProfileInfo;
  proposals: ProposalCard[];
}

export interface ChatLine {
  role: 'user' | 'assistant';
  content: string;
}

/** Entrada del historial: texto o tarjetas de propuesta, en el orden en que ocurrieron. */
export type ChatEntry = ChatLine | { role: 'event'; event: ProposalsEvent };

export interface SessionInfo {
  session_id: string;
  token: string;
  remaining_messages: number;
  profile: ProfileInfo;
  messages: ChatEntry[];
}

export type StreamEvent =
  | { type: 'delta'; text: string }
  | ProposalsEvent
  | { type: 'profile'; profile: ProfileInfo }
  | { type: 'payment_mode'; proposal_id: number; mode: PaymentMode }
  | { type: 'negotiation' }
  | { type: 'contact_requested' }
  | { type: 'price_notice'; message: string }
  | { type: 'error'; code: string; message: string }
  | { type: 'done' };

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public fieldErrors: Record<string, string[]> = {},
    public retryAfter?: number,
  ) {
    super(message);
  }
}

export const apiBase = (import.meta.env.PUBLIC_API_URL as string | undefined)?.replace(/\/$/, '') ?? '';

async function parseError(res: Response): Promise<ApiError> {
  let body: { code?: string; message?: string; errors?: Record<string, string[]>; retry_after?: number } = {};
  try {
    body = await res.json();
  } catch {
    /* respuesta sin JSON */
  }
  return new ApiError(body.code ?? 'error', body.message ?? 'No pudimos completar la solicitud.', res.status, body.errors ?? {}, body.retry_after);
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${apiBase}${path}`, init);
  } catch {
    throw new ApiError('network', 'No hay conexión con el servidor. Revisa tu internet e inténtalo de nuevo.', 0);
  }
  if (!res.ok) throw await parseError(res);
  return res.json() as Promise<T>;
}

const json = (token?: string, extra: Record<string, string> = {}): Record<string, string> => ({
  'Content-Type': 'application/json',
  ...(token ? { Authorization: `Bearer ${token}` } : {}),
  ...extra,
});

export function createSession(form: LeadForm, idempotencyKey: string): Promise<SessionInfo> {
  return request('/api/ai/sessions', {
    method: 'POST',
    headers: json(undefined, { 'Idempotency-Key': idempotencyKey }),
    body: JSON.stringify(form),
  });
}

export function getSession(id: string, token: string): Promise<SessionInfo> {
  return request(`/api/ai/sessions/${id}`, { headers: json(token) });
}

export function requestContact(id: string, token: string, message: string, proposalId?: number): Promise<{ ok: boolean }> {
  return request(`/api/ai/sessions/${id}/request-contact`, {
    method: 'POST',
    headers: json(token),
    body: JSON.stringify({ message, ...(proposalId ? { proposal_id: proposalId } : {}) }),
  });
}

export function updateProfile(id: string, token: string, businessSize: BusinessSize): Promise<{ profile: ProfileInfo }> {
  return request(`/api/ai/sessions/${id}/profile`, { method: 'PATCH', headers: json(token), body: JSON.stringify({ business_size: businessSize }) });
}

/** El visitante cambia la modalidad de pago de una tarjeta; Django valida que esté entre las calculadas. */
export function setProposalPaymentMode(id: string, token: string, proposalId: number, mode: PaymentMode): Promise<{ proposal: ProposalCard }> {
  return request(`/api/ai/sessions/${id}/proposals/${proposalId}/payment-mode`, { method: 'POST', headers: json(token), body: JSON.stringify({ mode }) });
}

/** Envía un mensaje y entrega los eventos SSE a medida que llegan. */
export async function streamMessage(id: string, token: string, message: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${apiBase}/api/ai/sessions/${id}/messages`, {
      method: 'POST',
      headers: json(token),
      body: JSON.stringify({ message }),
      signal,
    });
  } catch (e) {
    if ((e as DOMException).name === 'AbortError') return;
    throw new ApiError('network', 'No hay conexión con el servidor. Revisa tu internet e inténtalo de nuevo.', 0);
  }
  if (!res.ok || !res.body) throw await parseError(res);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (!chunk.startsWith('data: ')) continue;
      try {
        onEvent(JSON.parse(chunk.slice(6)) as StreamEvent);
      } catch {
        /* evento malformado: se ignora */
      }
    }
  }
}
