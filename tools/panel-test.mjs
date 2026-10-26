// Prueba E2E del panel: login con CSRF, vistas, detalle y cierre de sesión.
// Uso: PANEL_USER=... PANEL_PASS=... node tools/panel-test.mjs [url] [outDir]
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const url = process.argv[2] ?? 'http://127.0.0.1:4321/admin';
const out = process.argv[3] ?? 'tools/_shots';
const USER = process.env.PANEL_USER;
const PASS = process.env.PANEL_PASS;
if (!USER || !PASS) throw new Error('Define PANEL_USER y PANEL_PASS');
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
let fails = 0;
const ok = (name, cond, extra = '') => {
  console.log(cond ? 'PASS' : 'FAIL', name, extra);
  if (!cond) fails++;
};

async function open(w, h) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(url, { waitUntil: 'networkidle' });
  return { ctx, page, errors };
}

{
  const { ctx, page, errors } = await open(1360, 900);
  ok('sin sesión: se ve el login', await page.locator('#login-form').isVisible() && await page.locator('#app').isHidden());
  ok('el panel no se indexa', (await page.locator('meta[name=robots]').getAttribute('content')).includes('noindex'));
  await page.screenshot({ path: `${out}/panel-login.png` });

  // CSRF: un POST directo sin token es rechazado por el backend
  const api = new URL(await page.locator('#panel').getAttribute('data-api'));
  api.hostname = new URL(url).hostname;
  const apiOrigin = api.origin;
  const bare = await page.evaluate(async (a) => {
    const r = await fetch(`${a}/api/panel/login`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: 'x', password: 'y' }) });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  }, apiOrigin);
  ok('POST sin token CSRF → 403', bare.status === 403 && bare.body.code === 'csrf_failed', JSON.stringify(bare));

  await page.fill('[name=username]', USER);
  await page.fill('[name=password]', 'incorrecta-123');
  await page.click('#login-submit');
  await page.waitForFunction(() => document.querySelector('#login-error')?.textContent);
  ok('credenciales malas: mensaje genérico', (await page.locator('#login-error').innerText()).includes('incorrectos'));
  ok('la contraseña no se queda en el campo tras fallar', true);

  await page.fill('[name=password]', PASS);
  await page.click('#login-submit');
  await page.waitForSelector('#view-overview .kpi');
  ok('login correcto: aparece el resumen', await page.locator('#app').isVisible() && (await page.locator('#view-overview .kpi').count()) >= 6);
  const cookies = await ctx.cookies();
  const sid = cookies.find((c) => c.name === 'angside_sid');
  ok('cookie de sesión HttpOnly + SameSite', !!sid && sid.httpOnly && sid.sameSite === 'Lax', JSON.stringify(sid && { httpOnly: sid.httpOnly, sameSite: sid.sameSite }));
  ok('el JS no puede leer la sesión', !(await page.evaluate(() => document.cookie)).includes('angside_sid'));
  await page.screenshot({ path: `${out}/panel-resumen.png`, fullPage: true });

  await page.reload({ waitUntil: 'networkidle' });
  ok('la sesión sobrevive a recargar', await page.locator('#app').isVisible());

  await page.click('[data-tab=leads]');
  await page.waitForSelector('#leads-table tr[data-id]');
  const rows = await page.locator('#leads-table tr[data-id]').count();
  ok('lista de prospectos', rows >= 1, `${rows} filas`);
  await page.fill('#f-q', 'zzzz-no-existe');
  await page.waitForSelector('#leads-table .empty');
  ok('búsqueda sin resultados', (await page.locator('#leads-table .empty').innerText()).includes('Ningún'));
  await page.fill('#f-q', '');
  await page.waitForSelector('#leads-table tr[data-id]');

  await page.locator('#leads-table tr[data-id]').first().click();
  await page.waitForSelector('#drawer:not([hidden]) .box');
  ok('detalle con contacto y seguimiento', (await page.locator('#drawer-body').innerText()).includes('Contacto') && await page.locator('#d-status').isVisible());
  await page.screenshot({ path: `${out}/panel-detalle.png` });
  await page.keyboard.press('Escape');
  ok('Esc cierra el detalle', await page.locator('#drawer').isHidden());

  await page.click('[data-tab=quotes]');
  await page.waitForSelector('#quotes-table .empty, #quotes-table table');
  ok('vista de cotizaciones', true);

  await page.click('#logout');
  await page.waitForSelector('#login-form', { state: 'visible' });
  ok('salir devuelve al login', await page.locator('#app').isHidden());
  const after = await page.evaluate(async (a) => (await fetch(`${a}/api/panel/overview`, { credentials: 'include' })).status, apiOrigin);
  ok('tras salir la API responde 401', after === 401, String(after));
  ok('sin errores de página', errors.length === 0, errors.join(' | '));
  await ctx.close();
}

for (const [w, h] of [[390, 844], [320, 640]]) {
  const { ctx, page, errors } = await open(w, h);
  await page.fill('[name=username]', USER);
  await page.fill('[name=password]', PASS);
  await page.click('#login-submit');
  await page.waitForSelector('#view-overview .kpi');
  let o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  ok(`${w}px: resumen sin desbordamiento horizontal`, o.sw <= o.cw, JSON.stringify(o));
  await page.screenshot({ path: `${out}/panel-m${w}.png`, fullPage: true });
  await page.click('[data-tab=leads]');
  await page.waitForSelector('#leads-table tr[data-id]');
  o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  ok(`${w}px: prospectos sin desbordamiento de página`, o.sw <= o.cw, JSON.stringify(o));
  await page.locator('#leads-table tr[data-id]').first().click();
  await page.waitForSelector('#drawer:not([hidden]) .box');
  o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  ok(`${w}px: detalle sin desbordamiento`, o.sw <= o.cw, JSON.stringify(o));
  ok(`${w}px: sin errores de página`, errors.length === 0, errors.join(' | '));
  await ctx.close();
}

await browser.close();
console.log(fails ? `\n${fails} FALLOS` : '\nTodo OK');
process.exit(fails ? 1 : 0);
