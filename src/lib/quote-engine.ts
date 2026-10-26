import {
  baseById,
  bases,
  billingPlanById,
  billingPlans,
  dependencies,
  hostingById,
  hostingOptions,
  maintenance,
  moduleById,
  modules,
  paymentSplit,
  type BaseId,
  type BillingPlanId,
  type Dependency,
  type DependencyId,
  type HostingId,
  type ModuleId,
} from '../data/pricing';
import {
  defaultCommercialConfig,
  paymentCopy,
  paymentModeIds,
  usageTierIds,
  type CommercialConfig,
  type PaymentModeId,
  type UsageTierId,
} from '../data/commercial';
import {
  cadenceText,
  computeAllPayments,
  estimateChatbotUsage,
  fromCents,
  type PaymentBreakdown,
  type UsageEstimate,
} from './payment-plans';

export interface QuoteState {
  baseId: BaseId | null;
  moduleIds: ModuleId[];
  /** Dependencias que el usuario aceptó agregar explícitamente. */
  confirmedDeps: DependencyId[];
  hostingId: HostingId;
  maintenance: boolean;
  /** Plan de facturación; solo aplica si se eligió el módulo de facturación digital. */
  billingPlanId: BillingPlanId | null;
  /** Modalidad de pago elegida al final; null = aún sin elegir (pago estándar en dos partes). */
  paymentModeId: PaymentModeId | null;
  /** Volumen de uso del chatbot (solo si el presupuesto incluye el chatbot). */
  chatbotUsage: UsageTierId | null;
  /** Conversaciones mensuales cuando chatbotUsage es "custom". */
  chatbotConversations: number | null;
}

export type ModuleStatus = 'included' | 'selected' | 'unavailable' | 'available';

export interface QuoteLine {
  kind: 'base' | 'module' | 'dependency';
  id: string;
  label: string;
  price: number;
  from: boolean;
}

export interface PendingDependency {
  dependency: Dependency;
  requiredBy: string[];
}

export interface Quote {
  lines: QuoteLine[];
  /** Funcionalidades incluidas en la base sin costo adicional. */
  included: string[];
  developmentTotal: number;
  /** El desarrollo se paga en dos partes: para arrancar y al entregar con todo funcionando. */
  payments: { start: number; delivery: number };
  hostingMonthly: number;
  /** Costo mensual fijo del plan de facturación (0 si no aplica). */
  billingMonthly: number;
  /** Se eligió facturación digital pero falta escoger el plan de facturación. */
  missingBillingPlan: boolean;
  maintenanceMonthly: number;
  monthlyTotal: number;
  /** El desarrollo incluye algún monto "desde" (el alcance real se evalúa). */
  developmentFrom: boolean;
  /** El total mensual incluye algún monto "desde". */
  monthlyFrom: boolean;
  pending: PendingDependency[];
  notices: string[];
  hostingNeedsEvaluation: boolean;
  /** Hay base y no quedan dependencias sin resolver. */
  complete: boolean;
  /** Cálculo de la modalidad elegida (null si no se eligió ninguna). */
  payment: PaymentBreakdown | null;
  /** Las cuatro modalidades calculadas, para el selector. */
  paymentOptions: PaymentBreakdown[];
  hasChatbot: boolean;
  /** Estimación de consumo de IA del chatbot: recurrente, variable y fuera del total mensual. */
  usage: UsageEstimate | null;
}

export const initialState: QuoteState = {
  baseId: null,
  moduleIds: [],
  confirmedDeps: [],
  hostingId: 'externo',
  maintenance: false,
  billingPlanId: null,
  paymentModeId: null,
  chatbotUsage: null,
  chatbotConversations: null,
};

/** Divide el total de desarrollo en el pago de arranque y el pago de entrega. */
export function splitPayments(total: number): { start: number; delivery: number } {
  const start = Math.round(total * paymentSplit.start);
  return { start, delivery: total - start };
}

const unique = <T>(xs: T[]): T[] => [...new Set(xs)];

const MAX_CUSTOM_CONVERSATIONS = 1_000_000;

/** El presupuesto incluye el chatbot, sea como módulo o porque la base es el chatbot. */
export function hasChatbot(state: Pick<QuoteState, 'baseId' | 'moduleIds'>): boolean {
  const base = state.baseId ? baseById(state.baseId) : undefined;
  return state.moduleIds.includes('chatbot') || !!base?.includes.includes('chatbot');
}

