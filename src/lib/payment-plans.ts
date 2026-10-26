/**
 * Modalidades de pago del desarrollo y estimación de consumo de IA.
 * Todo el cálculo es entero (centavos / BigInt): sin flotantes, con redondeo "mitad hacia arriba" y la diferencia de
 * centavos absorbida por el último pago. backend/commercial/engine.py reproduce estas reglas con Decimal.
 */
import type { ChatbotAiConfig, CommercialConfig, PaymentModeId } from '../data/commercial';

// --- Aritmética decimal exacta ---

/** "20.833333" → 20833333n (escala 6). Redondea mitad hacia arriba si el texto trae más decimales. */
export function toScaled(text: string, scale: number): bigint {
  const m = /^(-?)(\d+)(?:\.(\d*))?$/.exec(String(text).trim());
  if (!m) throw new Error(`Número decimal inválido: ${text}`);
  const frac = m[3] ?? '';
  const padded = (frac + '0'.repeat(scale)).slice(0, scale);
  let value = BigInt(m[2] + padded);
  if (frac.length > scale && Number(frac[scale]) >= 5) value += 1n;
  return m[1] === '-' ? -value : value;
}

/** Cociente entero con redondeo mitad hacia arriba (valores no negativos). */
function divRound(n: bigint, d: bigint): bigint {
  return (2n * n + d) / (2n * d);
}

export const toCents = (usd: number): number => Math.round(usd * 100);
/** Centavos → USD como número (entero cuando no hay centavos). */
export const fromCents = (cents: number): number => cents / 100;

/** `cents` × `percent` % con redondeo monetario a centavos. */
export function percentOf(cents: number, percent: string): number {
  return Number(divRound(BigInt(cents) * toScaled(percent, 6), 100_000_000n));
}

// --- Modalidades de pago ---

export interface DevLine {
  kind: 'base' | 'module' | 'dependency';
  id: string;
  price: number;
  /** Otros ids del catálogo que esta línea también es (una base que equivale a un módulo). */
  alsoIds?: string[];
}

export interface ScheduleItem {
  /** "Inicial", "Cuota 2 de 6" o "Pago único". */
  label: string;
  /** Cuándo vence, en lenguaje claro. */
  due: string;
  amountCents: number;
}

export interface PaymentBreakdown {
  modeId: PaymentModeId;
  kind: 'cash' | 'financing';
  /** False si la modalidad no puede ofrecerse (desactivada o por debajo del mínimo comercial). */
  available: boolean;
  unavailableReason: string;
  /** Precio base del desarrollo, sin descuento ni incremento. */
  originalCents: number;
  /** Parte del desarrollo sobre la que se aplicó el descuento (excluye módulos exentos). */
  discountableCents: number;
  discountPercent: string;
  discountCents: number;
  surchargePercent: string;
  surchargeCents: number;
  /** Total de desarrollo de la modalidad (lo que se paga, o lo que se financia). */
  totalCents: number;
  /** Cuánto ahorra frente al precio original (solo contado). */
  savingsCents: number;
  initialPercent: string;
  initialCents: number;
  installmentCount: number;
  installmentCents: number;
  everyMonths: number;
  termMonths: number;
  schedule: ScheduleItem[];
  /** Todo plan financiado exige aprobación manual de Angside. */
  requiresApproval: boolean;
}

const blank = (modeId: PaymentModeId, originalCents: number): PaymentBreakdown => ({
  modeId,
  kind: modeId === 'cash' ? 'cash' : 'financing',
  available: true,
  unavailableReason: '',
  originalCents,
  discountableCents: 0,
  discountPercent: '0',
  discountCents: 0,
  surchargePercent: '0',
  surchargeCents: 0,
  totalCents: originalCents,
  savingsCents: 0,
  initialPercent: '0',
  initialCents: 0,
  installmentCount: 0,
  installmentCents: 0,
  everyMonths: 0,
  termMonths: 0,
  schedule: [],
  requiresApproval: modeId !== 'cash',
});

/**
 * Calcula una modalidad a partir de las líneas de desarrollo con su precio de catálogo.
 * Siempre parte del precio original: aplicarla dos veces da el mismo resultado (el descuento nunca se acumula).
 */
