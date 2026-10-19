import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runInNewContext } from "node:vm";
import { chromium } from "@playwright/test";

const source = readFileSync(
  new URL(
    "../src/plugins/desktopToolResultRendererModuleV2.ts",
    import.meta.url,
  ),
  "utf8",
);
const script = source.match(/<script>([\s\S]*?)<\/script>/u)[1];

function guest() {
  const elements = new Map();
  const element = () => ({
    hidden: true,
    dataset: {},
    style: {},
    textContent: "",
    children: [],
    append(child) {
      this.children.push(child);
    },
    replaceChildren() {
      this.children = [];
    },
    remove() {},
  });
  const messages = [];
  const parent = { postMessage: (message) => messages.push(message) };
  let receive;
  const revoked = [];
  runInNewContext(script, {
    parent,
    Uint8Array,
    Blob,
    URL: {
      createObjectURL: () => "blob:null/guest-owned",
      revokeObjectURL: (url) => revoked.push(url),
    },
    document: {
      body: { scrollHeight: 80 },
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
    },
    window: {
      addEventListener: (name, handler) => {
        if (name === "message") receive = handler;
      },
      removeEventListener() {},
    },
  });
  return {
    elements,
    messages,
    render: (payload) =>
      receive({
        source: parent,
        data: {
          source: "memstack-plugin-slot",
          message: {
            type: "slot:init",
            slotId: "structured-tool-result",
            payload,
          },
        },
      }),
  };
}

test("computer use result is accepted by the actual sandbox guest and renders its AX text", () => {
  for (const status of ["complete", "failed", "paused", "stopped"]) {
    const runtime = guest();
    runtime.render({
      schemaVersion: 1,
      resultId: "computer-state",
      toolName: "computer_get_app_state",
      kind: "computer_use",
      status,
      resultLabel: "Computer result",
      kindLabel: "Computer",
      statusLabel: status,
      presentation: { kind: "text", text: "[3] Text field" },
    });
    assert.equal(runtime.elements.get("surface").hidden, false);
    assert.equal(runtime.elements.get("surface").dataset.kind, "computer_use");
    assert.equal(
      runtime.elements.get("presentation").children[0].textContent,
      "[3] Text field",
    );
    assert.equal(
      runtime.messages.some(({ message }) => message.type === "slot:error"),
      false,
    );
  }
});

test("guest keeps rejecting unknown presentation kinds", () => {
  const runtime = guest();
  runtime.render({
    schemaVersion: 1,
    resultId: "bad",
    toolName: "x",
    kind: "unknown",
    status: "complete",
    resultLabel: "Result",
    kindLabel: "Unknown",
    statusLabel: "Complete",
  });
  assert.equal(runtime.elements.get("surface").hidden, true);
  assert.equal(runtime.messages.at(-1).message.type, "slot:error");
});
test("computer presentation renders AX content and only artifact-bound typed image bytes", () => {
  const runtime = guest();
  const payload = {
    schemaVersion: 1,
    resultId: "observed",
    toolName: "computer_get_app_state",
    kind: "computer_use",
    status: "complete",
    resultLabel: "Result",
    kindLabel: "Computer",
    statusLabel: "Complete",
    presentation: {
      kind: "computer_use",
      app: "Fixture",
      summary: "Two controls",
      text: "[0] Window\n[1] Button",
      screenshotArtifactId: "cua-image-abcd",
    },
    computerUsePreview: {
      artifactId: "cua-image-abcd",
      mimeType: "image/png",
      bytes: new Uint8Array([1]),
    },
  };
  runtime.render(payload);
  const children = runtime.elements.get("presentation").children;
  assert.deepEqual(
    children.map((child) => child.textContent),
    ["Fixture", "Two controls", "", "[0] Window\n[1] Button"],
  );
  assert.equal(children[2].src, "blob:null/guest-owned");
  assert.equal(children[2].alt, "Fixture");
  for (const url of [
    "https://untrusted.test/image.png",
    "file:///private/image.png",
    "data:image/png;base64,AAAA",
  ]) {
    runtime.render({
      ...payload,
      computerUsePreview: { artifactId: "cua-image-abcd", url },
    });
    assert.equal(
      runtime.elements.get("presentation").children.some((child) => child.src),
      false,
    );
  }
  runtime.render({
    ...payload,
    computerUsePreview: {
      artifactId: "cua-image-different",
      url: "blob:https://memstack.test/owned",
    },
  });
  assert.equal(
    runtime.elements.get("presentation").children.some((child) => child.src),
    false,
  );
  for (const preview of [
    { mimeType: "text/html", bytes: new Uint8Array([1]) },
    { mimeType: "image/png", bytes: [1] },
    { mimeType: "image/png", bytes: new Uint8Array() },
    { mimeType: "image/png", bytes: new Uint8Array(8 * 1024 * 1024 + 1) },
  ]) {
    runtime.render({
      ...payload,
      computerUsePreview: { artifactId: "cua-image-abcd", ...preview },
    });
    assert.equal(
      runtime.elements.get("presentation").children.some((child) => child.src),
      false,
    );
  }
});

