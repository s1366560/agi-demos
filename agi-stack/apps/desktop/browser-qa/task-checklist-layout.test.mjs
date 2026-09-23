import assert from "node:assert/strict";
import { test } from "node:test";
import { createRequire } from "node:module";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "@playwright/test";
import qaConfig from "./playwright.config.mjs";
const require = createRequire(import.meta.url);
const esbuild = createRequire(require.resolve("vite"))("esbuild");
const evidence = mkdtempSync(join(tmpdir(), "task-checklist-layout-"));
test("task plan stays aligned, scrollable and readable across widths and themes", async () => {
  const bundle = await esbuild.build({
    stdin: {
      contents: `
 import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
 import {Theme} from '@radix-ui/themes';import '@radix-ui/themes/styles.css';
 import './src/styles/global.css';import './src/features/chat/ChatPanel.css';
 import {TaskChecklist} from './src/features/chat/TaskChecklist';import {I18nProvider} from './src/i18n';
 function Fixture(){const [status,setStatus]=useState('pending');const [count,setCount]=useState(18);
 const items=Array.from({length:count},(_,i)=>({id:String(i),content:'检查任务状态和历史恢复 / Verify task progress and history '+ 'long-path/'.repeat(12),status:i===0?status:'pending',priority:'high',orderIndex:i}));
 return <I18nProvider><Theme appearance={new URLSearchParams(location.search).get('theme')||'dark'}>
 <button id="running" onClick={()=>setStatus('in_progress')}>Running</button><button id="done" onClick={()=>{setStatus('completed');setCount(1)}}>Done</button>
 <div className="chat-shell" style={{width:'100%',display:'block'}}><TaskChecklist items={items}/><div className="chat-composer"><textarea aria-label="Message"/></div></div></Theme></I18nProvider>}
 createRoot(document.getElementById('root')).render(<Fixture/>);`,
      resolveDir: new URL("..", import.meta.url).pathname,
      loader: "tsx",
    },
    bundle: true,
    write: false,
    outfile: join(evidence, "fixture.js"),
    platform: "browser",
    format: "iife",
    define: { "process.env.NODE_ENV": '"production"' },
  });
  const script = bundle.outputFiles.find((x) => x.path.endsWith(".js")).text,
    css = bundle.outputFiles.find((x) => x.path.endsWith(".css")).text;
  const browser = await chromium.launch({
    headless: true,
    ...qaConfig.use.launchOptions,
  });
  try {
    for (const width of [360, 800, 1100, 1440])
      for (const theme of ["light", "dark"]) {
        const page = await browser.newPage({
          viewport: { width, height: 800 },
          reducedMotion: "reduce",
        });
        await page.route("http://checklist.test/**", (route) =>
          route.fulfill({
            contentType: "text/html",
            body: '<div id="root"></div>',
          }),
        );
        await page.goto("http://checklist.test/?theme=" + theme);
        await page.addStyleTag({ content: css });
        await page.addScriptTag({ content: script });
        const checklist = page.locator(".task-checklist"),
          composer = page.locator(".chat-composer");
        const a = await checklist.boundingBox(),
          b = await composer.boundingBox();
        assert.ok(Math.abs(a.x - b.x) < 1);
        assert.ok(Math.abs(a.width - b.width) < 1);
        assert.ok(a.width <= 800);
        assert.ok(a.height < 240);
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth > innerWidth,
          ),
          false,
        );
        await page.locator(".task-checklist-header").click();
        await page.locator("#running").click();
        assert.equal(
          await page
            .locator(".task-checklist-header")
            .getAttribute("aria-expanded"),
          "false",
        );
        assert.match(await checklist.innerText(), /1 in progress/);
        await page.locator(".task-checklist-header").click();
        assert.equal(
          await page
            .locator(".status-in_progress .task-checklist-status")
            .innerText(),
          "In progress",
        );
        assert.equal(
          await page
            .locator(".status-in_progress svg")
            .evaluate((x) => getComputedStyle(x).animationName),
          "none",
        );
        await page.locator("#done").click();
        assert.equal(
          await page.locator(".task-checklist-count").innerText(),
          "1/1 completed",
        );
        assert.equal(
          await page.locator(".task-checklist-status").innerText(),
          "Completed",
        );
        await page.screenshot({
          path: join(evidence, width + "-" + theme + ".png"),
        });
        await page.close();
      }
  } finally {
    await browser.close();
  }
  console.log("Checklist screenshots: " + evidence);
});
