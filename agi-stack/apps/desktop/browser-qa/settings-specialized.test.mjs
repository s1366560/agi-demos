import assert from 'node:assert/strict';
import { before, after, test } from 'node:test';
import { createRequire } from 'node:module';
import { readFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import qaConfig from './playwright.config.mjs';
const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const evidence = mkdtempSync(join(tmpdir(), 'codex-settings-specialized-'));
const styles = [
  readFileSync(require.resolve('@radix-ui/themes/styles.css'), 'utf8'),
  ...[
    'styles/tokens.css',
    'styles/base.css',
    'features/settings/SettingsWindow.css',
    'features/settings/SettingsCorePages.css',
    'features/settings/PluginManagementDialogs.css',
    'features/navigation/KeyboardShortcutsDialog.css',
    ...[
      'BrowserIntegrationSettingsPage',
      'ShortcutSettingsPage',
      'UpdateSettingsPage',
      'ChannelConnectionsDialog',
    ].map((n) => `features/settings/${n}.css`),
  ].map((p) => readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8')),
].join('\n');
const script = await esbuild.build({
  stdin: {
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'tsx',
    contents: `
import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
import {Theme} from '@radix-ui/themes';import {I18nProvider} from './src/i18n';
import {BrowserIntegrationSettingsPage} from './src/features/settings/BrowserIntegrationSettingsPage';
import {ShortcutSettingsPage} from './src/features/settings/ShortcutSettingsPage';
import {UpdateSettingsPage} from './src/features/settings/UpdateSettingsPage';
import {ChannelConnectionsDialog} from './src/features/settings/ChannelConnectionsDialog';
const noop=()=>{};window.calls=[];const config={mode:'local'};
let enabled=true;const runtime=()=>({config:{browser_bridge:{enabled,full_cdp_access_enabled:false}}});
const bridge={loadSnapshot:async()=>({runtimeStatus:runtime(),bridgeStatus:{enabled,port:1234,brokerConnected:true}}),setEnabled:async value=>{enabled=value;window.calls.push('toggle');return runtime()},setFullCdpEnabled:async()=>runtime(),install:async()=>{window.calls.push('install');return {installed:[{browser:'Chrome',manifestPath:'/fixture/native.json'}],skipped:[]}},uninstall:async()=>({removed:['Chrome']})};
const integration={listBrowserOriginGrants:async()=>[{id:'g1',host:'example.test',decision:'all',created_at:'2026-09-22'}],listBrowserCapabilityGrants:async()=>[],listBrowserSiteCredentials:async()=>[],listBrowserAuditEntries:async()=>[],revokeBrowserOriginGrant:async()=>window.calls.push('revoke'),upsertBrowserSiteCredential:async()=>window.calls.push('credential')};
let updateState={schemaVersion:2,phase:'idle',currentVersion:'1.0',candidateVersion:null,recoveryVersion:null,progress:null,reasonCode:null,retryable:false,allowedActions:['check']};let subscriber=noop;
window.__MEMSTACK_DESKTOP__={updates:{subscribe:fn=>{subscriber=fn;return noop},getState:async()=>updateState,check:async()=>{window.calls.push('check');return {...updateState,phase:'downloaded',candidateVersion:'1.1',allowedActions:['restart_to_apply']}},restartToApply:async()=>{window.calls.push('restart');return {...updateState,phase:'applying',allowedActions:[]}}}};
window.updateFailure=()=>subscriber({...updateState,phase:'failed',reasonCode:'update_operation_failed'});
const schema={channel_type:'slack',config_schema:{type:'object',required:['bot_token'],properties:{bot_token:{type:'string',title:'Bot token'}}},config_ui_hints:{bot_token:{sensitive:true}},secret_paths:['bot_token'],defaults:{}};
function Channels(){const [editor,setEditor]=useState(null);return <ChannelConnectionsDialog management={{open:true,close:()=>window.calls.push('close'),busyId:null,loading:false,error:null,notice:null,catalog:[{channel_type:'slack',enabled:true,discovered:true}],configs:[{id:'one',name:'Incident room',channel_type:'slack',enabled:true,status:'connected'}],editor,openCreate:()=>setEditor({key:'create',schema,config:null,loading:false}),openEdit:()=>setEditor({key:'edit',schema,config:{id:'one',name:'Incident room',channel_type:'slack',enabled:true,extra_settings:{}},loading:false}),closeEditor:()=>setEditor(null),changeType:noop,save:async draft=>{window.calls.push(draft);setEditor(null)},toggle:()=>window.calls.push('toggle-channel'),test:()=>window.calls.push('test-channel'),remove:()=>window.calls.push('delete-channel'),reload:noop}}/>}
const root=createRoot(document.getElementById('root'));
window.renderSettings=(section,theme)=>root.render(<Theme appearance={theme} accentColor="gray"><I18nProvider><div className="fixture" key={section}>{section==='browser'?<BrowserIntegrationSettingsPage config={config} browserIntegrationClientV2={integration} browserBridgeManagementClientV2={bridge}/>:section==='shortcuts'?<ShortcutSettingsPage platform="mac"/>:section==='updates'?<UpdateSettingsPage/>:<Channels/>}</div></I18nProvider></Theme>);
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
  browser = await chromium.launch({ headless: true, ...qaConfig.use.launchOptions });
});
after(async () => {
  await browser?.close();
  console.log(`Settings specialized evidence: ${evidence}`);
});
async function fixture(section, theme = 'light', locale = 'en-US', width = 1100, height = 800) {
  const page = await browser.newPage({ viewport: { width, height }, reducedMotion: 'reduce' });
  await page.route('http://settings.test/**', (route) =>
    route.fulfill({ contentType: 'text/html', body: '<div></div>' }),
  );
  await page.goto('http://settings.test');
  await page.evaluate((locale) => localStorage.setItem('agistack.desktop.locale', locale), locale);
  await page.setContent(
    `<html data-theme="${theme}"><head><style>${styles}.fixture{max-width:780px;margin:0 auto;padding:28px;box-sizing:border-box}body{margin:0}.settings-page{min-width:0}</style></head><body><div id="root"></div></body></html>`,
  );
  await page.addScriptTag({ content: script.outputFiles[0].text });
  await page.evaluate(({ section, theme }) => window.renderSettings(section, theme), {
    section,
    theme,
  });
  await page.locator(section === 'channels' ? '[role="dialog"]' : '.settings-page').waitFor();
  return page;
}
test('browser settings preserve named permission switches and labeled credential save', async () => {
  const page = await fixture('browser');
  await page.getByRole('switch').first().click();
  await page.waitForFunction(() => window.calls.includes('toggle'));
  assert.equal(await page.getByRole('switch').first().getAttribute('aria-checked'), 'false');
  assert.ok(await page.getByRole('switch').nth(1).getAttribute('aria-label'));
  await page.locator('.settings-browser-actions button').first().click();
  await page.waitForFunction(() => window.calls.includes('install'));
  await page.getByLabel('Origin', { exact: true }).fill('https://example.test');
  await page.getByLabel('Username', { exact: true }).fill('fixture-user');
  await page.getByLabel('Password', { exact: true }).fill('fixture-only');
  await page.locator('.settings-browser-credential-form button').click();
  await page.waitForFunction(() => window.calls.includes('credential'));
  assert.equal(await page.getByLabel('Password', { exact: true }).inputValue(), '');
  await page.close();
});
test('shortcut search filters and captures key combinations with clear action', async () => {
  const page = await fixture('shortcuts');
  const search = page.getByRole('textbox');
  await search.fill('no-such-shortcut');
  await page.getByRole('status').waitFor();
  await search.fill('');
  await search.press('Meta+k');
  await page.locator('.settings-shortcuts-combo-chip').waitFor();
  await page.locator('.settings-shortcuts-combo-chip button').click();
  assert.equal(await page.locator('.settings-shortcuts-combo-chip').count(), 0);
  assert.ok((await page.locator('.shortcuts-row').count()) > 0);
  await page.close();
});
test('updates preserve allowed actions, failure alert and restart', async () => {
  const page = await fixture('updates');
  await page.getByRole('button', { name: 'Check for updates' }).click();
  await page.waitForFunction(() => window.calls.includes('check'));
  assert.match(await page.locator('.settings-update-versions').innerText(), /1.1/);
  await page.locator('.settings-update-card footer button').click();
  await page.waitForFunction(() => window.calls.includes('restart'));
  await page.evaluate(() => window.updateFailure());
  await page.getByRole('alert').waitFor();
  await page.close();
});
test('channel validation focuses invalid field and editing preserves unchanged secrets', async () => {
  const page = await fixture('channels');
  await page.locator('.channel-connections-toolbar button').click();
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.getAttribute('aria-invalid') === 'true');
  await page.getByLabel('Connection name', { exact: false }).fill('New connection');
  await page.getByLabel('Bot token', { exact: false }).fill('fixture-secret');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForFunction(() => window.calls.some((x) => x?.name === 'New connection'));
  await page.getByRole('button', { name: 'Edit Incident room' }).click();
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.waitForFunction(() => window.calls.some((x) => x?.name === 'Incident room'));
  const saved = await page.evaluate(() => window.calls.find((x) => x?.name === 'Incident room'));
  assert.equal(saved.extra_settings?.bot_token, undefined);
  await page.close();
});
for (const [width, height] of [
  [1100, 800],
  [1440, 1024],
])
  for (const theme of ['light', 'dark'])
    for (const locale of ['en-US', 'zh-CN'])
      test(`settings geometry ${width} ${theme} ${locale}`, async () => {
        const page = await fixture('browser', theme, locale, width, height);
        for (const section of ['browser', 'shortcuts', 'updates', 'channels']) {
          await page.evaluate(({ section, theme }) => window.renderSettings(section, theme), {
            section,
            theme,
          });
          await page
            .locator(section === 'channels' ? '[role="dialog"]' : '.settings-page')
            .waitFor();
          assert.equal(
            await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
            false,
            section,
          );
          assert.doesNotMatch(
            await page.locator('body').innerText(),
            /settings\.(browser|channels|shortcuts|updates)/,
          );
          if (width === 1100 && locale === 'en-US')
            await page.screenshot({
              path: join(evidence, `${section}-${theme}.png`),
              fullPage: true,
            });
        }
        await page.screenshot({ path: join(evidence, `${width}-${theme}-${locale}.png`) });
        await page.close();
      });
