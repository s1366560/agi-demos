import playwrightTestPkg from '/Users/tiejunsun/github/agi-demos/agi-stack/apps/desktop/node_modules/.pnpm/@playwright+test@1.57.0/node_modules/@playwright/test/index.js';

const { chromium } = playwrightTestPkg;

const prefix = process.argv[2] ?? 'p6';
const outDir = '/Users/tiejunsun/github/agi-demos/artifacts/desktop-refactor';
const base = 'http://127.0.0.1:5199/qa';
// [width, height, filename, url, action?]
const shots = [
  // Plain login screen vs oracle login-screen.png (device dialog dismissed)
  [1440, 1024, `${prefix}-login-1440.png`, `${base}/login-sso.html`, 'close-device-dialog'],
  [1100, 800, `${prefix}-login-1100.png`, `${base}/login-sso.html`, 'close-device-dialog'],
  // Device-auth dialog, waiting state (10:00 countdown)
  [1440, 1024, `${prefix}-login-sso-1440.png`, `${base}/login-sso.html`],
  // Device-auth dialog, expired state
  [1440, 1024, `${prefix}-login-sso-expired-1440.png`, `${base}/login-sso.html?state=expired`],
  // Force password change regression
  [1440, 1024, `${prefix}-force-password-change-1440.png`, `${base}/force-password-change.html`],
  // Settings window: models (provider workspace) vs model-provider-overview.png
  // (mode=cloud routes through the mocked fetch; local needs a sidecar capability)
  [1440, 1024, `${prefix}-settings-models-1440.png`, `${base}/provider-settings.html?mode=cloud&section=models`],
  [1100, 800, `${prefix}-settings-models-1100.png`, `${base}/provider-settings.html?mode=cloud&section=models`],
  // Settings window: skills (managed resource workspace) vs manage-skills.png
  [1440, 1024, `${prefix}-settings-skills-1440.png`, `${base}/provider-settings.html?mode=cloud&section=skills`],
  // Settings window: account vs settings-popup-account.png
  [1440, 1024, `${prefix}-settings-account-1440.png`, `${base}/provider-settings.html?mode=cloud&section=account`],
  // Settings window: workspace context + workspace create regression
  [1440, 1024, `${prefix}-workspace-settings-1440.png`, `${base}/workspace-settings.html`],
  [1440, 1024, `${prefix}-workspace-create-1440.png`, `${base}/workspace-create.html`],
];

const consoleIssues = [];
const browser = await chromium.launch();
for (const [width, height, name, url, action] of shots) {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on('console', (message) => {
    if (message.type() === 'error') consoleIssues.push(`[${name}] console.error: ${message.text()}`);
  });
  page.on('pageerror', (error) => consoleIssues.push(`[${name}] pageerror: ${error.message}`));
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(900);
  if (action === 'close-device-dialog') {
    await page.click('.desktop-device-auth-close');
    await page.waitForTimeout(200);
  }
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
