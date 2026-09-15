import playwrightTestPkg from '/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/.pnpm/@playwright+test@1.57.0/node_modules/@playwright/test/index.js';

const { chromium } = playwrightTestPkg;

const base = 'http://127.0.0.1:5199/qa/mission-control.html';
const outDir = '/Users/tiejunsun/github/agi-demos/artifacts/desktop-refactor';
const shots = [
  [1440, 1024, 'p2-mission-control-1440.png', base],
  [1100, 800, 'p2-mission-control-1100.png', base],
  [1440, 1024, 'p2-mission-control-mywork-1440.png', `${base}?view=my-work`],
];

const consoleIssues = [];
const browser = await chromium.launch();
for (const [width, height, name, url] of shots) {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on('console', (message) => {
    if (message.type() === 'error') consoleIssues.push(`[${name}] console.error: ${message.text()}`);
  });
  page.on('pageerror', (error) => consoleIssues.push(`[${name}] pageerror: ${error.message}`));
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  await page.screenshot({ path: `${outDir}/${name}` });
  console.log(
    `${name}: scrollWidth=${metrics.scrollWidth} clientWidth=${metrics.clientWidth} ` +
      `horizontalOverflow=${metrics.scrollWidth > metrics.clientWidth}`,
  );
  await page.close();
}
await browser.close();

if (consoleIssues.length > 0) {
  console.log('CONSOLE ISSUES:');
  for (const issue of consoleIssues) console.log(`  ${issue}`);
  process.exitCode = 1;
} else {
  console.log('CONSOLE CLEAN: no console.error or pageerror on either viewport');
}
