import { describe, expect, it } from 'vitest';
import { defaultCommercialConfig, type CommercialConfig } from '../src/data/commercial';
import { cadenceText, computeAllPayments, computePayment, estimateChatbotUsage, percentOf, toScaled, type DevLine } from '../src/lib/payment-plans';
import { isCommercialConfig } from '../src/lib/commercial-config';
import {
  buildSummary,
  computeQuote,
  confirmDependencies,
  decodeState,
  encodeState,
  initialState,
  setBase,
  setChatbotUsage,
  setHosting,
  setMaintenance,
  setPaymentMode,
  toggleModule,
  validateState,
} from '../src/lib/quote-engine';

const cfg = defaultCommercialConfig;
const withCfg = (patch: (c: CommercialConfig) => void): CommercialConfig => {
  const c = structuredClone(cfg);
  patch(c);
  return c;
};
const line = (id: string, price: number, kind: DevLine['kind'] = 'module'): DevLine => ({ kind, id, price });
// Un desarrollo de $1.200 como en el enunciado comercial.
const dev1200: DevLine[] = [line('sistema', 650, 'base'), line('crm', 180), line('panel', 180), line('bcv', 90), line('reportes', 100)];

describe('aritmética decimal', () => {
  it('interpreta porcentajes con 6 decimales sin flotantes', () => {
    expect(toScaled('20.833333', 6)).toBe(20833333n);
    expect(toScaled('50', 6)).toBe(50_000_000n);
    expect(percentOf(120000, '20.833333')).toBe(25000); // $1.200 × 20,833333 % = $250 (redondeado a centavos)
  });
  it('redondea mitad hacia arriba a centavos', () => {
    expect(percentOf(1005, '50')).toBe(503); // 502,5 → 503
    expect(percentOf(1001, '50')).toBe(501); // 500,5 → 501
    expect(percentOf(1, '10')).toBe(0);
  });
});

describe('pago de contado (opción A)', () => {
  const total = dev1200.reduce((s, l) => s + l.price, 0);
  it('el desarrollo de ejemplo suma $1.200', () => expect(total).toBe(1200));

  it('descuenta exactamente el 23 % y muestra original, descuento, ahorro y total', () => {
    const p = computePayment(dev1200, 'cash', cfg);
    expect(p.originalCents).toBe(120000);
    expect(p.discountCents).toBe(27600);
    expect(p.savingsCents).toBe(27600);
    expect(p.totalCents).toBe(92400);
    expect(p.schedule).toEqual([{ label: 'Pago único', due: 'Al confirmar el proyecto', amountCents: 92400 }]);
  });

  it('se puede desactivar desde la configuración', () => {
    const p = computePayment(dev1200, 'cash', withCfg((c) => { c.cashDiscount.enabled = false; }));
    expect(p.discountCents).toBe(0);
    expect(p.totalCents).toBe(120000);
  });

  it('el porcentaje es configurable', () => {
    const p = computePayment(dev1200, 'cash', withCfg((c) => { c.cashDiscount.percent = '35.5'; }));
    expect(p.discountCents).toBe(42600);
  });

  it('respeta el desarrollo mínimo para el descuento', () => {
    const p = computePayment([line('crm', 180)], 'cash', withCfg((c) => { c.cashDiscount.minDevelopmentUsd = '200'; }));
    expect(p.discountCents).toBe(0);
    expect(p.unavailableReason).toMatch(/\$200/);
  });
});

