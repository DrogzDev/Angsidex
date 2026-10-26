import { describe, expect, it } from 'vitest';
import {
  buildSummary,
  computeQuote,
  confirmDependencies,
  decodeState,
  encodeState,
  initialState,
  setBase,
  setBillingPlan,
  setHosting,
  setMaintenance,
  splitPayments,
  toggleModule,
  validateState,
} from '../src/lib/quote-engine';
import { buildWhatsAppUrl } from '../src/lib/whatsapp';

const withBase = (id: Parameters<typeof setBase>[1]) => setBase(initialState, id);

describe('base', () => {
  it('sin base el total es 0 y no está completo', () => {
    const q = computeQuote(initialState);
    expect(q.developmentTotal).toBe(0);
    expect(q.complete).toBe(false);
  });
  it('calcula el precio de la base', () => {
    expect(computeQuote(withBase('landing')).developmentTotal).toBe(180);
    expect(computeQuote(withBase('tienda')).developmentTotal).toBe(550);
  });
  it('solo permite una base: cambiarla reemplaza la anterior', () => {
    const s = setBase(withBase('landing'), 'sistema');
    expect(s.baseId).toBe('sistema');
    expect(computeQuote(s).developmentTotal).toBe(650);
  });
});

describe('módulos', () => {
  it('suma módulos a la base', () => {
    const s = toggleModule(toggleModule(withBase('corporativa'), 'whatsapp'), 'bcv');
    expect(computeQuote(s).developmentTotal).toBe(350 + 150 + 90);
  });
  it('quita un módulo al alternarlo de nuevo', () => {
    const on = toggleModule(withBase('corporativa'), 'bcv');
    expect(computeQuote(toggleModule(on, 'bcv')).developmentTotal).toBe(350);
  });
  it('no duplica lo ya incluido en la base', () => {
    const s = toggleModule(withBase('sistema'), 'panel');
    expect(s.moduleIds).toEqual([]);
    expect(computeQuote(s).developmentTotal).toBe(650);
  });
  it('rechaza módulos incompatibles con la base', () => {
    expect(toggleModule(withBase('landing'), 'inventario').moduleIds).toEqual([]);
  });
  it('rechaza módulos sin base', () => {
    expect(toggleModule(initialState, 'bcv').moduleIds).toEqual([]);
  });
  it('al cambiar de base descarta módulos que ya no aplican', () => {
    const s = setBase(toggleModule(withBase('tienda'), 'inventario'), 'landing');
    expect(s.moduleIds).toEqual([]);
  });
});

describe('dependencias', () => {
  it('no suma dependencias ocultas: quedan pendientes hasta confirmar', () => {
    const s = toggleModule(withBase('corporativa'), 'crm');
    const q = computeQuote(s);
    expect(q.developmentTotal).toBe(350 + 180);
    expect(q.pending.map((p) => p.dependency.id)).toEqual(['data']);
    expect(q.complete).toBe(false);
  });
  it('al confirmar se suman explícitamente y la propuesta queda completa', () => {
    const q = computeQuote(confirmDependencies(toggleModule(withBase('corporativa'), 'crm')));
    expect(q.developmentTotal).toBe(350 + 180 + 100);
    expect(q.lines.some((l) => l.kind === 'dependency' && l.id === 'data')).toBe(true);
    expect(q.complete).toBe(true);
  });
  it('la base puede cubrir la dependencia', () => {
    const q = computeQuote(toggleModule(withBase('sistema'), 'roles'));
    expect(q.pending).toEqual([]);
    expect(q.developmentTotal).toBe(650 + 150);
  });
  it('quitar el módulo elimina la dependencia confirmada', () => {
    const s = toggleModule(confirmDependencies(toggleModule(withBase('corporativa'), 'crm')), 'crm');
    expect(s.confirmedDeps).toEqual([]);
    expect(computeQuote(s).developmentTotal).toBe(350);
  });
  it('varios módulos comparten una sola dependencia', () => {
    let s = toggleModule(toggleModule(withBase('catalogo'), 'crm'), 'reservas');
    s = confirmDependencies(s);
    expect(computeQuote(s).developmentTotal).toBe(280 + 180 + 150 + 100);
  });
});

describe('únicos vs recurrentes', () => {
  it('el hosting y el mantenimiento no se mezclan con el desarrollo', () => {
    const s = setMaintenance(setHosting(withBase('landing'), 'vps-superior'), true);
    const q = computeQuote(s);
    expect(q.developmentTotal).toBe(180);
    expect(q.hostingMonthly).toBe(35);
    expect(q.maintenanceMonthly).toBe(25);
    expect(q.monthlyTotal).toBe(60);
  });
  it('hosting externo no cuesta', () => {
    expect(computeQuote(withBase('landing')).monthlyTotal).toBe(0);
  });
  it('el Xeon se marca como sujeto a evaluación', () => {
    expect(computeQuote(setHosting(withBase('sistema'), 'xeon')).hostingNeedsEvaluation).toBe(true);
  });
});

