// Prueba E2E del cotizador en el navegador real. Uso: node tools/calc-test.mjs <url>
import { chromium } from 'playwright';
const url = process.argv[2];
const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['clipboard-read', 'clipboard-write'] });
const p = await ctx.newPage();
const errors = [];
p.on('pageerror', (e) => errors.push(String(e)));
p.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
await p.goto(url, { waitUntil: 'networkidle' });
const txt = (s) => p.locator(s).first().innerText();
let fails = 0;
const ok = (name, cond, extra = '') => { console.log(cond ? 'PASS' : 'FAIL', name, extra); if (!cond) fails++; };

await p.locator('#calculadora').scrollIntoViewIfNeeded();
ok('inicio: total 0', (await txt('#out-dev')).includes('$0'));
ok('módulos deshabilitados sin base', await p.locator('[data-module="whatsapp"]').isDisabled());

await p.click('[data-base="corporativa"]');
ok('base corporativa $350', (await txt('#out-dev')).includes('$350'), await txt('#out-dev'));
await p.click('[data-module="whatsapp"]');
ok('+WhatsApp = $500 (desde? no)', (await txt('#out-dev')).includes('$500'), await txt('#out-dev'));
await p.click('[data-module="whatsapp"]');
ok('quitar módulo vuelve a $350', (await txt('#out-dev')).includes('$350'));

await p.click('[data-tab="ventas"]');
await p.click('[data-module="crm"]');
ok('CRM muestra dependencia pendiente', await p.locator('#dep-box').isVisible());
ok('dependencia NO sumada ($530)', (await txt('#out-dev')).includes('$530'), await txt('#out-dev'));
ok('CTA bloqueado con dependencia pendiente', await p.locator('#btn-send').isDisabled());
await p.click('#dep-confirm');
ok('al confirmar suma $100 ($630)', (await txt('#out-dev')).includes('$630'), await txt('#out-dev'));
ok('CTA habilitado', await p.locator('#btn-send').isEnabled());

await p.click('[data-hosting="vps-superior"]');
await p.click('#maint');
const mon = await txt('#out-month');
ok('mensual separado = $60', mon.includes('$60'), mon.replace(/\n/g, ' '));
ok('único sigue en $630', (await txt('#out-dev')).includes('$630'));

await p.click('[data-tab="admin"]');
ok('panel se puede agregar (no incluido en corporativa)', await p.locator('[data-module="panel"]').isEnabled());
await p.click('[data-base="landing"]');
ok('al cambiar a landing se descartan módulos incompatibles', !(await p.locator('#out-lines').innerText()).includes('CRM'));
await p.click('[data-base="sistema"]');
ok('sistema: panel incluido y deshabilitado', await p.locator('[data-module="panel"]').isDisabled());

// Compartir por URL
await p.click('[data-base="tienda"]');
await p.click('#btn-share');
const shared = await p.evaluate(() => navigator.clipboard.readText());
ok('enlace compartido', shared.includes('b=tienda'), shared);
const p2 = await ctx.newPage();
await p2.goto(shared, { waitUntil: 'networkidle' });
ok('URL restaura la configuración', (await p2.locator('#out-dev').innerText()).includes('$550'));

// Copiar
await p.click('#btn-copy');
const copied = await p.evaluate(() => navigator.clipboard.readText());
ok('copiar presupuesto', copied.includes('Tienda online') && copied.includes('DESARROLLO'));

// Persistencia
await p.reload({ waitUntil: 'networkidle' });
ok('persistencia en localStorage', (await p.locator('#out-dev').innerText()).includes('$550'));

// WhatsApp (número de Angside configurado → abre wa.me con el mensaje)
const waPopup = p.waitForEvent('popup');
await p.click('#btn-send');
const waUrl = (await waPopup).url();
ok('WhatsApp abre el número de Angside', waUrl.includes('584145487581'), waUrl.slice(0, 80));

// Reset
await p.click('#btn-reset');
ok('reiniciar', (await txt('#out-dev')).includes('$0'));

// Desde servicios → preselecciona
await p.goto(url, { waitUntil: 'networkidle' });
await p.evaluate(() => localStorage.clear());
await p.reload({ waitUntil: 'networkidle' });
await p.click('[data-service="sistema"]');
ok('servicio preselecciona base', (await p.locator('#out-dev').innerText()).includes('$650'));

// Pago en dos partes + facturación (costo mensual fijo)
await p.evaluate(() => localStorage.clear());
await p.reload({ waitUntil: 'networkidle' });
await p.click('[data-base="sistema"]');
ok('pago en dos partes visible', await p.locator('#out-pay').isVisible());
ok('arranque = 50 % de $650', (await txt('#out-pay-start')).includes('$325'), await txt('#out-pay-start'));
ok('entrega = 50 % de $650', (await txt('#out-pay-end')).includes('$325'), await txt('#out-pay-end'));
ok('paso de facturación oculto sin facturación', !(await p.locator('#billing-step').isVisible()));
await p.click('[data-tab="fiscal"]');
await p.click('[data-module="facturacion"]');
ok('paso de facturación aparece', await p.locator('#billing-step').isVisible());
ok('CTA bloqueado sin plan', await p.locator('#btn-send').isDisabled());
ok('aviso de plan pendiente', (await p.locator('#out-warn').innerText()).includes('facturación'));
await p.click('[data-billing="pymes"]');
ok('CTA habilitado con plan', await p.locator('#btn-send').isEnabled());
ok('mensual incluye facturación $30 fijo', (await txt('#out-month')).includes('$30') && !(await txt('#out-month')).includes('Desde'), (await txt('#out-month')).replace(/\n/g, ' '));
ok('desarrollo no incluye el plan ($830)', (await txt('#out-dev')).includes('$830'), await txt('#out-dev'));
await p.click('#btn-copy');
const t = await p.evaluate(() => navigator.clipboard.readText());
ok('resumen: 2 pagos y facturación, sin textos legales de cierre', t.includes('2 pagos') && t.includes('Facturación digital, plan Pymes') && !t.includes('100 % tuyo'));
ok('bloque de condiciones visible', await p.locator('#terms-title').isVisible());
await p.locator('#calculadora').screenshot({ path: process.argv[3] ?? 'calc.png' });

ok('sin errores de consola', errors.length === 0, errors.join(' | '));
await b.close();
process.exit(fails ? 1 : 0);