describe('financiamiento (opciones B, C y D)', () => {
  it('3 meses: +10 %, inicial 40 % y tres cuotas mensuales', () => {
    const p = computePayment(dev1200, 'm3', cfg);
    expect(p.surchargeCents).toBe(12000);
    expect(p.totalCents).toBe(132000);
    expect(p.initialCents).toBe(52800);
    expect(p.installmentCount).toBe(3);
    expect(p.installmentCents).toBe(26400);
    expect(p.schedule.map((s) => s.amountCents)).toEqual([52800, 26400, 26400, 26400]);
    expect(p.schedule.map((s) => s.due)).toEqual(['Al aprobar el plan y firmar el contrato', 'Mes 1', 'Mes 2', 'Mes 3']);
  });

  it('6 meses: +15 %, inicial $552 y seis cuotas de $138', () => {
    const p = computePayment(dev1200, 'm6', cfg);
    expect(p.totalCents).toBe(138000);
    expect(p.initialCents).toBe(55200);
    expect(p.installmentCents).toBe(13800);
    expect(p.schedule).toHaveLength(7);
  });

  it('9 meses: +20,833333 % → $1.450, inicial $580 y tres cuotas trimestrales de $290', () => {
    const p = computePayment(dev1200, 'm9', cfg);
    expect(p.totalCents).toBe(145000);
    expect(p.initialCents).toBe(58000);
    expect(p.installmentCents).toBe(29000);
    expect(p.schedule.map((s) => s.due).slice(1)).toEqual(['Mes 3', 'Mes 6', 'Mes 9']);
    expect(cadenceText(p.installmentCount, p.everyMonths)).toBe('3 cuotas trimestrales');
  });

  it('los planes financiados nunca reciben el descuento de contado', () => {
    for (const id of ['m3', 'm6', 'm9'] as const) {
      const p = computePayment(dev1200, id, cfg);
      expect(p.discountCents).toBe(0);
      expect(p.discountPercent).toBe('0');
      expect(p.totalCents).toBeGreaterThan(p.originalCents);
      expect(p.requiresApproval).toBe(true);
    }
  });

  it('el importe financiado es el total del plan, no el precio descontado', () => {
    const cash = computePayment(dev1200, 'cash', cfg);
    const m3 = computePayment(dev1200, 'm3', cfg);
    expect(m3.initialCents + m3.installmentCents * 3).toBe(m3.totalCents);
    expect(m3.totalCents).not.toBe(Math.round(cash.totalCents * 1.1));
  });

  it('el último pago absorbe la diferencia de centavos', () => {
    // $100,01 × 1,10 = $110,011 → $110,01; inicial 40 % = $44,00; resto $66,01 en 3 cuotas
    const c = withCfg((x) => { x.plans[0].surchargePercent = '10'; });
    const p = computePayment([line('x', 100.01)], 'm3', c);
    expect(p.totalCents).toBe(11001);
    const sum = p.schedule.reduce((s, it) => s + it.amountCents, 0);
    expect(sum).toBe(p.totalCents); // nunca sobra ni falta un centavo
    const cuotas = p.schedule.slice(1).map((s) => s.amountCents);
    expect(cuotas[0]).toBe(cuotas[1]);
    expect(cuotas[2]).not.toBeLessThan(0);
    expect(Math.abs(cuotas[2] - cuotas[0])).toBeLessThanOrEqual(2);
  });

  it('para cualquier total, inicial + cuotas == total del plan', () => {
    for (let price = 1; price < 400; price += 7) {
      for (const id of ['m3', 'm6', 'm9'] as const) {
        const p = computePayment([line('x', price + 0.37)], id, cfg);
        expect(p.schedule.reduce((s, it) => s + it.amountCents, 0)).toBe(p.totalCents);
      }
    }
  });

  it('porcentajes, cuotas y periodicidad vienen de la configuración', () => {
    const p = computePayment(dev1200, 'm3', withCfg((c) => { Object.assign(c.plans[0], { surchargePercent: '12', initialPercent: '25', installments: 4, everyMonths: 2 }); }));
    expect(p.totalCents).toBe(134400);
    expect(p.initialCents).toBe(33600);
    expect(p.installmentCents).toBe(25200);
    expect(p.schedule.map((s) => s.due).slice(1)).toEqual(['Mes 2', 'Mes 4', 'Mes 6', 'Mes 8']);
  });

  it('un plan desactivado o por debajo del mínimo comercial no está disponible', () => {
    expect(computePayment(dev1200, 'm6', withCfg((c) => { c.plans[1].enabled = false; })).available).toBe(false);
    const small = computePayment([line('chatbot', 100)], 'm3', withCfg((c) => { c.financingMinDevelopmentUsd = '150'; }));
    expect(small.available).toBe(false);
    expect(small.unavailableReason).toMatch(/\$150/);
  });
});

describe('no acumulación y exclusiones', () => {
  it('calcular varias veces da el mismo resultado: el descuento no se acumula', () => {
    const first = computePayment(dev1200, 'cash', cfg);
    const again = computePayment(dev1200, 'cash', cfg);
    expect(again).toEqual(first);
    expect(computeAllPayments(dev1200, cfg).find((p) => p.modeId === 'cash')).toEqual(first);
  });

  it('un módulo excluido del descuento conserva su precio completo', () => {
    const c = withCfg((x) => { x.cashDiscount.excludedIds = ['crm']; });
    const p = computePayment(dev1200, 'cash', c);
    expect(p.discountableCents).toBe(102000);
    expect(p.discountCents).toBe(23460);
    expect(p.totalCents).toBe(120000 - 23460);
    // El financiamiento sigue calculándose sobre el desarrollo completo
    expect(computePayment(dev1200, 'm3', c).totalCents).toBe(132000);
  });

  it('si todo está excluido no hay descuento', () => {
    const c = withCfg((x) => { x.cashDiscount.excludedIds = dev1200.map((l) => l.id); });
    expect(computePayment(dev1200, 'cash', c).discountCents).toBe(0);
  });
});