/** Reglas de la combinación; devuelve los problemas encontrados (vacío = válida). */
export function validateState(state: QuoteState): string[] {
  const errors: string[] = [];
  const base = state.baseId ? baseById(state.baseId) : undefined;
  if (state.baseId && !base) errors.push(`Base desconocida: ${state.baseId}`);
  if (!hostingById(state.hostingId)) errors.push(`Hosting desconocido: ${state.hostingId}`);
  if (new Set(state.moduleIds).size !== state.moduleIds.length) errors.push('Hay módulos duplicados.');
  for (const id of state.moduleIds) {
    const mod = moduleById(id);
    if (!mod) {
      errors.push(`Módulo desconocido: ${id}`);
      continue;
    }
    if (!base) errors.push(`Elige primero un tipo de proyecto antes de agregar "${mod.name}".`);
    else if (mod.incompatibleWith?.includes(base.id)) errors.push(`"${mod.name}" no aplica a ${base.name}.`);
    else if (base.includes.includes(id)) errors.push(`"${mod.name}" ya está incluido en ${base.name}.`);
  }
  for (const id of state.confirmedDeps) {
    if (!dependencies[id]) errors.push(`Dependencia desconocida: ${id}`);
  }
  if (state.billingPlanId) {
    if (!billingPlanById(state.billingPlanId)) errors.push(`Plan de facturación desconocido: ${state.billingPlanId}`);
    else if (!state.moduleIds.includes('facturacion')) errors.push('El plan de facturación requiere el módulo de facturación digital.');
  }
  if (state.paymentModeId && !paymentModeIds.includes(state.paymentModeId)) errors.push(`Modalidad de pago desconocida: ${state.paymentModeId}`);
  if (state.chatbotUsage && !usageTierIds.includes(state.chatbotUsage)) errors.push(`Volumen de uso desconocido: ${state.chatbotUsage}`);
  if (state.chatbotUsage && !hasChatbot(state)) errors.push('El volumen de uso requiere el chatbot con IA.');
  return errors;
}

/** Descarta lo inválido: ids desconocidos, duplicados, incompatibles o ya incluidos en la base. */
export function normalizeState(state: QuoteState): QuoteState {
  const base = state.baseId ? baseById(state.baseId) : undefined;
  const moduleIds = base
    ? unique(state.moduleIds).filter((id) => {
        const mod = moduleById(id);
        return !!mod && !mod.incompatibleWith?.includes(base.id) && !base.includes.includes(id);
      })
    : [];
  const needed = requiredDependencies(base?.id ?? null, moduleIds);
  const chatbot = hasChatbot({ baseId: base?.id ?? null, moduleIds });
  const usage = chatbot && state.chatbotUsage && usageTierIds.includes(state.chatbotUsage) ? state.chatbotUsage : null;
  const custom = usage === 'custom' && Number.isFinite(state.chatbotConversations) && (state.chatbotConversations ?? 0) > 0
    ? Math.min(Math.floor(state.chatbotConversations as number), MAX_CUSTOM_CONVERSATIONS)
    : null;
  return {
    baseId: base?.id ?? null,
    moduleIds,
    confirmedDeps: unique(state.confirmedDeps).filter((d) => !!dependencies[d] && needed.has(d)),
    hostingId: hostingById(state.hostingId)?.id ?? 'externo',
    maintenance: !!state.maintenance,
    billingPlanId: moduleIds.includes('facturacion') ? (billingPlanById(state.billingPlanId ?? '')?.id ?? null) : null,
    paymentModeId: paymentModeIds.includes(state.paymentModeId as PaymentModeId) ? state.paymentModeId : null,
    chatbotUsage: usage,
    chatbotConversations: custom,
  };
}

/** Dependencias que los módulos elegidos necesitan y que la base no incluye. */
function requiredDependencies(baseId: BaseId | null, moduleIds: ModuleId[]): Set<DependencyId> {
  const base = baseId ? baseById(baseId) : undefined;
  const result = new Set<DependencyId>();
  for (const id of moduleIds) {
    for (const dep of moduleById(id)?.requires ?? []) {
      if (!base?.includes.includes(dep)) result.add(dep);
    }
  }
  return result;
}

export function setBase(state: QuoteState, baseId: BaseId): QuoteState {
  if (!baseById(baseId)) return state;
  return normalizeState({ ...state, baseId });
}

