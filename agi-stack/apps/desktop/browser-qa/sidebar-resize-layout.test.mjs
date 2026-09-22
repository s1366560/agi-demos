import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { createRequire } from 'node:module';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from '@playwright/test';
import qaConfig from './playwright.config.mjs';

const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const evidence = mkdtempSync(join(tmpdir(), 'codex-sidebar-resize-'));
let browser;
let script;
let styles;
const measurements = [];

before(async () => {
  const bundle = await esbuild.build({
    stdin: {
      contents: `
        import React, {useState} from 'react';
        import {createRoot} from 'react-dom/client';
        import {Theme, ScrollArea} from '@radix-ui/themes';
        import '@radix-ui/themes/styles.css';
        import './src/styles/global.css';
        import {DesktopSidebar} from './src/features/navigation/DesktopSidebar';
        import {I18nProvider} from './src/i18n';
        const noop=()=>{};
        const props={
          activeSection:'home',taskCount:0,activityUnreadCount:0,
          tenantName:'Northstar Labs',projectName:'Desktop Client',
          user:{name:'Alexandria Researcher',email:'alexandria.long@example.test'},
          workspaces:[],conversationsByWorkspace:{},
          nodeState:{projects:{project:{loading:false,error:null}},workspaces:{}},
          currentProjectId:'project',currentWorkspaceId:'',currentConversationId:null,
          workspaceTreeSelectionMode:'none',expandedWorkspaceIds:new Set(),newTaskDisabledReason:null,
          onNavigate:noop,onNewTask:noop,onOpenSearch:noop,onOpenFeatureDirectory:noop,
          onCreateWorkspace:noop,onOpenAccountSettings:noop,onSwitchWorkspace:noop,onSignOut:noop,
          onToggleWorkspace:noop,onRetryProject:noop,onRetryWorkspace:noop,
          onSelectWorkspace:noop,onSelectConversation:noop,
        };
        function Fixture(){
          const [collapsed,setCollapsed]=useState(false);
          const width=Number(new URLSearchParams(location.search).get('width')||220);
          return <I18nProvider><Theme appearance="light"><div
            className={'app-shell desktop-window hierarchy-shell'+(collapsed?' sidebar-collapsed':'')}
            style={{'--desktop-sidebar-preferred-width':width+'px'}}>
            <header className="desktop-titlebar"><button id="toggle" onClick={()=>setCollapsed(x=>!x)}>Toggle sidebar</button></header>
            <DesktopSidebar {...props}/>
            <main className="workbench"><div className="workbench-content">
              <button id="content-focus">Content action</button>
              <section className="chat-shell">
                <ScrollArea className="message-scroll" tabIndex={0} aria-label="Conversation timeline" type="always" scrollbars="both" style={{height:180,width:260}}>
                  <div style={{height:1000,width:800}}>Scrollable conversation</div>
                </ScrollArea>
              </section>
            </div></main>
          </div></Theme></I18nProvider>;
        }
        createRoot(document.getElementById('root')).render(<Fixture/>);
      `,
      resolveDir: new URL('..', import.meta.url).pathname,
      loader: 'tsx',
    },
    bundle: true,
    write: false,
    outfile: join(evidence, 'fixture.js'),
    platform: 'browser',
    format: 'iife',
    define: { 'process.env.NODE_ENV': '"production"' },
  });
  script = bundle.outputFiles.find((file) => file.path.endsWith('.js')).text;
  styles = bundle.outputFiles.find((file) => file.path.endsWith('.css')).text;
  browser = await chromium.launch({ headless: true, ...qaConfig.use.launchOptions });
});
after(async () => {
  await browser?.close();
  writeFileSync(join(evidence, 'measurements.json'), JSON.stringify(measurements, null, 2));
  console.log(`Sidebar geometry evidence: ${evidence}`);
});