export function computePayment(lines: DevLine[], modeId: PaymentModeId, config: CommercialConfig): PaymentBreakdown {
  const originalCents = lines.reduce((sum, l) => sum + toCents(l.price), 0);
  const out = blank(modeId, originalCents);

  if (modeId === 'cash') {
    const d = config.cashDiscount;
    const excluded = new Set(d.excludedIds);
    const isExcluded = (l: DevLine) => excluded.has(l.id) || (l.alsoIds ?? []).some((id) => excluded.has(id));
    const discountable = lines.filter((l) => !isExcluded(l)).reduce((sum, l) => sum + toCents(l.price), 0);
    const belowMin = originalCents < toCents(Number(d.minDevelopmentUsd));
    out.discountableCents = discountable;
    if (d.enabled && !belowMin && discountable > 0) {
      out.discountPercent = d.percent;
      out.discountCents = percentOf(discountable, d.percent);
    } else if (d.enabled && belowMin) {
      out.unavailableReason = `El descuento de contado aplica desde $${d.minDevelopmentUsd} de desarrollo.`;
    }
    out.totalCents = originalCents - out.discountCents;
    out.savingsCents = out.discountCents;
    out.installmentCount = 1;
    out.schedule = originalCents > 0 ? [{ label: 'Pago único', due: 'Al confirmar el proyecto', amountCents: out.totalCents }] : [];
    return out;
  }

  const plan = config.plans.find((p) => p.id === modeId);
  if (!plan || !plan.enabled) {
    out.available = false;
    out.unavailableReason = 'Esta modalidad no está disponible por ahora.';
    return out;
  }
  out.surchargePercent = plan.surchargePercent;
  out.initialPercent = plan.initialPercent;
  out.termMonths = plan.termMonths;
  out.everyMonths = plan.everyMonths;
  out.installmentCount = plan.installments;
  if (originalCents < toCents(Number(config.financingMinDevelopmentUsd))) {
    out.available = false;
    out.unavailableReason = `El financiamiento aplica desde $${config.financingMinDevelopmentUsd} de desarrollo. Consulta con Angside.`;
  }

  out.surchargeCents = percentOf(originalCents, plan.surchargePercent);
  out.totalCents = originalCents + out.surchargeCents;
  out.initialCents = percentOf(out.totalCents, plan.initialPercent);
  const remaining = out.totalCents - out.initialCents;
  const each = Number(divRound(BigInt(remaining), BigInt(plan.installments)));
  out.installmentCents = each;
  if (originalCents > 0) {
    out.schedule.push({ label: 'Inicial', due: 'Al aprobar el plan y firmar el contrato', amountCents: out.initialCents });
    for (let i = 1; i <= plan.installments; i++) {
      // El último pago absorbe cualquier diferencia de centavos.
      const amount = i === plan.installments ? remaining - each * (plan.installments - 1) : each;
      out.schedule.push({ label: `Cuota ${i} de ${plan.installments}`, due: `Mes ${i * plan.everyMonths}`, amountCents: amount });
    }
  }
  return out;
}

export function computeAllPayments(lines: DevLine[], config: CommercialConfig): PaymentBreakdown[] {
  const ids: PaymentModeId[] = ['cash', ...config.plans.map((p) => p.id)];
  return ids.map((id) => computePayment(lines, id, config));
}

/** Nombre corto de la modalidad para botones y resúmenes. */
export function modeLabel(modeId: PaymentModeId, config: CommercialConfig): string {
  if (modeId === 'cash') return 'Contado';
  const plan = config.plans.find((p) => p.id === modeId);
  return plan ? `${plan.termMonths} meses` : modeId;
}

/** Cómo se describen las cuotas: "3 cuotas mensuales", "3 cuotas trimestrales"… */
export function cadenceText(count: number, everyMonths: number): string {
  const unit = everyMonths === 1 ? 'mensuales' : everyMonths === 3 ? 'trimestrales' : `cada ${everyMonths} meses`;
  return `${count} cuota${count === 1 ? '' : 's'} ${unit}`;
}

// --- Consumo de IA del chatbot ---

export interface UsageEstimate {
  conversations: number;
  queries: number;
  inputTokens: number;
  outputTokens: number;
  /** Estimación mensual en centavos (con margen de administración, si aplica). */
  monthlyCents: number;
  /** Fracción de centavo: el costo real es menor que un centavo. */
  underOneCent: boolean;
  /** El estimado supera el tope mensual configurado. */
  overLimit: boolean;
  monthlyLimitCents: number | null;
}

/**
 * Estimación de consumo de inferencia. Depende de los tokens, no solo del número de conversaciones:
 * consultas por conversación × tokens por consulta × tarifa por millón de tokens.
 */
export function estimateChatbotUsage(conversations: number, cfg: ChatbotAiConfig): UsageEstimate {
  const convs = Math.max(0, Math.floor(conversations));
  const queries = convs * cfg.queriesPerConversation;
  const inputTokens = queries * cfg.inputTokensPerQuery;
  const outputTokens = queries * cfg.outputTokensPerQuery;
  // tokens × (USD por millón escalado ×1e6) = USD × 1e-12
  const raw = BigInt(inputTokens) * toScaled(cfg.priceInPerM, 6) + BigInt(outputTokens) * toScaled(cfg.priceOutPerM, 6);
  const withMargin = raw * (100_000_000n + toScaled(cfg.marginPercent, 6));
  const monthlyCents = Number(divRound(withMargin, 10_000_000_000n * 100_000_000n));
  const limit = cfg.monthlyLimitUsd == null ? null : toCents(Number(cfg.monthlyLimitUsd));
  return {
    conversations: convs,
    queries,
    inputTokens,
    outputTokens,
    monthlyCents,
    underOneCent: monthlyCents === 0 && raw > 0n,
    overLimit: limit !== null && monthlyCents > limit,
    monthlyLimitCents: limit,
  };
}
