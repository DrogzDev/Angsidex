// Uso: node tools/sec.mjs <outDir> <url> <ancho> <id,id,..>  → captura cada sección con scroll previo
import { chromium } from 'playwright';
const [out, url, w, ids] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome' });
const p = await b.newPage({ viewport: { width: +w, height: 900 } });
await p.goto(url, { waitUntil: 'networkidle' });
for (const id of ids.split(',')) {
  await p.evaluate((id) => document.getElementById(id).scrollIntoView({ behavior: 'instant' }), id);
  await p.waitForTimeout(1200);
  if (id === 'calculadora') { await p.click('[data-base="tienda"]'); await p.click('[data-tab="admin"]'); await p.click('[data-module="inventario"]'); await p.click('[data-hosting="vps-basico"]'); await p.waitForTimeout(400); }
  await p.locator('#' + id).screenshot({ path: `${out}/${w}-${id}.png` });
}
await b.close();