for (const width of [180, 220, 320]) {
  test(`actual sidebar footer fits ${width}px and fully leaves layout and tab order when collapsed`, async () => {
    const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.route('http://sidebar.test/**', async (route) => {
      if (route.request().resourceType() === 'document') {
        await route.fulfill({ contentType: 'text/html', body: '<!doctype html><html data-theme="light"><body><div id="root"></div></body></html>' });
      } else await route.fulfill({ status: 204, body: '' });
    });
    try {
      await page.goto(`http://sidebar.test/?width=${width}`);
      await page.addStyleTag({ content: styles });
      await page.addScriptTag({ content: script });
      await page.locator('.desktop-design-profile').waitFor();
      const normal = await page.evaluate(() => {
        const rect=(selector)=>{const {x,y,width,height,right,bottom}=document.querySelector(selector).getBoundingClientRect();return {x,y,width,height,right,bottom};};
        const sidebar=document.querySelector('.desktop-design-sidebar');
        const footer=document.querySelector('.desktop-design-toolbar');
        return { sidebar:rect('.desktop-design-sidebar'),footer:rect('.desktop-design-toolbar'),
          features:rect('.desktop-design-feature-button'),profile:rect('.desktop-design-profile'),
          content:rect('.workbench'),overflow:sidebar.scrollWidth-sidebar.clientWidth,
          footerOverflow:footer.scrollWidth-footer.clientWidth,
          scrollbars:[...document.querySelectorAll('.rt-ScrollAreaScrollbar')].map((bar)=>({
            orientation:bar.getAttribute('data-orientation'),width:bar.getBoundingClientRect().width,height:bar.getBoundingClientRect().height,
          })) };
      });
      measurements.push({width,normal});
      assert.ok(Math.abs(normal.sidebar.width-width)<=1,JSON.stringify(normal));
      assert.equal(normal.overflow,0);
      assert.equal(normal.footerOverflow,0);
      for(const control of [normal.features,normal.profile]){
        assert.ok(control.x>=normal.footer.x-1 && control.right<=normal.footer.right+1);
        assert.ok(control.width>=width-32,'footer controls use the available width');
        assert.ok(control.height>=30,'footer controls retain usable height');
      }
      assert.ok(normal.profile.y>=normal.features.bottom,'footer controls occupy separate rows');
      assert.equal(normal.scrollbars.length,2);
      for(const bar of normal.scrollbars){
        const thickness=bar.orientation==='vertical'?bar.width:bar.height;
        assert.ok(thickness>0 && thickness<=8,JSON.stringify(bar));
      }
      await page.screenshot({path:join(evidence,`sidebar-${width}.png`)});
      await page.locator('#toggle').click();
      await page.locator('.desktop-design-sidebar').waitFor({state:'hidden'});
      const collapsed=await page.evaluate(()=>{
        const sidebar=document.querySelector('.desktop-design-sidebar');
        const content=document.querySelector('.workbench').getBoundingClientRect();
        return {sidebarWidth:sidebar.getBoundingClientRect().width,contentX:content.x,contentWidth:content.width,
          visibleFocusable:[...sidebar.querySelectorAll('button,a,input,[tabindex]')].filter((element)=>element.getClientRects().length>0).length};
      });
      measurements.push({width,collapsed});
      assert.equal(collapsed.sidebarWidth,0);
      assert.equal(collapsed.visibleFocusable,0);
      assert.equal(collapsed.contentX,0);
      assert.equal(collapsed.contentWidth,1100);
      await page.locator('#toggle').focus();
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(()=>document.activeElement.id),'content-focus');
      await page.locator('#toggle').click();
      await page.locator('.desktop-design-sidebar').waitFor({state:'visible'});
      assert.equal(Math.round((await page.locator('.desktop-design-sidebar').boundingBox()).width),width);
      assert.deepEqual(errors,[]);
    } finally { await page.close(); }
  });
}


test('real transcript ScrollArea avoids a selection outline and retains keyboard focus and scrolling', async () => {
  const page = await browser.newPage({viewport:{width:1100,height:800}});
  await page.route('http://sidebar.test/**', route => route.fulfill({contentType:'text/html',body:'<!doctype html><html data-theme="light"><body><div id="root"></div></body></html>'}));
  try {
    await page.goto('http://sidebar.test/?width=220');
    await page.addStyleTag({content:styles});
    await page.addScriptTag({content:script});
    const scroll=page.locator('.message-scroll');
    const viewport=scroll.locator('[data-radix-scroll-area-viewport]');
    await scroll.waitFor();
    await scroll.click({position:{x:120,y:90}});
    const pointer=await scroll.evaluate(element=>({outline:getComputedStyle(element).outlineStyle,shadow:getComputedStyle(element).boxShadow,focusVisible:element.matches(':focus-visible')}));
    assert.equal(pointer.outline,'none');
    assert.equal(await viewport.evaluate(element=>getComputedStyle(element).outlineStyle),'none');
    const ring=scroll.locator('.rt-ScrollAreaViewportFocusRing');
    assert.equal(await ring.count(),1,'real Radix focus-ring sibling is included');
    assert.equal(await ring.evaluate(element=>getComputedStyle(element).outlineStyle),'none');
    await page.locator('#content-focus').focus();
    await page.keyboard.press('Tab');
    const keyboard=await scroll.evaluate(element=>{const focused=document.activeElement;return {active:element.contains(focused),outline:getComputedStyle(focused).outlineStyle,shadow:getComputedStyle(focused).boxShadow,focusVisible:focused.matches(':focus-visible')};});
    assert.equal(keyboard.active,true);
    assert.equal(keyboard.outline,'none');
    assert.equal(keyboard.focusVisible,true);
    assert.match(keyboard.shadow,/2px 0px 0px 0px inset/);
    assert.equal(await viewport.evaluate(element=>document.activeElement===element),true);
    assert.equal(await ring.evaluate(element=>getComputedStyle(element).outlineStyle),'none');
    await page.keyboard.press('PageDown');
    await page.waitForFunction(()=>document.querySelector('.message-scroll [data-radix-scroll-area-viewport]').scrollTop>0,null,{timeout:3000});
    assert.equal(await viewport.evaluate(element=>getComputedStyle(element).outlineStyle),'none');
    await page.locator('#content-focus').focus();
    assert.notEqual(await page.locator('#content-focus').evaluate(element=>getComputedStyle(element).outlineStyle),'none','normal buttons keep their keyboard outline');
    measurements.push({transcriptFocus:{pointer,keyboard,scrollTop:await viewport.evaluate(element=>element.scrollTop)}});
    await page.screenshot({path:join(evidence,'transcript-focus.png')});
  } finally {await page.close();}
});
