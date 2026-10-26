/**
 * Condiciones comerciales vigentes. La fuente de verdad es Django Admin; el cotizador las descarga al cargar.
 * Si la API no responde (o devuelve algo inválido) se usan los valores por defecto de `data/commercial.ts`,
 * que son los mismos con los que se siembra la base de datos.
 */
import { defaultCommercialConfig, paymentModeIds, type CommercialConfig } from '../data/commercial';

const DECIMAL = /^\d+(\.\d+)?$/;

/** Comprobación mínima de forma: rechaza respuestas que romperían el cálculo en vez de mostrar importes erróneos. */
export function isCommercialConfig(value: unknown): value is CommercialConfig {
  const c = value as Partial<CommercialConfig> | null;
  if (!c || typeof c !== 'object') return false;
  const d = c.cashDiscount;
  const ch = c.chatbot;
  if (!d || typeof d.enabled !== 'boolean' || !DECIMAL.test(d.percent) || !DECIMAL.test(d.minDevelopmentUsd) || !Array.isArray(d.excludedIds)) return false;
  if (!DECIMAL.test(String(c.financingMinDevelopmentUsd)) || !Array.isArray(c.plans) || typeof c.version !== 'number') return false;
  const plansOk = c.plans.every(
    (p) =>
      paymentModeIds.includes(p.id) &&
      DECIMAL.test(p.surchargePercent) &&
      DECIMAL.test(p.initialPercent) &&
      Number.isInteger(p.installments) && p.installments > 0 &&
      Number.isInteger(p.everyMonths) && p.everyMonths > 0 &&
      Number.isInteger(p.termMonths),
  );
  if (!plansOk) return false;
  return (
    !!ch &&
    DECIMAL.test(ch.priceInPerM) &&
    DECIMAL.test(ch.priceOutPerM) &&
    DECIMAL.test(ch.marginPercent) &&
    Number.isInteger(ch.queriesPerConversation) &&
    Number.isInteger(ch.inputTokensPerQuery) &&
    Number.isInteger(ch.outputTokensPerQuery) &&
    Array.isArray(ch.tiers) && ch.tiers.length > 0
  );
}

export async function fetchCommercialConfig(apiBase: string, signal?: AbortSignal): Promise<CommercialConfig> {
  if (!apiBase) return defaultCommercialConfig;
  try {
    const res = await fetch(`${apiBase}/api/commercial/config`, { signal, headers: { Accept: 'application/json' } });
    if (!res.ok) return defaultCommercialConfig;
    const body: unknown = await res.json();
    return isCommercialConfig(body) ? body : defaultCommercialConfig;
  } catch {
    return defaultCommercialConfig;
  }
}

/** Referencia corta que identifica la cotización en el mensaje de WhatsApp y en el registro de Django. */
export function newQuoteReference(): string {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return `ANG-${[...bytes].map((b) => alphabet[b % alphabet.length]).join('')}`;
}

/** Registra la cotización en Django (sin datos personales). Falla en silencio: WhatsApp no depende de esto. */
export async function registerQuote(apiBase: string, body: { reference: string; config: string; version: number }): Promise<boolean> {
  if (!apiBase) return false;
  try {
    const res = await fetch(`${apiBase}/api/commercial/quotes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      keepalive: true,
    });
    return res.ok;
  } catch {
    return false;
  }
}
