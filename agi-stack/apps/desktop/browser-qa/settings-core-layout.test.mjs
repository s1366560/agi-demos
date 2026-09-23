import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import qa from './playwright.config.mjs';
const require = createRequire(import.meta.url),
  esbuild = createRequire(require.resolve('vite'))('esbuild');
const evidence = mkdtempSync(join(tmpdir(), 'settings-core-layout-'));
const source = `
import React from 'react';import {createRoot} from 'react-dom/client';import {Theme} from '@radix-ui/themes';import '@radix-ui/themes/styles.css';import './src/styles/global.css';import './src/features/settings/SettingsWindow.css';import './src/features/settings/SettingsForms.css';
import {I18nProvider} from './src/i18n';import {ThemePreferenceProvider} from './src/theme';import {GeneralSettingsPage,PreferenceSummaryPage,WorkspaceSettingsPage,AccountSettingsPage} from './src/features/settings/SettingsCorePages';import {AccountSessionSecurityPage} from './src/features/settings/AccountSessionSecurityPage';import {ProfileRoutePage} from './src/features/settings-routes/ProfileRoutePage';
const q=new URLSearchParams(location.search),view=q.get('view'),theme=q.get('theme'),authority=view==='local'?'local':'cloud';localStorage.setItem('agistack.desktop.theme',theme);localStorage.setItem('agistack.desktop.locale',q.get('locale')||'en');
window.__calls=[];window.__projects=[{id:'p',tenant_id:'t',name:'Research workspace',description:'A shared project with a readable description',member_ids:['1'],is_public:false},{id:'p2',tenant_id:'t',name:'Another project',description:'Another project'}];window.__MEMSTACK_DESKTOP__={getCapabilities:async()=>({webControlPlane:{availability:'available'}}),openWebControlPlane:async()=>window.__calls.push('control-plane')};
const user={id:'u',name:'Example User',email:'example@example.test',created_at:'2026-01-01',roles:['owner'],preferred_language:'en-US'},config={mode:authority,tenantId:'t',projectId:'p',workspaceId:'w',apiBaseUrl:'https://example.test'},auth={status:'signed_in',user,session:{auth_method:authority==='local'?'local':'password',trusted_device:true,expires_at:'2027-01-01'},tenants:[{id:'t',name:'Example organization',slug:'example',plan:'team'}],projects:window.__projects};
const model={authority,scope:{authority},state:authority==='local'?'degraded':'ready',reasonCode:authority==='local'?'local_profile_mutation_authority_unavailable':null,observation:{user,allowedActions:authority==='local'?['view']:['view','update','change-language','change-password']}},controller={update:async(_,input)=>{window.__calls.push(input);if(window.__fail)throw Error('unavailable')},changePassword:async(_,input)=>window.__calls.push(input)};
function App(){let page=view==='general'?<GeneralSettingsPage counts={{}} onOpenResource={()=>{}}/>:view==='appearance'||view==='notifications'?<PreferenceSummaryPage section={view}/>:view==='workspace'?<WorkspaceSettingsPage auth={auth} config={config} onContextChange={async(t,p)=>window.__calls.push(p)} onApplied={()=>{}}/>:view==='fallback'?<AccountSettingsPage auth={auth} tenant={auth.tenants[0]} config={config} onSignOut={()=>{}}/>:<><ProfileRoutePage model={model} controller={controller}/><AccountSessionSecurityPage auth={auth} config={config} onSignOut={()=>{}}/></>;return <I18nProvider><ThemePreferenceProvider><Theme appearance={theme}><div className="settings-window-dialog" style={{width:'100%',height:'100vh',display:'block'}}><div className="settings-window-content" style={{height:'100%',overflow:'auto'}}>{page}</div></div></Theme></ThemePreferenceProvider></I18nProvider>};createRoot(document.getElementById('root')).render(<App/>);`;
test('settings core layout and editable behavior across 56 theme locale viewport combinations', async () => {
  const result = await esbuild.build({
    stdin: {
      contents: source,
      resolveDir: new URL('..', import.meta.url).pathname,
      loader: 'tsx',
    },
    bundle: true,
    write: false,
    outfile: join(evidence, 'fixture.js'),
    platform: 'browser',
    format: 'iife',
    define: { 'process.env.NODE_ENV': '"production"' },
    plugins: [
      {
        name: 'authority-fixture',
        setup(b) {
          b.onResolve({ filter: /desktopRendererGenerationContextV2$/ }, () => ({
            path: 'generation',
            namespace: 'fixture',
          }));
          b.onResolve({ filter: /desktopWorkspaceContextAuthorityModuleV2$/ }, () => ({
            path: 'workspace',
            namespace: 'fixture',
          }));
          b.onLoad({ filter: /.*/, namespace: 'fixture' }, (a) => ({
            contents:
              a.path === 'generation'
                ? 'const actions={};export const useDesktopRendererGenerationV2=()=>({actions});'
                : 'export const withDesktopWorkspaceContextAuthorityOperationV2=async(a,c,run)=>run({listProjects:async()=>window.__projects});',
            loader: 'js',
          }));
        },
      },
    ],
  });
  const js = result.outputFiles.find((f) => f.path.endsWith('.js')).text,
    css = result.outputFiles.find((f) => f.path.endsWith('.css')).text,
    browser = await chromium.launch({
      headless: true,
      ...qa.use.launchOptions,
    });
  try {
    for (const width of [1100, 1440])
      for (const theme of ['dark', 'light'])
        for (const locale of ['en', 'zh-CN'])
          for (const view of [
            'local',
            'cloud',
            'fallback',
            'workspace',
            'general',
            'appearance',
            'notifications',
          ]) {
            const page = await browser.newPage({
                viewport: { width, height: 800 },
                reducedMotion: 'reduce',
              }),
              errors = [];
            page.on('pageerror', (e) => errors.push(e.message));
            await page.route('http://core.test/**', (r) =>
              r.fulfill({
                contentType: 'text/html',
                body: '<div id="root"></div>',
              }),
            );
            await page.goto('http://core.test/?' + new URLSearchParams({ view, theme, locale }));
            await page.addStyleTag({ content: css });
            await page.addScriptTag({ content: js });
            await page.locator('.settings-page').waitFor();
            assert.deepEqual(errors, []);
            assert.equal(await page.locator('h1').count(), 1);
            assert.equal(
              await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
              false,
              view + ' overflow',
            );
            if (view === 'cloud') {
              assert.equal(
                await page.locator('[data-action=change-language] small').innerText(),
                locale === 'zh-CN' ? '保存账户信息后，界面语言会随之更新。' : 'The interface language changes when you save your profile.',
              );
            }
            if (view === 'local') {
              assert.equal(await page.locator('input[type=password]').count(), 0);
              assert.equal(await page.locator('[data-action=update]').count(), 0);
            }
            if (width === 1100 && theme === 'dark' && locale === 'en') {
              await page.screenshot({
                path: join(evidence, view + '.png'),
                fullPage: true,
              });
              if (view === 'cloud') {
                await page.locator('[data-action=update] input').fill('Changed Name');
                await page.locator('[data-action=update] button[type=submit]').click();
                assert.equal((await page.evaluate(() => window.__calls))[0].name, 'Changed Name');
                await page.evaluate(() => {
                  window.__fail = true;
                });
                await page.locator('[data-action=update] button[type=submit]').click();
                await page.getByRole('alert').waitFor();
                await page.locator('.settings-profile-password summary').click();
                await page.locator('[data-action=change-password] button[type=submit]').click();
                await page.locator('[data-action=change-password] [role=alert]').waitFor();
                const inputs = page.locator('[data-action=change-password] input');
                await inputs.nth(0).fill('old-password');
                await inputs.nth(1).fill('new-password');
                await inputs.nth(2).fill('new-password');
                await page.locator('[data-action=change-password] button[type=submit]').click();
                assert.equal(
                  (await page.evaluate(() => window.__calls)).at(-1).newPassword,
                  'new-password',
                );
              }
              if (view === 'workspace') {
                await page.getByRole('button', { name: /Another project/ }).click();
                await page.locator('.settings-context-apply button').click();
                assert.ok((await page.evaluate(() => window.__calls)).includes('p2'));
              }
              if (view === 'appearance' || view === 'general') {
                const group = page.getByRole('radiogroup').first();
                await group.locator('[aria-checked=true]').focus();
                await page.keyboard.press('ArrowRight');
                assert.equal(
                  await group
                    .locator('[aria-checked=true]')
                    .evaluate((el) => el === document.activeElement),
                  true,
                );
                assert.equal(await group.locator('[tabindex="0"]').count(), 1);
              }
              if (view === 'notifications') {
                const toggles = page.getByRole('switch');
                assert.ok(await toggles.nth(0).getAttribute('aria-label'));
                await toggles.nth(1).click();
                await page.locator('input[type=time]').first().fill('21:30');
                assert.equal(await page.locator('input[type=time]').first().inputValue(), '21:30');
                const group = page.getByRole('radiogroup').first();
                await group.locator('[aria-checked=true]').focus();
                await page.keyboard.press('End');
                assert.equal(
                  await group.locator('[role=radio]').last().getAttribute('aria-checked'),
                  'true',
                );
              }
            }
            await page.close();
          }
  } finally {
    await browser.close();
  }
  console.log('56 combinations passed; evidence ' + evidence);
});
