// Humo en vivo: burbuja → formulario → conversación con el modelo REAL (usa créditos, pocos centavos).
// Uso: node tools/advisor-live.mjs <url> <outDir> [ancho=1440] [alto=900]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const [url, outDir, w = '1440', h = '900'] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });
const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: +w, height: +h }, hasTouch: +w < 800, isMobile: +w < 800 });
const p = await ctx.newPage();
const errors = [];
p.on('pageerror', (e) => errors.push(String(e)));
p.on('console', (m) => m.type() === 'error' && !/challenges\.cloudflare|Failed to load resource/.test(m.text()) && errors.push(m.text()));
const log = (...a) => console.log(...a);

await p.goto(url, { waitUntil: 'networkidle' });
await p.waitForTimeout(800);
const bubble = p.locator('.adv-bubble');
log('burbuja visible:', await bubble.isVisible(), '|', (await bubble.innerText()).replace(/\n/g, ' · '));
await p.screenshot({ path: `${outDir}/${w}-0-bubble.png` });

await bubble.click();
await p.locator('#adv-form').waitFor({ state: 'visible' });
await p.fill('#adv-name', 'Miguel');
await p.fill('#adv-business', 'Hamburguesería El Fogón');
await p.fill('#adv-email', 'prueba@example.com');
await p.fill('#adv-sector', 'Restaurante');
await p.fill('#adv-need', 'Recibo pedidos por WhatsApp y se me pierden. Quiero ordenarlos.');
await p.waitForFunction(() => !!document.querySelector('[name="cf-turnstile-response"]')?.value, null, { timeout: 25000 });
await p.click('#adv-start');
await p.locator('#adv-chat').waitFor({ state: 'visible', timeout: 20000 });
log('chat iniciado. saludo:', (await p.locator('.adv-msg.assistant').first().innerText()).slice(0, 140));

const send = async (t) => {
  await p.fill('#adv-input', t);
  await p.keyboard.press('Enter');
  await p.waitForFunction(() => !document.querySelector('.adv-msg.typing') && !document.querySelector('#adv-send')?.disabled, null, { timeout: 90000 });
};
await send('Somos 4 personas y vendemos unas 80 hamburguesas diarias. Tenemos un solo local. Queremos ordenar los pedidos y avisar al cliente cuando estén listos. Tengo como 600 dólares.');
let cards = await p.locator('.adv-card').count();
if (!cards) {
  await send('Ya te conté todo lo necesario. Por favor muéstrame las propuestas.');
  cards = await p.locator('.adv-card').count();
}
log('tarjetas:', cards, '|', (await p.locator('.adv-card-head h3').allInnerTexts()).join(', '), '|', (await p.locator('.adv-card-price b').allInnerTexts()).join(', '));
const last = (await p.locator('.adv-msg.assistant').last().innerText()).slice(0, 500);
log('última respuesta:', last);
log('avisos de precio:', (await p.locator('.adv-msg.notice').allInnerTexts()).filter((t) => t.includes('precios oficiales')).length);
await p.locator('.adv-log').evaluate((e) => (e.scrollTop = e.scrollHeight));
await p.screenshot({ path: `${outDir}/${w}-1-live.png` });
log('errores de consola:', errors.length ? errors.join(' | ') : 'ninguno');
await b.close();