test("real opaque Chromium guest inherits the desktop shell CSP and displays structured-cloned pixels", async () => {
  const html = source.match(
    /const DESKTOP_TOOL_RESULT_RENDERER_SRC_DOC_V2 = `([\s\S]*?)`;/u,
  )[1];
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const shell = readFileSync(
      new URL("../index.html", import.meta.url),
      "utf8",
    );
    const policy = shell.match(
      /<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"\s*\/>/u,
    )[1];
    await page.route("http://cua-preview-fixture.test/**", (route) =>
      route.fulfill({
        contentType: "text/html",
        // srcdoc inherits this real policy in addition to the guest's own CSP.
        body: `<html><head><meta http-equiv="Content-Security-Policy" content="${policy}"></head><body></body></html>`,
      }),
    );
    await page.goto("http://cua-preview-fixture.test/");
    await page.evaluate((srcDoc) => {
      window.cuaMessages = [];
      addEventListener("message", (event) =>
        window.cuaMessages.push(event.data),
      );
      const iframe = document.createElement("iframe");
      iframe.sandbox = "allow-scripts";
      iframe.srcdoc = srcDoc;
      document.body.append(iframe);
    }, html);
    await page.waitForFunction(() =>
      window.cuaMessages.some(({ message }) => message?.type === "slot:ready"),
    );
    const frame = page.frames().find((frame) => frame !== page.mainFrame());
    assert.equal(await frame.evaluate(() => window.origin), "null");
    assert.equal(
      await page.locator("iframe").getAttribute("sandbox"),
      "allow-scripts",
    );
    const pixel =
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ2cAAAAASUVORK5CYII=";
    await page.evaluate((base64) => {
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      const payload = {
        schemaVersion: 1,
        resultId: "actual-image",
        toolName: "computer_get_app_state",
        kind: "computer_use",
        status: "complete",
        resultLabel: "Result",
        kindLabel: "Computer",
        statusLabel: "Complete",
        presentation: {
          kind: "computer_use",
          app: "Fixture",
          summary: "Fixture pixels",
          text: "[0] Fixture",
          screenshotArtifactId: "cua-image-abcd",
          appIconArtifactId: "cua-image-beef",
          windowId: "fixture-window-1",
          windowTitle: "Owned fixture",
          observedAt: "2026-10-14T01:00:00Z",
        },
        computerUsePreview: {
          artifactId: "cua-image-abcd",
          mimeType: "image/png",
          bytes,
        },
        computerUseAppIcon: {
          artifactId: "cua-image-beef",
          mimeType: "image/png",
          bytes,
        },
      };
      document.querySelector("iframe").contentWindow.postMessage(
        {
          source: "memstack-plugin-slot",
          message: {
            type: "slot:init",
            slotId: "structured-tool-result",
            payload,
          },
        },
        "*",
      );
    }, pixel);
    await frame.waitForFunction(
      () =>
        document.querySelector(".computer-use-observation-preview")
          ?.naturalWidth === 1,
    );
    const image = await frame
      .locator(".computer-use-observation-preview")
      .evaluate((img) => ({
        width: img.naturalWidth,
        height: img.naturalHeight,
        url: img.src,
      }));
    assert.equal(image.width, 1);
    assert.equal(image.height, 1);
    assert.match(image.url, /^blob:null\//u);
    assert.equal(await frame.locator("pre").textContent(), "[0] Fixture");
    assert.equal(await frame.locator("img").count(), 3);
    assert.match(
      await frame.locator("#presentation").textContent(),
      /fixture-window-1/u,
    );
    await page.evaluate(() =>
      document.querySelector("iframe").contentWindow.postMessage(
        {
          source: "memstack-plugin-slot",
          message: { type: "slot:dispose", slotId: "structured-tool-result" },
        },
        "*",
      ),
    );
    await frame.waitForFunction(
      () => document.getElementById("surface") === null,
    );
    assert.equal(
      await frame.evaluate(
        (url) =>
          fetch(url).then(
            () => true,
            () => false,
          ),
        image.url,
      ),
      false,
    );
  } finally {
    await browser.close();
  }
});