describe('integración con el cotizador', () => {
  const sistema = () => toggleModule(toggleModule(setBase(initialState, 'sistema'), 'bcv'), 'reportes');

  it('la modalidad no cambia el desarrollo de catálogo ni los costos recurrentes', () => {
    const base = setMaintenance(setHosting(confirmDependencies(sistema()), 'vps-superior'), true);
    const plain = computeQuote(base);
    for (const mode of ['cash', 'm3', 'm6', 'm9'] as const) {
      const q = computeQuote(setPaymentMode(base, mode));
      expect(q.developmentTotal).toBe(plain.developmentTotal);
      expect(q.hostingMonthly).toBe(plain.hostingMonthly);
      expect(q.maintenanceMonthly).toBe(plain.maintenanceMonthly);
      expect(q.monthlyTotal).toBe(plain.monthlyTotal); // sin descuento ni incremento sobre lo recurrente
    }
  });

  it('el descuento solo toca el desarrollo: la base de cálculo excluye hosting y mantenimiento', () => {
    const q = computeQuote(setPaymentMode(setMaintenance(setHosting(sistema(), 'xeon'), true), 'cash'));
    expect(q.payment!.originalCents).toBe(q.developmentTotal * 100);
    expect(q.payment!.discountCents).toBe(q.developmentTotal * 23);
  });

  it('sin modalidad elegida se conserva el pago estándar en dos partes', () => {
    const q = computeQuote(sistema());
    expect(q.payment).toBeNull();
    expect(q.payments.start + q.payments.delivery).toBe(q.developmentTotal);
    expect(q.paymentOptions).toHaveLength(4);
  });

  it('la modalidad viaja en el enlace compartido y se valida', () => {
    const s = setPaymentMode(sistema(), 'm9');
    expect(decodeState(encodeState(s)).paymentModeId).toBe('m9');
    expect(decodeState('b=landing&p=hack').paymentModeId).toBeNull();
    expect(validateState({ ...initialState, paymentModeId: 'nope' as never }).length).toBeGreaterThan(0);
  });
});

describe('chatbot empresarial', () => {
  const only = () => setBase(initialState, 'chatbot-ia');

  it('el chatbot solo cuesta desde $100 y de contado queda en $77', () => {
    const q = computeQuote(setPaymentMode(only(), 'cash'));
    expect(q.developmentTotal).toBe(100);
    expect(q.developmentFrom).toBe(true);
    expect(q.payment!.totalCents).toBe(7700);
    expect(q.hasChatbot).toBe(true);
  });

  it('financiado usa el precio base de $100 más el incremento, sin descuento', () => {
    const q = computeQuote(setPaymentMode(only(), 'm3'));
    expect(q.payment!.originalCents).toBe(10000);
    expect(q.payment!.totalCents).toBe(11000);
    expect(q.payment!.discountCents).toBe(0);
  });

  it('como módulo se suma a otro proyecto; en la base del chatbot ya viene incluido', () => {
    const landing = toggleModule(setBase(initialState, 'landing'), 'chatbot');
    expect(computeQuote(landing).developmentTotal).toBe(280);
    expect(toggleModule(only(), 'chatbot').moduleIds).toEqual([]); // incluido: no se cobra dos veces
  });

  it('el consumo de IA no entra en el desarrollo ni en el total mensual', () => {
    const q = computeQuote(setChatbotUsage(setPaymentMode(only(), 'cash'), 'high'));
    expect(q.usage!.monthlyCents).toBeGreaterThan(0);
    expect(q.developmentTotal).toBe(100);
    expect(q.monthlyTotal).toBe(0);
    expect(q.payment!.totalCents).toBe(7700);
  });

  it('el volumen de uso solo aplica si hay chatbot', () => {
    expect(setChatbotUsage(setBase(initialState, 'landing'), 'low').chatbotUsage).toBeNull();
  });
});