describe('pago en dos partes', () => {
  it('las dos partes siempre suman el total', () => {
    for (const total of [0, 180, 333, 641, 1250]) {
      const p = splitPayments(total);
      expect(p.start + p.delivery).toBe(total);
    }
    expect(splitPayments(640)).toEqual({ start: 320, delivery: 320 });
  });
  it('el presupuesto expone el pago de arranque y el de entrega', () => {
    const q = computeQuote(toggleModule(withBase('corporativa'), 'bcv'));
    expect(q.developmentTotal).toBe(440);
    expect(q.payments).toEqual({ start: 220, delivery: 220 });
  });
});

describe('facturación digital', () => {
  const conFacturacion = () => confirmDependencies(toggleModule(withBase('sistema'), 'facturacion'));

  it('sin plan elegido la propuesta queda incompleta', () => {
    const q = computeQuote(conFacturacion());
    expect(q.missingBillingPlan).toBe(true);
    expect(q.complete).toBe(false);
  });
  it('el plan suma un costo mensual fijo, no al desarrollo', () => {
    const base = computeQuote(conFacturacion());
    const q = computeQuote(setBillingPlan(conFacturacion(), 'pymes'));
    expect(q.billingMonthly).toBe(30);
    expect(q.monthlyTotal).toBe(30);
    expect(q.developmentTotal).toBe(base.developmentTotal);
    expect(q.complete).toBe(true);
  });
  it('el costo mensual se suma al hosting y mantenimiento', () => {
    const s = setMaintenance(setHosting(setBillingPlan(conFacturacion(), 'gold'), 'vps-basico'), true);
    expect(computeQuote(s).monthlyTotal).toBe(55 + 15 + 25);
  });
  it('sin el módulo de facturación no hay plan', () => {
    expect(setBillingPlan(withBase('sistema'), 'gold').billingPlanId).toBeNull();
  });
  it('quitar el módulo descarta el plan', () => {
    const s = toggleModule(setBillingPlan(conFacturacion(), 'gold'), 'facturacion');
    expect(s.billingPlanId).toBeNull();
    expect(computeQuote(s).billingMonthly).toBe(0);
  });
  it('el plan viaja en la URL y en el resumen', () => {
    const s = setBillingPlan(conFacturacion(), 'emprendedor');
    expect(decodeState(encodeState(s))).toEqual(s);
    expect(buildSummary(s)).toContain('Facturación digital, plan Emprendedor');
  });
  it('validateState rechaza un plan sin el módulo', () => {
    expect(validateState({ ...withBase('sistema'), billingPlanId: 'pymes' }).length).toBeGreaterThan(0);
  });
});

describe('resumen, validación y URL', () => {
  it('el resumen separa desarrollo y mensual e incluye módulos', () => {
    const s = setHosting(toggleModule(withBase('tienda'), 'bcv'), 'vps-basico');
    const text = buildSummary(s);
    expect(text).toContain('Tienda online');
    expect(text).toContain('Tasa BCV y USDT automática');
    expect(text).toContain('DESARROLLO (2 pagos): $640 USD');
    expect(text).toContain('Para arrancar el desarrollo: $320 USD');
    expect(text).toContain('Al culminar, con todo funcionando: $320 USD');
    expect(text).toContain('MENSUAL: desde $15 USD/mes');
    expect(text).not.toContain('100 % tuyo');
    expect(text).not.toContain('sujeto a alcance');
  });
  it('validateState detecta combinaciones inválidas', () => {
    expect(validateState({ ...initialState, moduleIds: ['bcv'] }).length).toBeGreaterThan(0);
    expect(validateState({ ...initialState, baseId: 'landing', moduleIds: ['crm'] }).length).toBeGreaterThan(0);
    expect(validateState({ ...initialState, baseId: 'sistema', moduleIds: ['panel'] }).length).toBeGreaterThan(0);
    expect(validateState({ ...initialState, baseId: 'landing', moduleIds: ['bcv', 'bcv'] }).length).toBeGreaterThan(0);
    expect(validateState(withBase('landing'))).toEqual([]);
  });
  it('codifica y decodifica la configuración en la URL', () => {
    const s = setMaintenance(setHosting(confirmDependencies(toggleModule(withBase('corporativa'), 'crm')), 'vps-basico'), true);
    expect(decodeState(encodeState(s))).toEqual(s);
  });
  it('decodeState ignora valores inventados', () => {
    const s = decodeState('b=hack&m=bcv,zzz&h=nada&d=foo');
    expect(s).toEqual(initialState);
    const t = decodeState('b=landing&m=inventario,bcv');
    expect(t.moduleIds).toEqual(['bcv']);
  });
  it('arma el enlace wa.me solo con número válido', () => {
    expect(buildWhatsAppUrl(null, 'hola')).toBeNull();
    expect(buildWhatsAppUrl('58 412 000', 'a b')).toBe('https://wa.me/58412000?text=a%20b');
  });
});