export function getModuleStatus(state: QuoteState, id: ModuleId): ModuleStatus {
  const base = state.baseId ? baseById(state.baseId) : undefined;
  const mod = moduleById(id);
  if (!base || !mod) return 'unavailable';
  if (base.includes.includes(id)) return 'included';
  if (mod.incompatibleWith?.includes(base.id)) return 'unavailable';
  return state.moduleIds.includes(id) ? 'selected' : 'available';
}

export function toggleModule(state: QuoteState, id: ModuleId): QuoteState {
  const status = getModuleStatus(state, id);
  if (status === 'selected') return normalizeState({ ...state, moduleIds: state.moduleIds.filter((m) => m !== id) });
  if (status === 'available') return normalizeState({ ...state, moduleIds: [...state.moduleIds, id] });
  return state;
}

/** El usuario acepta incluir (y pagar) las dependencias que faltan. */
export function confirmDependencies(state: QuoteState): QuoteState {
  const needed = requiredDependencies(state.baseId, state.moduleIds);
  return normalizeState({ ...state, confirmedDeps: [...state.confirmedDeps, ...needed] });
}

export const setHosting = (state: QuoteState, hostingId: HostingId): QuoteState => normalizeState({ ...state, hostingId });
export const setMaintenance = (state: QuoteState, on: boolean): QuoteState => ({ ...state, maintenance: on });
export const setBillingPlan = (state: QuoteState, planId: BillingPlanId): QuoteState => normalizeState({ ...state, billingPlanId: planId });
export const setPaymentMode = (state: QuoteState, modeId: PaymentModeId | null): QuoteState => normalizeState({ ...state, paymentModeId: modeId });
export const setChatbotUsage = (state: QuoteState, usage: UsageTierId | null, conversations: number | null = null): QuoteState =>
  normalizeState({ ...state, chatbotUsage: usage, chatbotConversations: conversations });

/** Conversaciones mensuales a estimar según el volumen elegido (null si aún no eligió). */
export function usageConversations(state: QuoteState, config: CommercialConfig = defaultCommercialConfig): number | null {
  if (!state.chatbotUsage) return null;
  if (state.chatbotUsage === 'custom') return state.chatbotConversations;
  return config.chatbot.tiers.find((t) => t.id === state.chatbotUsage)?.conversations ?? null;
}

export function computeQuote(input: QuoteState, config: CommercialConfig = defaultCommercialConfig): Quote {
  const state = normalizeState(input);
  const base = state.baseId ? baseById(state.baseId) : undefined;
  const lines: QuoteLine[] = [];
  const notices: string[] = [];

  if (base) lines.push({ kind: 'base', id: base.id, label: base.name, price: base.price, from: !!base.from });

  const selected = state.moduleIds.map((id) => moduleById(id)!);
  for (const mod of selected) {
    lines.push({ kind: 'module', id: mod.id, label: mod.name, price: mod.price, from: !!mod.from });
    if (mod.notice) notices.push(`${mod.name}: ${mod.notice}`);
  }

  const needed = requiredDependencies(state.baseId, state.moduleIds);
  const pending: PendingDependency[] = [];
  for (const depId of needed) {
    const dependency = dependencies[depId];
    if (state.confirmedDeps.includes(depId)) {
      lines.push({ kind: 'dependency', id: depId, label: dependency.name, price: dependency.price, from: false });
    } else {
      const requiredBy = selected.filter((m) => m.requires.includes(depId)).map((m) => m.name);
      pending.push({ dependency, requiredBy });
    }
  }

  const hosting = hostingById(state.hostingId) ?? hostingOptions[0];
  const hostingMonthly = hosting.monthly;
  const maintenanceMonthly = state.maintenance ? maintenance.monthly : 0;
  const billingMonthly = billingPlanById(state.billingPlanId ?? '')?.monthly ?? 0;
  const missingBillingPlan = state.moduleIds.includes('facturacion') && !state.billingPlanId;
  const developmentTotal = lines.reduce((sum, l) => sum + l.price, 0);
  // El desarrollo nunca recibe un segundo descuento: las modalidades se calculan siempre desde el precio de catálogo.
  const devLines = lines.map((l) => ({ kind: l.kind, id: l.id, price: l.price, alsoIds: l.kind === 'base' && base?.sameAs ? [base.sameAs] : [] }));
  const paymentOptions = base ? computeAllPayments(devLines, config) : [];
  const payment = state.paymentModeId ? (paymentOptions.find((p) => p.modeId === state.paymentModeId) ?? null) : null;
  const chatbot = hasChatbot(state);
  const conversations = usageConversations(state, config);
  const usage = chatbot && conversations !== null ? estimateChatbotUsage(conversations, config.chatbot) : null;

  return {
    lines,
    included: base ? base.includes.map((id) => moduleById(id)?.name ?? dependencies[id as DependencyId]?.name).filter((n): n is string => !!n) : [],
    developmentTotal,
    payments: splitPayments(developmentTotal),
    hostingMonthly,
    billingMonthly,
    missingBillingPlan,
    maintenanceMonthly,
    monthlyTotal: hostingMonthly + billingMonthly + maintenanceMonthly,
    developmentFrom: lines.some((l) => l.from),
    monthlyFrom: (hostingMonthly > 0 && !!hosting.from) || state.maintenance,
    pending,
    notices,
    hostingNeedsEvaluation: !!hosting.needsEvaluation,
    complete: !!base && pending.length === 0 && !missingBillingPlan,
    payment,
    paymentOptions,
    hasChatbot: chatbot,
    usage,
  };
}

