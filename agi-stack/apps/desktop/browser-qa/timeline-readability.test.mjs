import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import qaConfig from './playwright.config.mjs';
const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const evidence = mkdtempSync(join(tmpdir(), 'codex-timeline-readability-'));
const measurements = [];
const styles = [
  readFileSync(require.resolve('@radix-ui/themes/styles.css'), 'utf8'),
  ...[
    'styles/tokens.css',
    'styles/base.css',
    'features/chat/ChatTimeline.css',
    'features/chat/ChatPanel.css',
    'features/session/TimelineStepDetails.css',
  ].map((path) =>
    readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8'),
  ),
].join('\n');
const script = await esbuild.build({
  stdin: {
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'tsx',
    contents: `
import React from 'react';
import {createRoot} from 'react-dom/client';
import {Theme} from '@radix-ui/themes';
import {ToastProvider} from './src/features/feedback/ToastCenter';
import {I18nProvider} from './src/i18n';
import {AgentTimeline} from './src/features/chat/ChatTimeline';
import {TimelineInspectionProvider,useTimelineInspection} from './src/features/session/TimelineInspectionContext';
import {TimelineStepDetails} from './src/features/session/TimelineStepDetails';
const noop=()=>{};
const base=(id,type,n,extra={})=>({id,type,eventTimeUs:(Date.now()-10000+n*1000)*1000,eventCounter:n,timestamp:Date.now()-10000+n*1000,...extra});
const items=[base('user','user_message',1,{role:'user',content:'Review workspace'}),
base('call','act',2,{toolName:'read',toolInput:{path:'src/main.ts',nested:{fixtureInput:'INPUT_ONLY'}},payload:{tool_call_id:'one'}}),
base('result','observe',3,{toolName:'read',toolOutput:{nested:{fixtureRaw:'RAW_JSON_ONLY',long:'x'.repeat(1500)}},payload:{tool_call_id:'one'},display:{summary:'Read workspace source'}}),
base('answer','assistant_message',4,{role:'assistant',content:'Source reviewed.'}),
base('error','error',5,{error:'Internal diagnostic failure',content:'Internal diagnostic failure',payload:{error_code:'runtime_conflict'}}),
base('running','act',6,{toolName:'grep',toolInput:{pattern:'TODO'},payload:{tool_call_id:'two'},display:{summary:'Search remaining tasks'}})];
function Fixture({updated}){const selection=useTimelineInspection();return <div className="fixture"><main className="chat-shell"><AgentTimeline imagePreviewClient={null} state={{items:updated?[...items,base('thought','thought',7,{content:'Continue review'})]:items,approvalRequests:[],loading:false,loadingEarlier:false,hasMore:false,error:null}} expandedItems={{}} onToggleItem={noop} onLoadEarlier={noop} onShowEarlier={noop} earlierRenderAllowance={0} onRetry={noop} onRespondToHitl={async()=>{}} respondableHitlRequestIds={[]} activityPresence="live"/></main>{selection.items.length>0&&<aside><TimelineStepDetails items={selection.items} onClose={selection.dismiss}/></aside>}</div>}
const root=createRoot(document.getElementById('root'));
window.renderTimeline=(theme,updated=false)=>root.render(<Theme appearance={theme} accentColor="gray"><I18nProvider><ToastProvider><TimelineInspectionProvider sessionKey="fixture" onOpen={noop}><Fixture updated={updated}/></TimelineInspectionProvider></ToastProvider></I18nProvider></Theme>);
`,
  },
  bundle: true,
  write: false,
  platform: 'browser',
  format: 'iife',
  loader: { '.css': 'empty', '.svg': 'text' },
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.PROD': 'true' },
});
let browser;
before(async () => {
  browser = await chromium.launch({
    headless: true,
    ...qaConfig.use.launchOptions,
  });
});
after(async () => {
  await browser?.close();
  writeFileSync(
    join(evidence, 'measurements.json'),
    JSON.stringify(measurements, null, 2),
  );
  console.log(`Timeline readability evidence: ${evidence}`);
});
for (const [width, height] of [
  [1100, 800],
  [1440, 1024],
])
  for (const theme of ['light', 'dark'])
    for (const locale of ['en-US', 'zh-CN']) {
      test(`actual timeline readability: ${width}-${theme}-${locale}`, async () => {
        const page = await browser.newPage({
          viewport: { width, height },
          colorScheme: theme,
          reducedMotion: 'reduce',
        });
        page.on('pageerror', (error) =>
          console.log('Fixture error:', error.message),
        );
        try {
          await page.route('http://timeline.test/', (route) =>
            route.fulfill({ contentType: 'text/html', body: '<div></div>' }),
          );
          await page.goto('http://timeline.test/');
          await page.evaluate(
            (locale) => localStorage.setItem('agistack.desktop.locale', locale),
            locale,
          );
          await page.setContent(
            `<html data-theme="${theme}"><head><style>${styles}.fixture{display:flex;width:100%;height:100vh;min-width:0}.fixture main{display:block;flex:1;min-width:0;overflow:auto;padding:24px}.fixture main>div{max-width:800px;margin-inline:auto}.fixture aside{width:340px;min-width:0;flex-shrink:0;border-left:1px solid var(--desktop-border)}</style></head><body><div id="root"></div></body></html>`,
          );
          await page.addScriptTag({ content: script.outputFiles[0].text });
          await page.evaluate((theme) => window.renderTimeline(theme), theme);
          const completed = page.locator(
              '.timeline-tool-group.status-complete',
            ),
            running = page.locator('.timeline-tool-group.status-running');
          await running.waitFor({ timeout: 5000 });
          assert.equal(await completed.getAttribute('open'), null);
          assert.notEqual(await running.getAttribute('open'), null);
          assert.doesNotMatch(
            await page.locator('main').innerText(),
            /RAW_JSON_ONLY|INPUT_ONLY/,
          );
          assert.ok(
            await page.locator('.timeline-notice.is-error').isVisible(),
          );
          assert.match(
            await completed.locator('summary').innerText(),
            locale === 'zh-CN' ? /完成/ : /Completed/,
          );
          await completed.locator('summary').click();
          await page.evaluate(
            (theme) => window.renderTimeline(theme, true),
            theme,
          );
          assert.notEqual(await completed.getAttribute('open'), null);
          const trigger = completed.locator('.timeline-step-button');
          await trigger.click();
          const details = page.locator('.timeline-step-details');
          await details.waitFor();
          await page.locator('#timeline-detail-tab-input').click();
          assert.match(await details.innerText(), /INPUT_ONLY/);
          await page.locator('#timeline-detail-tab-output').click();
          assert.match(await details.innerText(), /RAW_JSON_ONLY/);
          const metrics = await page.evaluate(() => ({
            documentWidth: document.documentElement.scrollWidth,
            mainWidth: document.querySelector('main').clientWidth,
            mainScroll: document.querySelector('main').scrollWidth,
            detailWidth: document.querySelector('aside').clientWidth,
            detailScroll: document.querySelector('aside').scrollWidth,
          }));
          assert.ok(metrics.documentWidth <= width, JSON.stringify(metrics));
          assert.ok(
            metrics.mainScroll <= metrics.mainWidth,
            JSON.stringify(metrics),
          );
          assert.ok(
            metrics.detailScroll <= metrics.detailWidth,
            JSON.stringify(metrics),
          );
          measurements.push({ width, height, theme, locale, ...metrics });
          await page.screenshot({
            path: join(evidence, `${width}-${theme}-${locale}.png`),
            fullPage: true,
          });
          await page.keyboard.press('Escape');
          await details.waitFor({ state: 'detached' });
          await page.waitForFunction(() =>
            document.activeElement?.classList.contains('timeline-step-button'),
          );
          assert.equal(
            await trigger.evaluate((el) => el === document.activeElement),
            true,
          );
        } finally {
          await page.close();
        }
      });
    }
