import { chromium } from 'playwright';
const b = await chromium.launch({ channel: 'chrome' });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
await p.goto('http://localhost:4399/', { waitUntil: 'networkidle' });
await p.click('[data-base="tienda"]'); await p.click('[data-hosting="vps-basico"]');
const [pop] = await Promise.all([ctx.waitForEvent('page'), p.click('#btn-send')]);
console.log(decodeURIComponent(pop.url()).slice(0, 700));
await b.close();
