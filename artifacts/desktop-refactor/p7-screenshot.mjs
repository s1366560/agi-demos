import playwrightTestPkg from '/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/.pnpm/@playwright+test@1.57.0/node_modules/@playwright/test/index.js';

const { chromium } = playwrightTestPkg;

const prefix = process.argv[2] ?? 'p7';
const outDir = '/Users/tiejunsun/github/agi-demos/artifacts/desktop-refactor';
const base = 'http://127.0.0.1:5199/qa';
// [width, height, filename, url]
const shots = [
  // Plan review card (draft) vs codex-05-plan-card-1440.png
  [1440, 1024, `${prefix}-plan-review-1440.png`, `${base}/session-plan-review.html`],
  [1100, 800, `${prefix}-plan-review-1100.png`, `${base}/session-plan-review.html`],
  // Plan review card (approved state)
  [1440, 1024, `${prefix}-plan-review-approved-1440.png`, `${base}/session-plan-review.html?state=approved`],
  // Evidence canvas: tab bar with count badges (sources view / checks view)
  [1440, 1024, `${prefix}-evidence-1440.png`, `${base}/session-evidence.html`],
  [1440, 1024, `${prefix}-evidence-checks-1440.png`, `${base}/session-evidence.html?view=checks`],
  [1100, 800, `${prefix}-evidence-1100.png`, `${base}/session-evidence.html`],
  // Artifact preview panel
  [1440, 1024, `${prefix}-artifact-preview-1440.png`, `${base}/artifact-preview.html`],
  [1100, 800, `${prefix}-artifact-preview-1100.png`, `${base}/artifact-preview.html`],
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
  await page.waitForTimeout(900);
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
  console.log('CONSOLE CLEAN: no console.error or pageerror on any viewport');
}