export function formatUSD(amount: number): string {
  const decimals = Number.isInteger(amount) ? 0 : 2;
  return `$${amount.toLocaleString('de-DE', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })} USD`;
}

/** Centavos → "$1.320 USD" (o "$1.320,50 USD" si hay centavos). */
export const formatCents = (cents: number): string => formatUSD(fromCents(cents));

/** Bloque de desarrollo y pagos del resumen, según la modalidad elegida. */
function paymentSummary(q: Quote, config: CommercialConfig, from: string): string[] {
  const out: string[] = [];
  const pay = q.payment;
  if (!pay) {
    out.push(`DESARROLLO (2 pagos): ${from}${formatUSD(q.developmentTotal)}`);
    out.push(`- Para arrancar el desarrollo: ${from}${formatUSD(q.payments.start)}`);
    out.push(`- Al culminar, con todo funcionando: ${from}${formatUSD(q.payments.delivery)}`);
    return out;
  }
  out.push(`MODALIDAD DE PAGO: ${pay.kind === 'cash' ? 'Contado' : `Financiamiento a ${pay.termMonths} meses`}`);
  out.push(`- Precio original del desarrollo: ${from}${formatCents(pay.originalCents)}`);
  if (pay.kind === 'cash') {
    if (pay.discountCents > 0) {
      out.push(`- Descuento de contado (${Number(pay.discountPercent)} %): -${formatCents(pay.discountCents)}`);
      out.push(`- Ahorro: ${formatCents(pay.savingsCents)}`);
    } else {
      out.push('- Descuento de contado: no aplica a esta cotización');
    }
    out.push(`TOTAL DE DESARROLLO DE CONTADO: ${from}${formatCents(pay.totalCents)}`);
    out.push('El descuento aplica solo al desarrollo; no incluye costos recurrentes ni servicios de terceros.');
    return out;
  }
  out.push(`- Incremento por financiamiento (${Number(pay.surchargePercent)} %): +${formatCents(pay.surchargeCents)}`);
  out.push(`TOTAL DE DESARROLLO FINANCIADO: ${from}${formatCents(pay.totalCents)} (sin descuento de contado)`);
  out.push(`- Inicial (${Number(pay.initialPercent)} %): ${formatCents(pay.initialCents)}`);
  out.push(`- ${cadenceText(pay.installmentCount, pay.everyMonths)} de ${formatCents(pay.installmentCents)}`);
  out.push('Calendario:');
  out.push(...pay.schedule.map((it) => `  ${it.label} (${it.due.toLowerCase().startsWith('mes') ? it.due.toLowerCase() : it.due}): ${formatCents(it.amountCents)}`));
  out.push(paymentCopy.approvalFine);
  return out;
}

