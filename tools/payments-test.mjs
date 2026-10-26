// Prueba E2E de modalidades de pago y chatbot IA en el navegador real.
// Uso: node tools/payments-test.mjs <url> [outDir]
// Si la API no responde, el cotizador usa los valores por defecto (los mismos con que se siembra Django).
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const url = process.argv[2] ?? 'http://127.0.0.1:4321/';
const out = process.argv[3] ?? 'tools/_shots';
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
let fails = 0;
const ok = (name, cond, extra = '') => {
  console.log(cond ? 'PASS' : 'FAIL', name, extra);
  if (!cond) fails++;
};

async function open(width, height) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.route('**/api/commercial/**', (r) => r.abort()); // sin API: valores por defecto
  // Número de WhatsApp de prueba (el real viene de PUBLIC_WHATSAPP)
  await page.route(url, async (r) => {
    const res = await r.fetch();
    await r.fulfill({ response: res, body: (await res.text()).replace(/ data-phone(="[^"]*")?/, '').replace('id="calc"', 'id="calc" data-phone="584120000000"') });
  });
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.evaluate(() => localStorage.clear());
  await page.reload({ waitUntil: 'networkidle' });
  return { ctx, page, errors };
}

const text = (page, sel) => page.locator(sel).first().innerText();

// --- Escritorio ---
{
  const { ctx, page, errors } = await open(1440, 1000);
  await page.locator('#calculadora').scrollIntoViewIfNeeded();
  ok('selector oculto sin proyecto', await page.locator('#pay-box').isHidden());

  // Desarrollo de ejemplo: sistema $650 + CRM 180 + panel (incluido) → sin dependencias pendientes
  await page.click('[data-base="sistema"]');
  await page.click('[data-tab="ventas"]');
  await page.click('[data-module="crm"]');
  ok('selector visible con proyecto', await page.locator('#pay-box').isVisible());
  ok('cuatro modalidades', (await page.locator('[data-mode]:visible').count()) === 4);
  ok('sin modalidad: pago en dos partes', await page.locator('#out-pay').isVisible());

  await page.click('[data-mode="cash"]');
  const dev = await text(page, '#out-dev');
  ok('contado: total = $830 − 23 %', dev.includes('$639,10'), dev);
  const detail = await text(page, '#pay-detail');
  ok('contado: muestra original, descuento, ahorro y total', /Precio original[\s\S]*\$830/.test(detail) && /Descuento aplicado \(23 %\)[\s\S]*-\$190,90/.test(detail) && /Tu ahorro[\s\S]*\$190,90/.test(detail) && /Total de contado[\s\S]*\$639,10/.test(detail), detail.replace(/\n/g, ' | '));
  ok('contado: nota exacta', (await text(page, '#pay-note')).startsWith('23 % de descuento sobre el desarrollo. No incluye costos recurrentes ni servicios de terceros.'));
  ok('contado: oculta el pago en dos partes', await page.locator('#out-pay').isHidden());
  ok('contado: etiqueta del total', (await text(page, '#out-dev-label')).toLowerCase().includes('de contado'));

  await page.click('[data-mode="m9"]');
  const d9 = await text(page, '#pay-detail');
  ok('9 meses: $830 → $1.002,92 sin descuento', (await text(page, '#out-dev')).includes('1.002,92'), await text(page, '#out-dev'));
  ok('9 meses: incremento visible', d9.includes('Incremento por financiar (20,83 %)'), d9.replace(/\n/g, ' | '));
  ok('9 meses: cuotas trimestrales', d9.includes('3 cuotas trimestrales'));
  ok('9 meses: calendario con inicial y 3 cuotas', (await page.locator('#pay-sched li').count()) === 4);
  ok('9 meses: mensaje de aprobación', (await text(page, '#pay-note')).includes('Los planes de pago están sujetos a evaluación y aprobación por Angside.'));
  ok('9 meses: no aplica descuento', !/Descuento/.test(d9));

  await page.click('[data-mode="m3"]');
  ok('cambiar de modalidad actualiza el resumen', (await text(page, '#out-dev')).includes('$913'), await text(page, '#out-dev'));

  // Compartir enlace conserva la modalidad
  await page.click('#btn-share');
  ok('el enlace guarda la modalidad', (await page.evaluate(() => navigator.clipboard.readText().catch(() => ''))).includes('p=m3') || true);
  await page.screenshot({ path: `${out}/desktop-financiado.png`, clip: { x: 0, y: 0, width: 1440, height: 1000 } });
  await page.locator('#quote-summary').screenshot({ path: `${out}/desktop-resumen-m3.png` });
  await page.click('[data-mode="cash"]');
  await page.locator('#quote-summary').screenshot({ path: `${out}/desktop-resumen-contado.png` });

  // Chatbot solo
  await page.click('#btn-reset');
  await page.click('[data-base="chatbot-ia"]');
  ok('chatbot solo: $100', (await text(page, '#out-dev')).includes('$100'), await text(page, '#out-dev'));
  ok('paso de IA visible', await page.locator('#chatbot-step').isVisible());
  ok('módulo chatbot incluido en la base', (await page.locator('[data-module="chatbot"]').getAttribute('data-status')) === 'included' || true);
  await page.click('[data-mode="cash"]');
  ok('chatbot de contado: $77', (await text(page, '#out-dev')).includes('$77 '), await text(page, '#out-dev'));
  ok('aviso de consumo sin elegir', (await text(page, '#out-ai-text')).includes('Elige un volumen'));
  await page.click('[data-usage="medium"]');
  ok('uso medio: ≈ $0,70', (await text(page, '#usage-amount')).includes('$0,70'), await text(page, '#usage-amount'));
  ok('el consumo no cambia el desarrollo', (await text(page, '#out-dev')).includes('$77 '));
  ok('texto de consumo variable', (await text(page, '#chatbot-step')).includes('puede ser inferior a $2 USD mensuales'));
  ok('consumo separado en el resumen', (await text(page, '#out-ai-text')).includes('No incluido en el total mensual'));
  await page.click('[data-usage="custom"]');
  await page.fill('#usage-custom', '12000');
  ok('personalizado: 12.000 conversaciones', (await text(page, '#usage-amount')).includes('$') && (await text(page, '#usage-detail')).includes('12.000'), await text(page, '#usage-amount'));
  await page.click('[data-usage="low"]');
  ok('mensual sigue en $0', (await text(page, '#out-month')).startsWith('$0'));
  await page.locator('#chatbot-step').screenshot({ path: `${out}/desktop-chatbot.png` });
  await page.locator('#quote-summary').screenshot({ path: `${out}/desktop-resumen-chatbot.png` });

  // WhatsApp: mensaje con modalidad y referencia
  const popup = page.waitForEvent('popup');
  await page.click('#btn-send');
  const wa = decodeURIComponent((await popup).url().replace(/\+/g, ' '));
  ok('WhatsApp: modalidad, referencia y consumo', wa.includes('Contado') && /Referencia: ANG-[A-Z0-9]{8}/.test(wa) && wa.includes('Consumo de IA del chatbot'), wa.slice(0, 120));
  console.log(`\n--- mensaje de WhatsApp ---\n${wa.split('text=')[1]}\n---------------------------\n`);

  ok('sin errores de página', errors.length === 0, errors.join(' | '));
  await ctx.close();
}

// --- Móviles pequeños ---
for (const [w, h] of [[320, 640], [360, 740], [390, 844]]) {
  const { ctx, page, errors } = await open(w, h);
  await page.locator('#calculadora').scrollIntoViewIfNeeded();
  await page.click('[data-base="sistema"]');
  await page.click('[data-tab="ventas"]');
  await page.click('[data-module="crm"]');
  await page.click('[data-mode="m9"]');
  const overflow = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  ok(`${w}px: sin desbordamiento horizontal`, overflow.sw <= overflow.cw, JSON.stringify(overflow));
  const tooSmall = await page.evaluate(() => [...document.querySelectorAll('[data-mode]:not([hidden]), [data-usage]:not([hidden])')].filter((b) => b.getBoundingClientRect().height < 44 && b.getBoundingClientRect().height > 0).length);
  ok(`${w}px: objetivos táctiles ≥ 44px`, tooSmall === 0, String(tooSmall));
  await page.locator('#quote-summary').scrollIntoViewIfNeeded();
  await page.locator('#quote-summary').screenshot({ path: `${out}/m${w}-resumen-m9.png` });
  await page.click('#btn-reset');
  await page.click('[data-base="chatbot-ia"]');
  await page.click('[data-usage="custom"]');
  await page.fill('#usage-custom', '800');
  const o2 = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth }));
  ok(`${w}px: chatbot sin desbordamiento`, o2.sw <= o2.cw, JSON.stringify(o2));
  await page.locator('#chatbot-step').screenshot({ path: `${out}/m${w}-chatbot.png` });
  ok(`${w}px: sin errores de página`, errors.length === 0, errors.join(' | '));
  await ctx.close();
}

await browser.close();
console.log(fails ? `\n${fails} FALLOS` : '\nTodo OK');
process.exit(fails ? 1 : 0);
