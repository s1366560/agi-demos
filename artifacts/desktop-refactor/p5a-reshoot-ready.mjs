import playwrightTestPkg from '/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/.pnpm/@playwright+test@1.57.0/node_modules/@playwright/test/index.js';

const { chromium } = playwrightTestPkg;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1024 } });
const issues = [];
page.on('console', (m) => { if (m.type() === 'error') issues.push(m.text()); });
page.on('pageerror', (e) => issues.push(e.message));
await page.goto('http://127.0.0.1:5199/qa/session-recovery.html?rail=1&status=ready_review', { waitUntil: 'networkidle' });
await page.waitForTimeout(600);
await page.screenshot({ path: '/Users/tiejunsun/github/agi-demos/artifacts/desktop-refactor/p5a-session-ready-review-1440.png' });
await browser.close();
console.log(issues.length ? `ISSUES: ${issues.join('; ')}` : 'CONSOLE CLEAN');
