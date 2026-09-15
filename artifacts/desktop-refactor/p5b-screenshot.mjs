import playwrightTestPkg from '/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/.pnpm/@playwright+test@1.57.0/node_modules/@playwright/test/index.js';

const { chromium } = playwrightTestPkg;

const prefix = process.argv[2] ?? 'p5b';
const outDir = '/Users/tiejunsun/github/agi-demos/artifacts/desktop-refactor';
const base = 'http://127.0.0.1:5199/qa';
// [width, height, filename, url, extraWaitMs?]
const shots = [
  // Thread anatomy baseline vs oracle codex-06-thread-running-1440.png
  [1440, 1024, `${prefix}-conversation-1440.png`, `${base}/session-conversation.html`],
  [1100, 800, `${prefix}-conversation-1100.png`, `${base}/session-conversation.html`],
  // Full chat panel: composer + delivery switch + timeline
  [1440, 1024, `${prefix}-steering-1440.png`, `${base}/session-steering.html`],
  [1100, 800, `${prefix}-steering-1100.png`, `${base}/session-steering.html`],
  // HITL response cards, resolved state (slim rows) vs oracle
  // codex-04-approval-resolved-1440.png — the answered events land at 1800ms
  [1440, 1024, `${prefix}-hitl-1440.png`, `${base}/session-steering.html?hitl-response-events=1`, 2200],
  // Pending amber approval card vs oracle codex-03-inline-approval-1440.png
  [1440, 1024, `${prefix}-hitl-approval-1440.png`, `${base}/session-steering.html?hitl-approval=1`],
  // Compose-ahead queue + steering composer
  [1440, 1024, `${prefix}-compose-ahead-1440.png`, `${base}/compose-ahead.html`],
];

const consoleIssues = [];
const browser = await chromium.launch();
for (const [width, height, name, url, extraWait = 0] of shots) {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on('console', (message) => {
    if (message.type() === 'error') consoleIssues.push(`[${name}] console.error: ${message.text()}`);
  });
  page.on('pageerror', (error) => consoleIssues.push(`[${name}] pageerror: ${error.message}`));
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(900 + extraWait);
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
