import { createRequire } from 'node:module';
const require = createRequire('/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/@playwright/test/index.js');
const { chromium } = require('/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/@playwright/test/index.js');

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1325, height: 1100 } });
await page.goto('http://127.0.0.1:5199/qa/aggregated-sources.html', { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
// Expand the first tool-call row to reveal the input/output detail blocks.
await page.locator('.timeline-tool-group-items .tool-call .timeline-row-toggle').first().click();
await page.waitForTimeout(400);
await page.screenshot({ path: process.argv[2] });
await browser.close();
console.log('saved', process.argv[2]);