describe('estimación de consumo de IA', () => {
  const ch = cfg.chatbot;
  it('depende de los tokens, no solo de las conversaciones', () => {
    const base = estimateChatbotUsage(500, ch);
    const long = estimateChatbotUsage(500, { ...ch, inputTokensPerQuery: ch.inputTokensPerQuery * 4 });
    expect(long.monthlyCents).toBeGreaterThan(base.monthlyCents);
  });
  it('calcula los tres niveles orientativos con las tarifas de respaldo', () => {
    // por consulta: 1.500 × $0,15/M + 250 × $0,50/M = $0,00035; × 4 consultas por conversación = $0,0014
    expect(estimateChatbotUsage(100, ch).monthlyCents).toBe(14);
    expect(estimateChatbotUsage(500, ch).monthlyCents).toBe(70);
    expect(estimateChatbotUsage(2000, ch).monthlyCents).toBe(280);
  });
  it('las tarifas son configurables (no están fijas en el frontend)', () => {
    const e = estimateChatbotUsage(500, { ...ch, priceInPerM: '0.30', priceOutPerM: '1.00' });
    expect(e.monthlyCents).toBe(140);
  });
  it('aplica el margen de administración y avisa si supera el límite', () => {
    const e = estimateChatbotUsage(2000, { ...ch, marginPercent: '25', monthlyLimitUsd: '3' });
    expect(e.monthlyCents).toBe(350);
    expect(e.overLimit).toBe(true);
  });
  it('cero conversaciones cuesta cero y una sola cuesta menos de un centavo', () => {
    expect(estimateChatbotUsage(0, ch).monthlyCents).toBe(0);
    const one = estimateChatbotUsage(1, ch);
    expect(one.monthlyCents).toBe(0);
    expect(one.underOneCent).toBe(true);
  });
  it('el uso personalizado y el URL viajan en el estado', () => {
    const s = setChatbotUsage(setBase(initialState, 'chatbot-ia'), 'custom', 12345);
    expect(decodeState(encodeState(s))).toEqual(s);
    expect(computeQuote(s).usage!.conversations).toBe(12345);
  });
});

describe('resumen para WhatsApp', () => {
  const quote = () => setPaymentMode(setChatbotUsage(toggleModule(setBase(initialState, 'corporativa'), 'chatbot'), 'medium'), 'm9');

  it('incluye proyecto, funcionalidades, precio original, modalidad, incremento, total, inicial y calendario', () => {
    const text = buildSummary(quote(), cfg, { reference: 'ANG-TEST1234' });
    for (const needle of [
      'Tipo de proyecto: Web corporativa', 'Chatbot empresarial con inteligencia artificial', 'Precio original del desarrollo',
      'Financiamiento a 9 meses', 'Incremento por financiamiento (20.833333 %)', 'TOTAL DE DESARROLLO FINANCIADO',
      'Inicial (40 %)', '3 cuotas trimestrales', 'Calendario:', 'Mes 9', 'Referencia: ANG-TEST1234',
      'Hosting', 'Consumo de IA del chatbot', 'sujeto a aprobación manual',
    ]) expect(text.toLowerCase()).toContain(needle.toLowerCase());
  });

  it('el consumo de IA aparece separado del total mensual y como estimación no garantizada', () => {
    const text = buildSummary(quote(), cfg);
    expect(text).toMatch(/no incluido en el total mensual/);
    expect(text).toMatch(/estimación orientativa, no una garantía/);
  });

  it('contado muestra descuento y ahorro; el financiado no menciona descuento de contado aplicado', () => {
    const cash = buildSummary(setPaymentMode(quote(), 'cash'), cfg);
    expect(cash).toMatch(/Descuento de contado \(23 %\): -\$/);
    expect(cash).toMatch(/Ahorro: \$/);
    expect(buildSummary(quote(), cfg)).not.toMatch(/Descuento de contado \(/);
  });

  it('solo contiene lo configurado: no agrega datos personales', () => {
    const text = buildSummary(quote(), cfg, { reference: 'ANG-TEST1234' });
    expect(text).not.toMatch(/@|\+?\d{9,}|nombre|tel[eé]fono|correo/i);
  });

  it('sin modalidad elegida conserva el formato anterior en dos pagos', () => {
    const text = buildSummary(setBase(initialState, 'landing'));
    expect(text).toContain('DESARROLLO (2 pagos)');
  });
});

describe('configuración descargada', () => {
  it('acepta la configuración por defecto', () => expect(isCommercialConfig(cfg)).toBe(true));
  it('rechaza respuestas corruptas en vez de mostrar importes erróneos', () => {
    expect(isCommercialConfig(null)).toBe(false);
    expect(isCommercialConfig({})).toBe(false);
    expect(isCommercialConfig(withCfg((c) => { c.cashDiscount.percent = 'abc'; }))).toBe(false);
    expect(isCommercialConfig(withCfg((c) => { c.plans[0].installments = 0; }))).toBe(false);
    expect(isCommercialConfig(withCfg((c) => { (c.plans[0] as { id: string }).id = 'm99'; }))).toBe(false);
  });
});
