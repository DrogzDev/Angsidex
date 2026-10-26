// Comprueba que el widget de Turnstile no tapa el botón "Empezar conversación" en móvil.
// Uso: node tools/captcha-overlap.mjs <url> [outDir]
import { chromium } from 'playwright';
const [url, outDir = '.'] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch());
let fails = 0;
for (const [w, h] of [[390, 844], [360, 740], [320, 640]]) {
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
  const p = await ctx.newPage();
  await p.goto(url, { waitUntil: 'networkidle' });
  await p.addStyleTag({ content: 'astro-dev-toolbar{display:none!important}' });
  await p.locator('[data-open-advisor]').first().click();
  await p.locator('#adv-form').waitFor({ state: 'visible' });
  await p.waitForSelector('#adv-turnstile > div', { state: 'attached', timeout: 20000 });
  await p.waitForTimeout(1500);
  await p.locator('#adv-start').scrollIntoViewIfNeeded();
  const r = await p.evaluate(() => {
    const c = document.querySelector('#adv-turnstile').getBoundingClientRect();
    const bt = document.querySelector('#adv-start').getBoundingClientRect();
    return { capBottom: Math.round(c.bottom), capH: Math.round(c.height), capW: Math.round(c.width), btnTop: Math.round(bt.top), formW: document.getElementById('adv-form').clientWidth };
  });
  const ok = r.capBottom <= r.btnTop && r.capW <= r.formW;
  if (!ok) fails++;
  console.log(ok ? 'PASS' : 'FAIL', `${w}px`, JSON.stringify(r));
  await p.screenshot({ path: `${outDir}/captcha-${w}.png` });
  await ctx.close();
}
await b.close();
process.exit(fails ? 1 : 0);
