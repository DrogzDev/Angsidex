/**
 * Genera el contrato que consume el backend (Django):
 *  - backend/angside_ai/data/pricing.json  → precios y reglas (fuente única: src/data/pricing.ts)
 *  - backend/tests/fixtures/quote_cases.json → casos calculados por quote-engine.ts, que el motor Python debe reproducir.
 * Ejecutar con: npm run export:contract
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import * as pricing from '../src/data/pricing';
import { defaultCommercialConfig } from '../src/data/commercial';
import {
  computeQuote,
  confirmDependencies,
  decodeState,
  encodeState,
  initialState,
  setBase,
  setBillingPlan,
  setChatbotUsage,
  setHosting,
  setPaymentMode,
  setMaintenance,
  toggleModule,
  type QuoteState,
} from '../src/lib/quote-engine';

const out = (rel: string, data: unknown) => {
  const path = resolve(__dirname, '..', 'backend', rel);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(data, null, 2) + '\n', 'utf-8');
};

/** Proyección compacta de una modalidad: lo necesario para comprobar importes y calendario. */
const pay = (p: ReturnType<typeof computeQuote>['payment']) =>
  p && {
    modeId: p.modeId,
    available: p.available,
    originalCents: p.originalCents,
    discountCents: p.discountCents,
    surchargeCents: p.surchargeCents,
    totalCents: p.totalCents,
    initialCents: p.initialCents,
    installmentCents: p.installmentCents,
    schedule: p.schedule.map((s) => s.amountCents),
  };

const snapshot = (state: QuoteState) => {
  const q = computeQuote(state);
  return {
    query: encodeState(state),
    expected: {
      developmentTotal: q.developmentTotal,
      payments: q.payments,
      hostingMonthly: q.hostingMonthly,
      billingMonthly: q.billingMonthly,
      maintenanceMonthly: q.maintenanceMonthly,
      monthlyTotal: q.monthlyTotal,
      developmentFrom: q.developmentFrom,
      monthlyFrom: q.monthlyFrom,
      complete: q.complete,
      missingBillingPlan: q.missingBillingPlan,
      pending: q.pending.map((p) => p.dependency.id),
      lines: q.lines.map((l) => `${l.kind}:${l.id}:${l.price}`),
      paymentOptions: q.paymentOptions.map(pay),
      payment: pay(q.payment),
      hasChatbot: q.hasChatbot,
      usage: q.usage,
    },
  };
};

describe('contrato para el backend', () => {
  it('exporta precios y casos', () => {
    out('angside_ai/data/pricing.json', {
      bases: pricing.bases,
      dependencies: pricing.dependencies,
      categories: pricing.categories,
      modules: pricing.modules,
      hostingOptions: pricing.hostingOptions,
      maintenance: pricing.maintenance,
      billingPlans: pricing.billingPlans,
      billingRange: pricing.billingRange,
      paymentSplit: pricing.paymentSplit,
      billingService: pricing.billingService,
      costNotes: pricing.costNotes,
      projectTerms: pricing.projectTerms,
      // Valores iniciales de la configuración comercial (Django Admin los puede cambiar después).
      commercialDefaults: { ...defaultCommercialConfig, version: undefined },
    });

    const cases = [] as ReturnType<typeof snapshot>[];
    const seen = new Set<string>();
    const add = (s: QuoteState) => {
      const c = snapshot(s);
      if (!seen.has(c.query)) {
        seen.add(c.query);
        cases.push(c);
      }
    };

    for (const base of pricing.bases) {
      const b = setBase(initialState, base.id);
      add(b);
      add(setMaintenance(setHosting(b, 'vps-superior'), true));
      add(setHosting(b, 'xeon'));
      let acc = b;
      for (const mod of pricing.modules) {
        const one = toggleModule(b, mod.id);
        add(one);
        add(confirmDependencies(one));
        acc = toggleModule(acc, mod.id);
        add(acc);
        add(confirmDependencies(acc));
        if (mod.id === 'facturacion') {
          for (const plan of pricing.billingPlans) add(setBillingPlan(confirmDependencies(one), plan.id));
        }
      }
      for (const plan of pricing.billingPlans) {
        add(setMaintenance(setHosting(setBillingPlan(confirmDependencies(toggleModule(b, 'facturacion')), plan.id), 'vps-basico'), true));
      }
    }
    // Modalidades de pago y consumo de IA sobre una muestra de cotizaciones.
    const sample = [...cases].filter((_, i) => i % 5 === 0).map((c) => decodeState(c.query));
    const chatbotOnly = setBase(initialState, 'chatbot-ia');
    const withChatbot = toggleModule(setBase(initialState, 'corporativa'), 'chatbot');
    for (const state of [...sample, chatbotOnly, withChatbot]) {
      for (const mode of ['cash', 'm3', 'm6', 'm9'] as const) add(setPaymentMode(state, mode));
    }
    for (const state of [chatbotOnly, withChatbot]) {
      for (const [tier, n] of [['low', null], ['medium', null], ['high', null], ['custom', 12345], ['custom', 1]] as const) {
        for (const mode of ['cash', 'm9'] as const) add(setPaymentMode(setChatbotUsage(state, tier, n), mode));
      }
    }
    // Entradas hostiles: el motor debe normalizarlas igual en ambos lados.
    for (const q of ['b=hack', 'b=landing&m=inventario,bcv,zzz', 'b=sistema&m=panel,roles&c=gold', 'm=bcv', 'b=tienda&d=auth,foo&h=nada&c=pymes', 'b=landing&p=m3', 'b=landing&p=zzz&u=high', 'b=chatbot-ia&u=custom&n=99999999', 'b=chatbot-ia&u=custom&n=-5&p=cash']) add(decodeState(q));

    out('tests/fixtures/quote_cases.json', cases);
    expect(cases.length).toBeGreaterThan(50);
  });
});
