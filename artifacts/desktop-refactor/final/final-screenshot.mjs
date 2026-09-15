import playwrightTestPkg from '/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/.pnpm/@playwright+test@1.57.0/node_modules/@playwright/test/index.js';

const { chromium } = playwrightTestPkg;

const outDir = '/Users/tiejunsun/github/agi-demos/artifacts/desktop-refactor/final';
const base = 'http://127.0.0.1:5199/qa';
const fixtures = [
  'mission-control',
  'session-conversation',
  'login-sso',
  'new-task-flow',
  'provider-settings',
  'session-plan-review',
  'session-evidence',
  'search',
  'automations',
  'workspace-collaboration',
];

const consoleIssues = [];
const overflowIssues = [];
const browser = await chromium.launch();
for (const fixture of fixtures) {
  const name = `final-${fixture}-1440.png`;
  const url = `${base}/${fixture}.html`;
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 }, colorScheme: 'dark' });
  page.on('console', (message) => {
    if (message.type() === 'error') consoleIssues.push(`[${fixture}] console.error: ${message.text()}`);
  });
  page.on('pageerror', (error) => consoleIssues.push(`[${fixture}] pageerror: ${error.message}`));
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(900);
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bg: getComputedStyle(document.body).backgroundColor,
  }));
  if (metrics.scrollWidth !== metrics.clientWidth) {
    overflowIssues.push(
      `[${fixture}] horizontal overflow: scrollWidth=${metrics.scrollWidth} clientWidth=${metrics.clientWidth}`,
    );
  }
  await page.screenshot({ path: `${outDir}/${name}` });
  console.log(
    `${fixture}: scrollWidth=${metrics.scrollWidth} clientWidth=${metrics.clientWidth} ` +
      `overflow=${metrics.scrollWidth > metrics.clientWidth} bg=${metrics.bg}`,
  );
  await page.close();
}
await browser.close();

if (consoleIssues.length > 0) {
  console.log('CONSOLE ISSUES:');
  for (const issue of consoleIssues) console.log(`  ${issue}`);
} else {
  console.log('CONSOLE CLEAN: no console.error or pageerror on any fixture');
}
if (overflowIssues.length > 0) {
  console.log('OVERFLOW ISSUES:');
  for (const issue of overflowIssues) console.log(`  ${issue}`);
} else {
  console.log('OVERFLOW CLEAN: scrollWidth === clientWidth on all fixtures');
}
if (consoleIssues.length > 0 || overflowIssues.length > 0) process.exitCode = 1;
