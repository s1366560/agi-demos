import { createRequire } from 'node:module';
const require = createRequire('/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/@playwright/test/index.js');
const { chromium } = require('/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/@playwright/test/index.js');

const [,, url, out, mode] = process.argv;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1325, height: 1750 } });
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
await page.waitForTimeout(2500);
await page.screenshot({ path: out });
await browser.close();
console.log('saved', out);
