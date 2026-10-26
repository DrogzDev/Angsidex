// E2E del asistente de IA. Requiere: sitio en <url>, backend Django y tests/mock_openrouter.py (o un OpenRouter real).
// Uso: node tools/advisor-test.mjs <url> <outDir> [ancho=1440] [alto=900]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const [url, outDir, w = '1440', h = '900'] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const width = +w;
const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width, height: +h }, hasTouch: width < 800, isMobile: width < 800 });
const p = await ctx.newPage();
const errors = [];
p.on('pageerror', (e) => errors.push(String(e)));
p.on('console', (m) => m.type() === 'error' && !/challenges\.cloudflare|Failed to load resource/.test(m.text()) && errors.push(m.text()));
const apiCalls = [];
p.on('request', (r) => r.url().includes('/api/ai/') && apiCalls.push(r.method() + ' ' + new URL(r.url()).pathname));

let fails = 0;
const ok = (name, cond, extra = '') => { console.log(cond ? 'PASS' : 'FAIL', name, extra); if (!cond) fails++; };
const sendMsg = async (text) => { await p.fill('#adv-input', text); await p.keyboard.press('Enter'); };
const idle = () => p.waitForFunction(() => !document.querySelector('.adv-msg.typing') && !document.querySelector('#adv-send')?.disabled, null, { timeout: 20000 });

await p.goto(url, { waitUntil: 'networkidle' });
await p.evaluate(() => document.getElementById('calculadora').scrollIntoView({ behavior: 'instant' }));
await p.waitForTimeout(900);
const cta = p.locator('[data-open-advisor]').first();
ok('CTA visible en el cotizador', await cta.isVisible());
ok('texto del CTA', (await p.locator('div.cta').innerText()).includes('¿No sabes qué necesita tu negocio?'));

await cta.click();
const dialog = p.locator('#advisor .adv-panel');
await dialog.waitFor({ state: 'visible' });
await p.waitForTimeout(500);
ok('panel abierto como diálogo accesible', (await dialog.getAttribute('aria-modal')) === 'true');
ok('scroll del fondo bloqueado', await p.evaluate(() => document.documentElement.classList.contains('adv-lock')));
ok('formulario previo visible (sin chat)', (await p.locator('#adv-form').isVisible()) && !(await p.locator('#adv-chat').isVisible()));
ok('casilla comercial NO marcada por defecto', !(await p.locator('input[name=marketing_consent]').isChecked()));
ok('enlace a política de privacidad', (await p.locator('.adv-legal a[href="/privacidad"]').count()) === 1);

await p.click('#adv-start');
ok('muestra errores de validación', (await p.locator('[data-err="name"]').innerText()).length > 0 && (await p.locator('[data-err="need"]').innerText()).length > 0);
ok('sin llamadas a la API con formulario inválido', apiCalls.filter((c) => c.startsWith('POST')).length === 0);

await p.fill('#adv-name', 'María Pérez');
await p.fill('#adv-business', 'Panadería La Espiga');
await p.fill('#adv-email', 'maria@example.com');
await p.fill('#adv-sector', 'Alimentos');
await p.fill('#adv-need', 'Quiero vender mis panes por internet y controlar el inventario.');
await p.locator('.adv-more summary').click();
await p.selectOption('#adv-budget_range', '500-1000');
await p.waitForFunction(() => !!document.querySelector('[name="cf-turnstile-response"]')?.value, null, { timeout: 25000 }).catch(() => {});
ok('Turnstile entregó un token', ((await p.evaluate(() => document.querySelector('[name="cf-turnstile-response"]')?.value ?? '')).length) > 10);

await Promise.all([p.click('#adv-start'), p.click('#adv-start', { timeout: 500 }).catch(() => {})]);
await p.locator('#adv-chat').waitFor({ state: 'visible', timeout: 15000 });
ok('conversación iniciada', await p.locator('#adv-chat').isVisible());
ok('un solo POST /sessions', apiCalls.filter((c) => c === 'POST /api/ai/sessions').length === 1, apiCalls.join(','));
const greeting = await p.locator('.adv-msg.assistant').first().innerText();
ok('saludo de descubrimiento', greeting.includes('Panadería La Espiga') && greeting.includes('qué te gustaría mejorar con una página web o un sistema'));

