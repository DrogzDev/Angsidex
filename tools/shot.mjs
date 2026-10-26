// Uso: node tools/shot.mjs <outDir> <url> <ancho>x<alto>[,..] [fullPage=1]
// Captura el sitio en varios viewports y reporta overflow horizontal y errores de consola.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const [outDir, url, sizes, full = '1'] = process.argv.slice(2);
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
for (const size of sizes.split(',')) {
  const [w, h] = size.split('x').map(Number);
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2200);
  // Recorre la página para disparar las animaciones de entrada por scroll
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 400) {
      scrollTo({ top: y, behavior: 'instant' });
      await new Promise((r) => setTimeout(r, 120));
    }
    scrollTo({ top: 0, behavior: 'instant' });
    await new Promise((r) => setTimeout(r, 900));
  });
  const overflow = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
    offenders: [...document.querySelectorAll('body *')]
      .filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
      .slice(0, 5)
      .map((e) => e.tagName + '.' + String(e.className).slice(0, 40)),
  }));
  await page.screenshot({ path: `${outDir}/${w}x${h}${full === '1' ? '-full' : ''}.png`, fullPage: full === '1' });
  console.log(size, JSON.stringify(overflow), errors.length ? 'ERRORS: ' + errors.join(' | ') : 'no console errors');
  await ctx.close();
}
await browser.close();
