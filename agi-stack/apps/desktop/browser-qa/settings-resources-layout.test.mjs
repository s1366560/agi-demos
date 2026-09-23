import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import qaConfig from './playwright.config.mjs';
const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const evidence=mkdtempSync(join(tmpdir(),'settings-resources-'));
const bundle=await esbuild.build({entryPoints:[new URL('./settings-resources.fixture.tsx',import.meta.url).pathname],bundle:true,write:false,outfile:join(evidence,'fixture.js'),platform:'browser',format:'iife',define:{'process.env.NODE_ENV':'"production"'}});
const script=bundle.outputFiles.find(f=>f.path.endsWith('.js')).text, css=bundle.outputFiles.find(f=>f.path.endsWith('.css')).text;
const scenes=['provider','agent','subagent','skill','mcp','local-plugins','plugin-local','plugin-marketplace','plugin-install','plugin-uninstall','skill-import','skill-versions','skill-evolution','subagent-library'];
test('resource settings render usable forms and details across narrow/wide light/dark layouts',async()=>{
const browser=await chromium.launch({headless:true,...qaConfig.use.launchOptions});
try {for(const width of [640,1100])for(const theme of ['light','dark'])for(const scene of scenes){
const page=await browser.newPage({viewport:{width,height:800},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>{errors.push(e.message);console.log(scene,e.message)});
await page.route('https://settings.test/**',route=>route.fulfill({contentType:'text/html',body:'<div id="root"></div>'}));
await page.route('https://example.com/**',route=>route.fulfill({json:{trust_configured:true,installations:[{reference:{bundle_id:'workspace-tools',version:'1.0',digest:'a'.repeat(64),source:'local-file://workspace-tools/1.0'},scope:{kind:'project',tenant_id:'tenant-1',project_id:'project-1'},enabled:true,authorization_status:'approved',activation_status:'active',activation_error:null,approved_permissions:['workspace.read']}]}}));
await page.goto(`https://settings.test/?scene=${scene}&theme=${theme}`);await page.evaluate(t=>{document.documentElement.dataset.theme=t;},theme);await page.addStyleTag({content:css});await page.addScriptTag({content:script});
await page.locator(scene==='local-plugins'?'.local-plugin-list article':scene==='provider'?'.provider-identity':scene.startsWith('plugin-')&&!['plugin-install','plugin-uninstall'].includes(scene)?'.managed-resource-identity':'[role=dialog]').waitFor();
assert.deepEqual(errors,[],`${scene} render errors`);
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${scene} ${width} ${theme} viewport overflow`);
const overflow=await page.locator('[role=dialog],.provider-detail,.managed-resource-detail').evaluateAll(els=>els.filter(el=>el.scrollWidth>el.clientWidth+2).map(el=>el.className));assert.deepEqual(overflow,[],`${scene} ${width} detail overflow`);
if(scene==='provider'){
 for(const tab of ['Connection','Models','Routing','Usage']){await page.getByRole('tab',{name:tab,exact:true}).click();await page.screenshot({path:join(evidence,`${scene}-${tab}-${width}-${theme}.png`)});assert.deepEqual(errors,[],`${scene} ${tab}`);}
 await page.getByRole('tab',{name:'Connection',exact:true}).click();
 assert.equal(await page.locator('.provider-tabs button.active').evaluate(el=>getComputedStyle(el).color),await page.locator('.model-provider-workspace').evaluate(el=>getComputedStyle(el).color));
 const edit=page.getByRole('button',{name:'Edit',exact:true});if(await edit.count())await edit.click();
 await page.getByRole('button',{name:'Add provider',exact:true}).first().click();await page.getByRole('dialog').waitFor();
 await page.locator('.provider-option-grid button').first().waitFor();await page.locator('.provider-wizard footer .primary').click();
 await page.locator('.provider-wizard input[type=password]').fill('fixture-key');await page.locator('.provider-wizard-test').click();
 await page.screenshot({path:join(evidence,`provider-connect-${width}-${theme}.png`)});
 await page.locator('.provider-wizard footer .primary').click();await page.locator('.provider-wizard input').first().fill('model-one');
 assert.equal(await page.locator('.provider-wizard footer .primary').isEnabled(),true);
}
if(['agent','subagent','skill'].includes(scene)){
 const tabs=page.locator('.agent-definition-dialog-tabs button');
 for(let index=0;index<await tabs.count();index++){await tabs.nth(index).click();assert.equal(await page.locator('.agent-definition-dialog-body').evaluate(el=>el.scrollWidth>el.clientWidth+2),false,`${scene} tab ${index}`);await page.screenshot({path:join(evidence,`${scene}-tab${index}-${width}-${theme}.png`)});}
 const save=page.locator('.agent-definition-dialog-footer .primary');await save.click();
 assert.equal(await tabs.first().getAttribute('aria-pressed'),'true',`${scene} invalid save reveals required identity fields`);
}
if(scene==='skill-versions'){await page.locator('.skill-version-action button').last().click();await page.locator('.skill-version-confirmation').waitFor();}
if(scene==='skill-evolution'){await page.locator('.skill-evolution-entry-actions button.apply').click();await page.locator('.skill-evolution-confirm').waitFor();}
if(scene==='plugin-install'){assert.ok((await page.getByRole('checkbox').boundingBox()).width<=20);const button=page.locator('.plugin-management-footer .primary');assert.equal(await button.isDisabled(),true);await page.getByRole('checkbox').check();assert.equal(await button.isEnabled(),true);}
await page.screenshot({path:join(evidence,`${scene}-${width}-${theme}.png`)});await page.close();
}}
finally{await browser.close();console.log('Resource screenshots:',evidence);}
});

test('template library errors are localized without falsely showing an empty catalog', async () => {
  const browser = await chromium.launch({ headless: true, ...qaConfig.use.launchOptions });
  try {
    for (const locale of ['en', 'zh-CN']) {
      for (const error of ['local_subagent_registry_unavailable', 'unexpected_transport_failure: opaque diagnostics', null]) {
        const page = await browser.newPage({ viewport: { width: 640, height: 800 }, locale });
        await page.route('https://settings.test/**', route => route.fulfill({ contentType: 'text/html', body: '<div id="root"></div>' }));
        await page.goto(`https://settings.test/?scene=library-error${error ? `&error=${encodeURIComponent(error)}` : ''}`);
        await page.evaluate(value => localStorage.setItem('agistack.desktop.locale', value), locale);
        await page.addStyleTag({ content: css });
        await page.addScriptTag({ content: script });
        await page.getByRole('dialog').waitFor();
        if (error) {
          assert.equal(await page.locator('.subagent-library-state').count(), 0);
          const alert = page.getByRole('alert');
          const expected = error === 'local_subagent_registry_unavailable'
            ? (locale === 'en' ? 'The template library is unavailable in this local workspace.' : '当前本地工作区暂不支持模板库。')
            : (locale === 'en' ? 'The template library request failed. Close this window and try again.' : '模板库请求失败，请关闭此窗口后重试。');
          assert.ok((await alert.innerText()).includes(expected));
          assert.equal(await alert.locator('pre').isVisible(), false);
          await alert.locator('summary').click();
          assert.equal(await alert.locator('pre').innerText(), error);
          await alert.locator('summary').click();
          assert.equal(await alert.locator('pre').isVisible(), false);
          await page.screenshot({ path: join(evidence, `library-${locale}-${error === 'local_subagent_registry_unavailable' ? 'unavailable' : 'unknown'}.png`) });
        } else {
          assert.equal(await page.getByRole('alert').count(), 0);
          assert.equal(await page.locator('.subagent-library-state').count(), 1);
        }
        await page.close();
      }
    }
  } finally {
    await browser.close();
    console.log('Library error screenshots:', evidence);
  }
});