/** Texto legible de la propuesta, usado para WhatsApp y para copiar. Solo contiene lo que el visitante configuró. */
export function buildSummary(input: QuoteState, config: CommercialConfig = defaultCommercialConfig, opts: { reference?: string } = {}): string {
  const state = normalizeState(input);
  const q = computeQuote(state, config);
  const base = state.baseId ? baseById(state.baseId) : undefined;
  const hosting = hostingById(state.hostingId);
  const out: string[] = ['Hola Angside, quiero solicitar esta propuesta:'];
  if (opts.reference) out.push(`Referencia: ${opts.reference}`);
  out.push('');
  out.push(`Tipo de proyecto: ${base?.name ?? 'Sin definir'}`);
  const rows = q.lines.map((l) => `- ${l.label}: ${l.from ? 'desde ' : ''}${formatUSD(l.price)}`);
  out.push('', 'Desglose de desarrollo (precio original):', ...(rows.length ? rows : ['- (sin elementos)']));
  if (q.included.length) out.push('', `Incluido en la base: ${q.included.join(', ')}`);
  if (q.pending.length) {
    out.push('', 'Requisitos por definir (no sumados):', ...q.pending.map((p) => `- ${p.dependency.name} (requerido por ${p.requiredBy.join(', ')})`));
  }
  const from = q.developmentFrom ? 'desde ' : '';
  out.push('', ...paymentSummary(q, config, from));
  out.push('', 'Costos mensuales recurrentes (sin descuento):');
  out.push(`- Hosting (${hosting?.name ?? 'Hosting externo'}): ${formatUSD(q.hostingMonthly)}/mes`);
  const plan = billingPlanById(state.billingPlanId ?? '');
  if (plan) out.push(`- Facturación digital, plan ${plan.name} (costo fijo): ${formatUSD(plan.monthly)}/mes`);
  if (state.maintenance) out.push(`- ${maintenance.name}: ${formatUSD(q.maintenanceMonthly)}/mes`);
  out.push(`MENSUAL: ${q.monthlyFrom ? 'desde ' : ''}${formatUSD(q.monthlyTotal)}/mes`);
  if (q.hasChatbot) {
    if (q.usage) {
      const label = q.usage.underOneCent ? 'menos de $0,01 USD' : formatCents(q.usage.monthlyCents);
      out.push('', `Consumo de IA del chatbot (aparte, variable, no incluido en el total mensual): ~${label}/mes para ${q.usage.conversations.toLocaleString('de-DE')} conversaciones mensuales.`);
    } else {
      out.push('', 'Consumo de IA del chatbot (aparte, variable según uso): por estimar.');
    }
    out.push('Es una estimación orientativa, no una garantía ni un compromiso; no incluye hosting, soporte ni integraciones adicionales.');
  }
  if (q.hostingNeedsEvaluation) out.push('', 'Nota: el servidor Xeon compartido está sujeto a disponibilidad y evaluación.');
  if (q.notices.length) out.push('', 'Observaciones:', ...q.notices.map((n) => `- ${n}`));
  if (q.missingBillingPlan) out.push('', 'Pendiente: elegir el plan de facturación para la facturación digital.');
  return out.join('\n');
}

/** Serializa la configuración para compartirla en una URL (?b=..&m=..). */
export function encodeState(input: QuoteState): string {
  const state = normalizeState(input);
  const p = new URLSearchParams();
  if (state.baseId) p.set('b', state.baseId);
  if (state.moduleIds.length) p.set('m', state.moduleIds.join(','));
  if (state.confirmedDeps.length) p.set('d', state.confirmedDeps.join(','));
  if (state.hostingId !== 'externo') p.set('h', state.hostingId);
  if (state.maintenance) p.set('k', '1');
  if (state.billingPlanId) p.set('c', state.billingPlanId);
  if (state.paymentModeId) p.set('p', state.paymentModeId);
  if (state.chatbotUsage) p.set('u', state.chatbotUsage);
  if (state.chatbotConversations) p.set('n', String(state.chatbotConversations));
  return p.toString();
}

/** Lee una configuración de la URL; cualquier valor desconocido se ignora. */
export function decodeState(search: string): QuoteState {
  const p = new URLSearchParams(search);
  const list = (key: string) => (p.get(key) ?? '').split(',').filter(Boolean);
  const baseId = bases.find((b) => b.id === p.get('b'))?.id ?? null;
  return normalizeState({
    baseId,
    moduleIds: list('m').filter((id): id is ModuleId => modules.some((m) => m.id === id)),
    confirmedDeps: list('d').filter((id): id is DependencyId => id in dependencies),
    hostingId: (hostingOptions.find((h) => h.id === p.get('h'))?.id ?? 'externo') as HostingId,
    maintenance: p.get('k') === '1',
    billingPlanId: billingPlans.find((b) => b.id === p.get('c'))?.id ?? null,
    paymentModeId: paymentModeIds.find((id) => id === p.get('p')) ?? null,
    chatbotUsage: usageTierIds.find((id) => id === p.get('u')) ?? null,
    chatbotConversations: /^\d{1,7}$/.test(p.get('n') ?? '') ? Number(p.get('n')) : null,
  });
}