// Descubrimiento → clasificación → tres propuestas
await sendMsg('Quiero una tienda online para vender mis panes');
await p.locator('.adv-card').nth(2).waitFor({ timeout: 20000 });
await idle();
const cards = p.locator('.adv-card');
ok('tres tarjetas de propuesta', (await cards.count()) === 3);
const names = await p.locator('.adv-card-head h3').allInnerTexts();
ok('Esencial / Recomendada / Completa', names.join('|') === 'Esencial|Recomendada|Completa', names.join('|'));
const prices = await p.locator('.adv-card-price b').allInnerTexts();
ok('precios del motor ($550 / $790 / $1.090)', prices.join('|') === '$550 USD|$790 USD|$1.090 USD', prices.join('|'));
const cardTexts = await cards.allInnerTexts();
const cardContent = await cards.evaluateAll((els) => els.map((e) => e.textContent)); // incluye <details> cerrados
ok('forma de pago en dos partes', cardTexts[1].includes('Para arrancar: $395 USD') && cardTexts[1].includes('Al culminar, con todo funcionando: $395 USD'));
ok('costos recurrentes separados (facturación fija en la completa)', cardTexts[2].includes('Facturación digital Emprendedor') && cardTexts[2].includes('Total mensual: desde $35 USD/mes'), cardTexts[2].match(/Total mensual[^\n]*/)?.[0]);
ok('plazo pendiente de evaluación', cardTexts.every((t) => t.includes('Plazo: Pendiente de evaluación')));
ok('beneficio específico de la funcionalidad', cardContent[0].includes('evita que se pierdan mensajes'));
ok('dentro del presupuesto indicado (rango $500–$1.000)', cardTexts[0].includes('Dentro de tu presupuesto') && cardTexts[2].includes('Supera tu presupuesto'));
const profile = await p.locator('.adv-profile').first().innerText();
ok('clasificación y complejidad visibles', profile.includes('Pequeño negocio') && /Complejidad/i.test(profile), profile.replace(/\n/g, ' '));
ok('cada tarjeta tiene sus 3 acciones', (await p.locator('.adv-card-actions').first().locator('button').allInnerTexts()).join('|') === 'Ver en el cotizador|Solicitar propuesta|Negociar esta propuesta');
const order = await p.evaluate(() => [...document.querySelector('.adv-log').children].map((e) => (e.classList.contains('adv-proposals') ? 'cards' : e.className.replace('adv-msg ', ''))).join(','));
ok('tarjetas antes de la explicación del asistente', order.indexOf('cards') < order.lastIndexOf('assistant'), order);
await p.locator('.adv-proposals').scrollIntoViewIfNeeded();
await p.screenshot({ path: `${outDir}/${w}-1-cards.png` });
const ov0 = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, lw: document.querySelector('.adv-log').scrollWidth, lcw: document.querySelector('.adv-log').clientWidth }));
ok('tarjetas sin overflow horizontal', ov0.sw <= ov0.cw && ov0.lw <= ov0.lcw, JSON.stringify(ov0));

// Clasificación editable (no cambia precios)
await p.locator('.adv-profile .adv-link').first().click();
await p.selectOption('.adv-profile-edit select', 'large');
await p.locator('.adv-profile-edit .btn').first().click();
await p.waitForFunction(() => document.querySelector('[data-profile-size]')?.textContent === 'Empresa grande', null, { timeout: 8000 });
ok('el cliente puede corregir su clasificación', true);
ok('los precios no cambian al corregir el tamaño', (await p.locator('.adv-card-price b').allInnerTexts()).join('|') === prices.join('|'));

// Solicitar propuesta
await cards.nth(1).locator('button', { hasText: 'Solicitar propuesta' }).click();
await p.waitForFunction(() => document.querySelector('.adv-card[data-tier="recommended"] .adv-card-actions .btn:not(.btn-dark)')?.textContent?.includes('solicitada'), null, { timeout: 8000 });
ok('propuesta solicitada', true);

// Negociación → propuesta ajustada
await cards.nth(1).locator('button', { hasText: 'Negociar' }).click();
await p.locator('.adv-card[data-tier="adjusted"]').waitFor({ timeout: 20000 });
await idle();
const adj = await p.locator('.adv-card[data-tier="adjusted"]').innerText();
ok('propuesta ajustada recalculada por el motor ($430)', adj.includes('Ajustada a tu presupuesto') && adj.includes('$430 USD'), adj.split('\n').slice(0, 6).join(' | '));
ok('la IA no ofrece descuentos (sin aviso de precios)', (await p.locator('.adv-msg.notice').allInnerTexts()).every((t) => !t.includes('precios oficiales')));
await p.screenshot({ path: `${outDir}/${w}-2-adjusted.png` });

// Ver en el cotizador (tarjeta recomendada)
await cards.nth(1).locator('button', { hasText: 'Ver en el cotizador' }).click();
await p.waitForTimeout(800);
ok('panel se cierra', !(await p.locator('#advisor').isVisible()));
ok('cotizador recibió la propuesta recomendada ($790)', (await p.locator('#out-dev').innerText()).includes('$790'), await p.locator('#out-dev').innerText());
ok('costo mensual del hosting aplicado ($15)', (await p.locator('#out-month').innerText()).includes('$15'));
ok('scroll del fondo liberado', !(await p.evaluate(() => document.documentElement.classList.contains('adv-lock'))));

// Reanudar: las tarjetas vuelven a mostrarse
await p.locator('[data-open-advisor]').first().click();
await p.locator('#adv-chat').waitFor({ state: 'visible', timeout: 10000 });
ok('reanuda sin pedir los datos otra vez', !(await p.locator('#adv-form').isVisible()));
ok('las tarjetas se restauran', (await p.locator('.adv-card').count()) === 4);
ok('la propuesta solicitada sigue marcada', (await p.locator('.adv-card[data-tier="recommended"] .adv-card-actions .btn:not(.btn-dark)').first().innerText()).includes('solicitada'));

// Texto del modelo nunca se interpreta como HTML
ok('mensajes renderizados como texto', !(await p.evaluate(() => !!document.querySelector('.adv-msg img, .adv-msg script, .adv-msg b'))));

const ov = await p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, pw: document.querySelector('.adv-panel').scrollWidth, pcw: document.querySelector('.adv-panel').clientWidth }));
ok('sin overflow horizontal', ov.sw <= ov.cw && ov.pw <= ov.pcw, JSON.stringify(ov));

await p.keyboard.press('Escape');
await p.waitForTimeout(500);
ok('Escape cierra el panel', !(await p.locator('#advisor').isVisible()));
ok('el foco vuelve al botón que lo abrió', await p.evaluate(() => document.activeElement?.hasAttribute('data-open-advisor')));
await p.locator('[data-open-advisor]').first().click();
await p.waitForTimeout(500);
for (let i = 0; i < 14; i++) await p.keyboard.press('Tab');
ok('el foco no escapa del panel', await p.evaluate(() => !!document.activeElement?.closest('#advisor')));

ok('sin errores de consola', errors.length === 0, errors.join(' | '));
await b.close();
process.exit(fails ? 1 : 0);
