import { createRequire as moduleRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = moduleRequire(import.meta.url);
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const assert = require("node:assert/strict");
const { createRequire } = require("node:module");
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);
const here = fs.mkdtempSync(
  path.join(require("node:os").tmpdir(), "memstack-repl-renderer-browser-"),
);
const req = createRequire(
  path.join(root, "agi-stack/apps/desktop/package.json"),
);
const esbuild = createRequire(req.resolve("vite/package.json"))("esbuild");
const { chromium } = req("@playwright/test");
const shellHtml = fs.readFileSync(path.join(root, "agi-stack/apps/desktop/index.html"), "utf8");
const shellCsp = shellHtml.match(/http-equiv="Content-Security-Policy"\s+content="([^"]+)"/u)?.[1];
assert.ok(shellCsp, "use the actual desktop shell CSP for srcdoc inheritance");
assert.doesNotMatch(shellCsp, /script-src[^;]*'unsafe-inline'/u);
const desktop = path.join(root, "agi-stack/apps/desktop/src");
const entry = `import React from 'react';import {createRoot} from 'react-dom/client';
import {PlatformPluginToolResultSlots} from ${JSON.stringify(desktop + "/features/chat/PlatformPluginToolResultSlots.tsx")};
import {DESKTOP_TOOL_RESULT_RENDERER_MODULE_V2 as module} from ${JSON.stringify(desktop + "/plugins/desktopToolResultRendererModuleV2.ts")};
import {ReplToolResultContentV2} from ${JSON.stringify(root + "/web/src/components/plugins/ReplToolResultContentV2.tsx")};
const png=Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6tewAAAAASUVORK5CYII='),x=>x.charCodeAt(0));
const wave=new Uint8Array(16044),view=new DataView(wave.buffer); const put=(p,s)=>{for(let i=0;i<s.length;i++)wave[p+i]=s.charCodeAt(i)};put(0,'RIFF');view.setUint32(4,16036,true);put(8,'WAVE');put(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,8000,true);view.setUint32(28,16000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);put(36,'data');view.setUint32(40,16000,true);
const waits=[],requests=[]; const client={preview(id,signal){requests.push({id,signal});return new Promise(resolve=>waits.push({id,resolve}));},audio(id,signal){requests.push({id,signal});return Promise.resolve(new Blob([wave],{type:'audio/wav'}));}};
const slot={id:'structured-tool-result',pluginId:'test',sourceEntryId:'test',slot:'tool_result_renderer',contract:'tool-result@2'};
window.qa={owner:'one',client,requests,waits,slots:[slot],generation:{meta:{digest:'test-generation'},composition:{resolveToolResultRendererModule:()=>module}},mode:'desktop',presentation:{kind:'repl_output',entries:[{kind:'text',text:'before'},{kind:'audio',store:'device',artifactId:'audio-one',mimeType:'audio/wav',sizeBytes:wave.length},{kind:'text',text:'between'},{kind:'image',store:'device',artifactId:'image-one',mimeType:'image/png',sizeBytes:png.length},{kind:'text',text:'after'}]},resolve(id){waits.find(x=>x.id===id).resolve('data:image/png;base64,'+btoa(String.fromCharCode(...png)));},png,wave};
const app=createRoot(document.getElementById('root'));
window.render=()=>app.render(window.qa.mode==='desktop'?<PlatformPluginToolResultSlots resultId='same-result' presentation={JSON.parse(JSON.stringify(window.qa.presentation))} toolName='declared' status='complete' kind='repl_output'/>:<ReplToolResultContentV2 presentation={window.qa.presentation} media={window.qa.media} label='Output'/>);
window.unmount=()=>app.unmount();window.render();`;
const hook = `export const t=(x)=>x;export const useI18n=()=>({t});export const useTranslation=()=>({t});export const useOptionalDesktopRendererGenerationV2=()=>window.qa.generation;export const usePlatformPluginUiSlots=()=>({slots:window.qa.slots,error:null,loading:false});export const useComputerUseDevice=()=>({client:window.qa.client});export const useTimelineInspection=()=>({sessionKey:window.qa.owner});`;
(async () => {
  await Promise.race([
    esbuild.build({
    stdin: { contents: entry, resolveDir: root, loader: "tsx" },
    outfile: path.join(here, "browser-regression.bundle.js"),
    bundle: true,
    platform: "browser",
    format: "iife",
    jsx: "automatic",
    nodePaths: [path.join(root, "agi-stack/apps/desktop/node_modules")],
    plugins: [
      {
        name: "owner-seams",
        setup(build) {
          build.onResolve(
            { filter: /^react(?:\/.*)?$|^react-dom(?:\/.*)?$/ },
            (a) => ({ path: req.resolve(a.path) }),
          );
          build.onResolve(
            {
              filter:
                /^(react-i18next)$|(?:\/i18n|desktopRendererGenerationContextV2|usePlatformPluginUiSlots|ComputerUseDeviceProvider|TimelineInspectionContext)$/,
            },
            (a) => ({ path: a.path, namespace: "hooks" }),
          );
          build.onLoad({ filter: /.*/, namespace: "hooks" }, () => ({
            contents: hook,
            loader: "js",
          }));
          build.onResolve({ filter: /^@agistack\/plugin-slots$/ }, () => ({
            path: root + "/agi-stack/packages/plugin-slots/src/index.ts",
          }));
        },
      },
    ],
  }),
    new Promise((_, reject) => {
      setTimeout(() => reject(new Error("desktop browser bundle timed out")), 90_000);
    }),
  ]);
  const server = http.createServer((request, response) => {
    if (request.url === "/bundle.js") {
      response.setHeader("content-type", "text/javascript");
      response.end(
        fs.readFileSync(path.join(here, "browser-regression.bundle.js")),
      );
    } else {
      response.setHeader("content-type", "text/html");
      response.end(`<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${shellCsp}"></head><body><div id="root"></div><script src="/bundle.js"></script></body></html>`);
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const browser = await chromium.launch({ headless: true, timeout: 20_000 });
  const page = await browser.newPage();
  page.setDefaultTimeout(5000);
  const errors = [];
  const cspErrors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (message) => {
    if (message.type() === "error" && /Content Security Policy/iu.test(message.text())) {
      cspErrors.push(message.text());
    }
  });
  try {
    await page.goto("http://127.0.0.1:" + server.address().port);
    await page.waitForFunction(() =>
      window.qa?.waits.some((x) => x.id === "image-one"),
    );
    await page.locator("iframe").waitFor();
    let frame = page.frames().find((f) => f.parentFrame());
    await frame.waitForSelector("#presentation");
    assert.equal(
      await frame.locator("audio").count(),
      0,
      "pending second asset must not publish playable first asset",
    );
    await page.evaluate(() => window.qa.resolve("image-one"));
    await frame.waitForSelector("audio");
    await frame.waitForFunction(
      () => document.querySelector("audio")?.readyState >= 1,
    );
    assert.deepEqual(
      await frame
        .locator("#presentation")
        .evaluate((el) => [...el.children].map((x) => x.tagName)),
      ["PRE", "AUDIO", "PRE", "IMG", "PRE"],
    );
    assert.equal(
      await frame.locator("img").evaluate((el) => el.naturalWidth),
      1,
    );
    await frame.evaluate(() => {
      window.savedAudio = document.querySelector("audio");
      window.savedAudio.currentTime = 0.2;
    });
    await page.evaluate(() => window.render());
    await page.waitForTimeout(100);
    assert.equal(
      await frame.evaluate(
        () => document.querySelector("audio") === window.savedAudio,
      ),
      true,
    );
    assert.ok(
      await frame.evaluate(
        () =>
          Math.abs(document.querySelector("audio").currentTime - 0.2) < 0.02,
      ),
    );
    assert.equal(await frame.locator("audio").getAttribute("autoplay"), null);
    await page.evaluate(() => {
      window.qa.presentation = {
        kind: "repl_output",
        entries: [
          {
            kind: "image",
            store: "device",
            artifactId: "old-pending",
            mimeType: "image/png",
            sizeBytes: window.qa.png.length,
          },
        ],
      };
      window.render();
    });
    await page.waitForFunction(() =>
      window.qa.waits.some((x) => x.id === "old-pending"),
    );
    await page.evaluate(() => {
      window.qa.owner = "two";
      window.qa.presentation = {
        kind: "repl_output",
        entries: [
          { kind: "text", text: "new conversation" },
          {
            kind: "image",
            store: "device",
            artifactId: "new-pending",
            mimeType: "image/png",
            sizeBytes: window.qa.png.length,
          },
        ],
      };
      window.render();
    });
    await page.waitForFunction(() =>
      window.qa.waits.some((x) => x.id === "new-pending"),
    );
    assert.equal(
      await page.evaluate(
        () =>
          window.qa.requests.find((x) => x.id === "old-pending").signal.aborted,
      ),
      true,
    );
    await page.evaluate(() => window.qa.resolve("old-pending"));
    frame = page.frames().find((f) => f.parentFrame());
    await frame.waitForSelector("#presentation");
    assert.equal(await frame.locator("img").count(), 0);
    assert.equal(await frame.locator("pre").textContent(), "new conversation");
    await page.evaluate(() => window.qa.resolve("new-pending"));
    await frame.waitForSelector("img");
    await page.evaluate(() => {
      window.qa.mode = "web";
      window.qa.presentation = {
        kind: "repl_output",
        entries: [
          { kind: "text", text: "web before" },
          {
            kind: "audio",
            store: "conversation_tool_media",
            artifactId: "web-audio",
            mimeType: "audio/wav",
            sizeBytes: window.qa.wave.length,
          },
          {
            kind: "image",
            store: "conversation_tool_media",
            artifactId: "web-image",
            mimeType: "image/png",
            sizeBytes: window.qa.png.length,
          },
        ],
      };
      window.qa.media = [
        {
          store: "conversation_tool_media",
          artifactId: "web-audio",
          mimeType: "audio/wav",
          bytes: window.qa.wave,
        },
        {
          store: "conversation_tool_media",
          artifactId: "web-image",
          mimeType: "image/png",
          bytes: window.qa.png,
        },
      ];
      window.qa.revoked = [];
      const revoke = URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL = (url) => {
        window.qa.revoked.push(url);
        revoke(url);
      };
      window.render();
    });
    await page.locator("audio").waitFor();
    await page.waitForFunction(
      () => document.querySelector("audio").readyState >= 1,
    );
    assert.deepEqual(
      await page
        .locator("#root > div")
        .evaluate((el) => [...el.children].map((x) => x.tagName)),
      ["PRE", "AUDIO", "IMG"],
    );
    assert.equal(
      await page.locator("img").evaluate((el) => el.naturalWidth),
      1,
    );
    await page.evaluate(() => window.unmount());
    assert.equal(await page.evaluate(() => window.qa.revoked.length), 2);
    assert.deepEqual(errors, []);
    assert.deepEqual(cspErrors, [], "the actual parent and guest CSP must permit rendering");
    const result = {
      ok: true,
      tests: [
        "actual desktop shell CSP + React host + sandboxed production guest interleaving",
        "delayed second asset publishes one batch",
        "unrelated rerender preserves same audio DOM and currentTime",
        "same-client conversation switch aborts old request and rejects late completion",
        "actual Web React media component renders and revokes all Blob URLs",
      ],
      pageErrors: errors,
      cspErrors,
    };
    fs.writeFileSync(
      path.join(here, "browser-green.json"),
      JSON.stringify(result, null, 2),
    );
    console.log(JSON.stringify(result));
  } catch (error) {
    console.error(
      "Browser diagnostics",
      JSON.stringify({
        errors,
        cspErrors,
        body: await page.locator("body").innerText(),
        qa: await page.evaluate(() => ({
          mode: window.qa.mode,
          media: window.qa.media?.map((x) => ({
            id: x.artifactId,
            type: x.bytes.constructor.name,
            len: x.bytes.byteLength,
          })),
          presentation: window.qa.presentation,
        })),
      }),
    );
    throw error;
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
    fs.rmSync(here, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
