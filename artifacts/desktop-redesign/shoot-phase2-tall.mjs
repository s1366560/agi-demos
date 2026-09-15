import { createRequire } from 'node:module';
const require = createRequire('/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/@playwright/test/index.js');
const { chromium } = require('/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/@playwright/test/index.js');

// usage: node shoot-phase2-tall.mjs <url> <out> [light] [scrollY] [height]
const [,, url, out, mode, scrollY = '0', height = '3200'] = process.argv;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1325, height: Number(height) } });
await page.goto(url, { waitUntil: 'networkidle' });
if (mode === 'light') {
  await page.evaluate(() => {
    document.documentElement.dataset.theme = 'light';
    const radix = document.querySelector('.radix-themes');
    if (radix) { radix.classList.remove('dark'); radix.classList.add('light'); }
    for (const el of [document.documentElement, document.body, document.getElementById('root')]) {
      if (el) el.style.background = '#ffffff';
    }
  });
}
await page.waitForTimeout(2000);
const y = Number(scrollY);
if (y > 0) {
  await page.evaluate((scroll) => {
    const candidates = [...document.querySelectorAll('div')].filter(
      (el) => el.scrollHeight > el.clientHeight + 100 && el.clientHeight > 300,
    );
    for (const el of candidates) el.scrollTop = scroll;
    window.scrollTo(0, scroll);
  }, y);
  await page.waitForTimeout(600);
}
await page.screenshot({ path: out });
await browser.close();
console.log('saved', out);
