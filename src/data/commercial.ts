/**
 * Condiciones comerciales por defecto: modalidades de pago, descuento de contado y estimación de consumo de IA.
 *
 * La fuente de verdad en producción es Django Admin (`/api/commercial/config`); el cotizador la descarga al cargar.
 * Estos valores solo cumplen dos funciones: sembrar la base de datos la primera vez (vía el contrato exportado) y servir
 * de respaldo si la API no responde. Los porcentajes son texto decimal para que el cálculo sea exacto (sin flotantes).
 */

export type PaymentModeId = 'cash' | 'm3' | 'm6' | 'm9';
export type FinancingModeId = Exclude<PaymentModeId, 'cash'>;
export type UsageTierId = 'low' | 'medium' | 'high' | 'custom';

export const paymentModeIds: readonly PaymentModeId[] = ['cash', 'm3', 'm6', 'm9'];
export const usageTierIds: readonly UsageTierId[] = ['low', 'medium', 'high', 'custom'];

export interface CashDiscountConfig {
  enabled: boolean;
  /** Porcentaje de descuento sobre el desarrollo elegible, p. ej. "23". */
  percent: string;
  /** El descuento solo aplica si el desarrollo suma al menos este monto (0 = sin mínimo). */
  minDevelopmentUsd: string;
  /** Ids de base o módulo cuyo precio no recibe descuento. */
  excludedIds: string[];
}

export interface FinancingPlanConfig {
  id: FinancingModeId;
  enabled: boolean;
  /** Duración total mostrada al cliente. */
  termMonths: number;
  /** Incremento sobre el precio base del desarrollo, p. ej. "20.833333". */
  surchargePercent: string;
  /** Inicial como porcentaje del total de la modalidad. */
  initialPercent: string;
  installments: number;
  /** Cada cuántos meses vence una cuota (1 = mensual, 3 = trimestral). */
  everyMonths: number;
}

export interface UsageTierConfig {
  id: UsageTierId;
  label: string;
  /** Conversaciones mensuales orientativas (en "custom" es el valor inicial sugerido). */
  conversations: number;
}

export interface ChatbotAiConfig {
  model: string;
  /** USD por millón de tokens de entrada / salida (vigentes: las del proveedor; si no, las de respaldo). */
  priceInPerM: string;
  priceOutPerM: string;
  ratesSource: 'openrouter' | 'fallback';
  ratesUpdatedAt: string | null;
  queriesPerConversation: number;
  inputTokensPerQuery: number;
  outputTokensPerQuery: number;
  /** Margen de administración sobre el consumo (0 = sin margen). */
  marginPercent: string;
  /** Tope mensual de consumo que se informa al cliente (null = sin tope definido). */
  monthlyLimitUsd: string | null;
  tiers: UsageTierConfig[];
  customMaxConversations: number;
}

export interface CommercialConfig {
  /** Versión de precios: se guarda con cada cotización para que las históricas no cambien en silencio. */
  version: number;
  cashDiscount: CashDiscountConfig;
  /** Desarrollo mínimo para ofrecer financiamiento (0 = sin mínimo). Sujeto a aprobación comercial. */
  financingMinDevelopmentUsd: string;
  plans: FinancingPlanConfig[];
  chatbot: ChatbotAiConfig;
}

export const defaultCommercialConfig: CommercialConfig = {
  version: 0,
  cashDiscount: { enabled: true, percent: '23', minDevelopmentUsd: '0', excludedIds: [] },
  financingMinDevelopmentUsd: '0',
  plans: [
    { id: 'm3', enabled: true, termMonths: 3, surchargePercent: '10', initialPercent: '40', installments: 3, everyMonths: 1 },
    { id: 'm6', enabled: true, termMonths: 6, surchargePercent: '15', initialPercent: '40', installments: 6, everyMonths: 1 },
    { id: 'm9', enabled: true, termMonths: 9, surchargePercent: '20.833333', initialPercent: '40', installments: 3, everyMonths: 3 },
  ],
  chatbot: {
    model: 'z-ai/glm-5.3-flash-20260826',
    priceInPerM: '0.15',
    priceOutPerM: '0.50',
    ratesSource: 'fallback',
    ratesUpdatedAt: null,
    queriesPerConversation: 4,
    inputTokensPerQuery: 1500,
    outputTokensPerQuery: 250,
    marginPercent: '0',
    monthlyLimitUsd: null,
    tiers: [
      { id: 'low', label: 'Uso bajo', conversations: 100 },
      { id: 'medium', label: 'Uso medio', conversations: 500 },
      { id: 'high', label: 'Uso alto', conversations: 2000 },
      { id: 'custom', label: 'Personalizado', conversations: 1000 },
    ],
    customMaxConversations: 100000,
  },
};

/** Textos comerciales fijos (no son parámetros: no cambian con la configuración). */
export const paymentCopy = {
  /** `pct` ya formateado, p. ej. "23". */
  cashNote: (pct: string) => `${pct} % de descuento sobre el desarrollo. No incluye costos recurrentes ni servicios de terceros.`,
  financingNote: 'Los planes de pago están sujetos a evaluación y aprobación por Angside.',
  approvalFine: 'Sujeto a aprobación manual de Angside, evaluación del proyecto y contrato. No se cobra ni se aprueba nada automáticamente.',
  usageDisclaimer:
    'Para negocios pequeños con un volumen moderado de consultas, el consumo del modelo puede ser inferior a $2 USD mensuales. El costo real depende de la cantidad de solicitudes, longitud de las conversaciones y modelo utilizado.',
  usageNotGuarantee: 'Es una estimación orientativa, no una garantía ni una obligación contractual.',
} as const;
