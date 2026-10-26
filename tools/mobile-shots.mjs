// Capturas móviles del sitio, del cotizador paso a paso y de una conversación con el asesor (OpenRouter simulado).
// Uso: node tools/mobile-shots.mjs <url> <outDir>
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const [url, outDir] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const b = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
const p = await ctx.newPage();
let n = 0;
const shot = async (name, full = false) => { n++; await p.waitForTimeout(500); await p.screenshot({ path: `${outDir}/${String(n).padStart(2, '0')}-${name}.png`, fullPage: full }); console.log('shot', n, name); };
const goTo = async (sel) => { await p.evaluate((s) => document.querySelector(s)?.scrollIntoView({ behavior: 'instant', block: 'start' }), sel); await p.waitForTimeout(700); };

await p.goto(url, { waitUntil: 'networkidle' });
await p.addStyleTag({ content: 'astro-dev-toolbar{display:none!important}' });
await p.waitForTimeout(2200);

// 1) Recorrido del sitio
await shot('hero');
const ids = await p.evaluate(() => [...document.querySelectorAll('main section[id], section[id]')].map((s) => s.id));
console.log('secciones', ids.join(','));
for (const id of ids) { if (id === 'calculadora') continue; await goTo('#' + id); await shot('sec-' + id); }

// 2) Cotizador paso a paso
await goTo('#calculadora'); await shot('cotizador-inicio');
await p.click('[data-base="tienda"]'); await p.waitForTimeout(400); await shot('cotizador-base-tienda');
await p.click('[data-tab="ventas"]').catch(() => {});
await p.click('[data-module="whatsapp"]').catch(() => {});
await p.click('[data-module="crm"]').catch(() => {});
await p.waitForTimeout(400); await shot('cotizador-modulos');
if (await p.locator('#dep-confirm').isVisible().catch(() => false)) { await shot('cotizador-dependencia'); await p.click('#dep-confirm'); }
await p.click('[data-hosting="vps-basico"]').catch(() => {});
await p.click('#maint').catch(() => {});
await p.waitForTimeout(400);
await p.evaluate(() => document.getElementById('out-dev')?.scrollIntoView({ behavior: 'instant', block: 'center' }));
await shot('cotizador-resumen');
await p.evaluate(() => document.getElementById('btn-send')?.scrollIntoView({ behavior: 'instant', block: 'center' }));
await shot('cotizador-pago-y-envio');

// 3) Conversación con el asesor
await goTo('#calculadora');
await p.locator('[data-open-advisor]').first().click();
await p.locator('#advisor .adv-panel').waitFor({ state: 'visible' });
await shot('asesor-formulario');
await p.fill('#adv-name', 'María Pérez');
await p.fill('#adv-business', 'Panadería La Espiga');
await p.fill('#adv-email', 'maria@example.com');
await p.fill('#adv-sector', 'Alimentos');
await p.fill('#adv-need', 'Quiero vender mis panes por internet y controlar el inventario.');
await p.waitForFunction(() => !!document.querySelector('[name="cf-turnstile-response"]')?.value, null, { timeout: 25000 }).catch(() => {});
await shot('asesor-formulario-lleno');
await p.click('#adv-start');
await p.locator('#adv-chat').waitFor({ state: 'visible', timeout: 15000 });
await shot('asesor-saludo');
await p.fill('#adv-input', 'Quiero una tienda online para vender mis panes');
await p.keyboard.press('Enter');
await p.waitForTimeout(1200); await shot('asesor-escribiendo');
await p.locator('.adv-card').nth(2).waitFor({ timeout: 20000 });
await p.waitForFunction(() => !document.querySelector('.adv-msg.typing') && !document.querySelector('#adv-send')?.disabled, null, { timeout: 20000 });
await p.locator('.adv-proposals').scrollIntoViewIfNeeded();
await shot('asesor-propuestas');
for (let i = 0; i < 3; i++) { await p.locator('.adv-card').nth(i).scrollIntoViewIfNeeded(); await shot('asesor-propuesta-' + (i + 1)); }
await p.locator('.adv-card').nth(1).locator('button', { hasText: 'Negociar' }).click();
await p.locator('.adv-card[data-tier="adjusted"]').waitFor({ timeout: 20000 });
await p.waitForFunction(() => !document.querySelector('.adv-msg.typing') && !document.querySelector('#adv-send')?.disabled, null, { timeout: 20000 });
await p.locator('.adv-card[data-tier="adjusted"]').scrollIntoViewIfNeeded();
await shot('asesor-propuesta-ajustada');
await b.close();
