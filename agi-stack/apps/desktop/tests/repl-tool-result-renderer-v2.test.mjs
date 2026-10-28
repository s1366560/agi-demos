import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");
const repo = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);
const base = repo;
const repoRequire = Module.createRequire(
  repo + "/agi-stack/apps/desktop/package.json",
);
const ts = repoRequire("typescript");
const resolve = Module._resolveFilename;
Module._resolveFilename = function (request, parent, ...rest) {
  if (request === "@agistack/plugin-slots")
    return path.join(base, "agi-stack/packages/plugin-slots/src/index.ts");
  try {
    return resolve.call(this, request, parent, ...rest);
  } catch (error) {
    if (parent?.filename.startsWith(base + "/") && request.startsWith(".")) {
      const relative = path.relative(
        base,
        path.resolve(path.dirname(parent.filename), request),
      );
      return resolve.call(this, path.join(repo, relative), parent, ...rest);
    }
    throw error;
  }
};
require.extensions[".ts"] = (module, filename) =>
  module._compile(
    ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      fileName: filename,
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        esModuleInterop: true,
      },
    }).outputText,
    filename,
  );
const shared = require(
  path.join(
    base,
    "agi-stack/packages/plugin-slots/src/replOutputPresentationV2.ts",
  ),
);
const { projectToolOutputPresentationV2: project } = require(
  path.join(
    base,
    "agi-stack/apps/desktop/src/features/chat/toolResultOutputPresentationV2.ts",
  ),
);
const { toolCallPresentationKind } = require(
  path.join(
    base,
    "agi-stack/apps/desktop/src/features/chat/chatTimelineModel.ts",
  ),
);
const guestSource = fs.readFileSync(
  path.join(
    base,
    "agi-stack/apps/desktop/src/plugins/desktopToolResultRendererModuleV2.ts",
  ),
  "utf8",
);
const script = guestSource.match(/<script>([\s\S]*?)<\/script>/u)[1];
function guest(payload) {
  const elements = new Map(),
    messages = [],
    revoked = [];
  const element = (tag = "") => ({
    tag,
    hidden: true,
    dataset: {},
    style: {},
    textContent: "",
    children: [],
    append(x) {
      this.children.push(x);
    },
    replaceChildren() {
      this.children = [];
    },
    remove() {},
  });
  const parent = { postMessage: (m) => messages.push(m) };
  let receive;
  let serial = 0;
  runInNewContext(script, {
    parent,
    Uint8Array,
    Blob,
    URL: {
      createObjectURL: () => `blob:null/${++serial}`,
      revokeObjectURL: (url) => revoked.push(url),
    },
    document: {
      body: { scrollHeight: 100 },
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, element());
        return elements.get(id);
      },
      createElement: element,
    },
    window: {
      addEventListener(name, handler) {
        if (name === "message") receive = handler;
      },
      removeEventListener() {},
    },
  });
  const send = (message) =>
    receive({
      source: parent,
      data: {
        source: "memstack-plugin-slot",
        message: { slotId: "structured-tool-result", ...message },
      },
    });
  send({ type: "slot:init", payload });
  return {
    children: () => elements.get("presentation").children,
    messages,
    revoked,
    update: (p) => send({ type: "slot:event", name: "tool-result", data: p }),
    dispose: () => send({ type: "slot:dispose" }),
  };
}
const descriptor = (kind, id, size = 3) => ({
  store: "device",
  kind,
  artifact_id: id,
  mime_type: kind === "image" ? "image/png" : "audio/wav",
  size_bytes: size,
  url: "file:///must-not-cross",
});
const baseOutput = {
  outputs: [
    { type: "text", text: "before" },
    { type: "text", text: "between" },
    { type: "text", text: "after" },
  ],
  artifacts: [
    descriptor("image", "cua-image-a"),
    descriptor("audio", "cua-audio-b"),
    descriptor("image", "cua-image-c"),
  ],
  output_order: [
    { source: "text", index: 0 },
    { source: "media", index: 0 },
    { source: "text", index: 1 },
    { source: "media", index: 1 },
    { source: "media", index: 2 },
    { source: "text", index: 2 },
  ],
};
const payload = (presentation, media = []) => ({
  schemaVersion: 1,
  resultId: "result",
  toolName: "arbitrary-declared-tool",
  kind: "repl_output",
  status: "complete",
  resultLabel: "Output",
  kindLabel: "Output",
  statusLabel: "Complete",
  presentation,
  media,
});
const bytes = (presentation) =>
  shared
    .replMediaReferencesV2(presentation)
    .map((x) => ({
      store: x.store,
      artifactId: x.artifactId,
      mimeType: x.mimeType,
      bytes: new Uint8Array(x.sizeBytes),
    }));
test("declared kind never depends on tool name or output prose", () => {
  assert.equal(
    toolCallPresentationKind({
      call: { toolName: "cua_repl_js" },
      result: null,
    }),
    "tool",
  );
  assert.equal(
    toolCallPresentationKind({
      call: { toolName: "other", display: { kind: "repl_output" } },
      result: null,
    }),
    "repl_output",
  );
  assert.equal(project({ kind: "tool", output: baseOutput }).kind, "text");
});
test("actual production projection and guest preserve interleaved text, two images and audio", () => {
  const presentation = project({ kind: "repl_output", output: baseOutput });
  assert.equal(presentation.kind, "repl_output");
  const g = guest(payload(presentation, bytes(presentation)));
  assert.deepEqual(
    g.children().map((x) => x.tag),
    ["pre", "img", "pre", "audio", "img", "pre"],
  );
  assert.deepEqual(
    g
      .children()
      .filter((x) => x.tag === "pre")
      .map((x) => x.textContent),
    ["before", "between", "after"],
  );
  assert.equal(g.children()[3].controls, true);
  assert.equal(g.children()[3].autoplay, undefined);
  assert.equal(
    g.messages.some((x) => x.message.type === "slot:error"),
    false,
  );
  assert.equal(JSON.stringify(presentation).includes("file:///"), false);
});
test("mixed historical output without event order is not reordered by guess", () => {
  const { output_order, ...old } = baseOutput;
  assert.equal(shared.projectReplOutputPresentationV2(old), null);
  assert.equal(project({ kind: "repl_output", output: old }).kind, "text");
});
test("invalid, duplicate, out-of-range or incomplete event positions fail closed", () => {
  for (const order of [
    [],
    [...baseOutput.output_order.slice(0, -1), baseOutput.output_order[0]],
    [...baseOutput.output_order.slice(0, -1), { source: "text", index: 8 }],
    [...baseOutput.output_order.slice(0, -1), { source: "text", index: 0.5 }],
  ])
    assert.equal(
      shared.projectReplOutputPresentationV2({
        ...baseOutput,
        output_order: order,
      }),
      null,
    );
});
test("forged media payload never crosses artifact id, MIME or byte-length binding", () => {
  const p = project({
    kind: "repl_output",
    output: { outputs: [], artifacts: [descriptor("image", "cua-image-a")] },
  });
  for (const entry of [
    { artifactId: "other", mimeType: "image/png", bytes: new Uint8Array(3) },
    {
      artifactId: "cua-image-a",
      mimeType: "text/html",
      bytes: new Uint8Array(3),
    },
    {
      artifactId: "cua-image-a",
      mimeType: "image/png",
      bytes: new Uint8Array(4),
    },
    {
      artifactId: "cua-image-a",
      mimeType: "image/png",
      url: "https://bad.invalid/image",
    },
  ]) {
    const g = guest(payload(p, [{ store: "device", ...entry }]));
    assert.equal(
      g.children().some((x) => x.tag === "img" || x.tag === "audio"),
      false,
    );
  }
  assert.equal(
    shared.projectReplOutputPresentationV2({
      outputs: [],
      artifacts: [descriptor("image", "file:///private")],
    }),
    null,
  );
});
test("current guest revokes every media URL on replacement and disposal", () => {
  const p = project({ kind: "repl_output", output: baseOutput });
  const g = guest(payload(p, bytes(p)));
  g.update(payload(p, bytes(p)));
  assert.equal(g.revoked.length, 3);
  g.dispose();
  assert.equal(g.revoked.length, 6);
});
test("guest CSP matches its actual script and permits only owned blob media", () => {
  const crypto = require("node:crypto");
  const digest = crypto.createHash("sha256").update(script).digest("base64");
  assert.ok(guestSource.includes(`script-src 'sha256-${digest}'`));
  assert.ok(guestSource.includes("img-src blob:; media-src blob:;"));
});

test("malformed guest entries reject the whole update and clean all previous media", () => {
  const p = project({ kind: "repl_output", output: baseOutput });
  for (const bad of [
    null,
    [],
    {},
    { kind: "text", text: 1 },
    { kind: "video", artifactId: "valid" },
    {
      kind: "image",
      store: "device",
      artifactId: "bad/url",
      mimeType: "image/png",
      sizeBytes: 3,
    },
  ]) {
    const g = guest(payload(p, bytes(p)));
    assert.doesNotThrow(() =>
      g.update(payload({ kind: "repl_output", entries: [p.entries[0], bad] })),
    );
    assert.deepEqual(g.children(), []);
    assert.equal(g.revoked.length, 3);
    assert.equal(g.messages.at(-1).message.type, "slot:error");
  }
});
test("a delayed second asset cannot publish a partial batch or restart playing audio", async () => {
  const p = project({
    kind: "repl_output",
    output: {
      outputs: [],
      artifacts: [
        descriptor("audio", "audio-a"),
        descriptor("image", "image-b"),
      ],
    },
  });
  let finish;
  let reads = 0;
  let publications = 0;
  const pending = shared
    .loadReplMediaV2(
      p,
      async (ref) => {
        reads++;
        if (ref.kind === "image") await new Promise((r) => (finish = r));
        return new Blob([new Uint8Array(3)], { type: ref.mimeType });
      },
      new AbortController().signal,
    )
    .then((values) => {
      publications++;
      return values;
    });
  while (reads < 2) await new Promise((r) => setImmediate(r));
  assert.equal(publications, 0);
  finish();
  const values = await pending;
  assert.equal(publications, 1);
  assert.equal(values.length, 2);
  const g = guest(payload(p, values));
  const playing = g.children()[0];
  playing.currentTime = 12;
  await new Promise((r) => setImmediate(r));
  assert.equal(g.children()[0], playing);
  assert.equal(playing.currentTime, 12);
});
test("same client late bytes from previous conversation are aborted before publication", async () => {
  const p = project({
    kind: "repl_output",
    output: { outputs: [], artifacts: [descriptor("image", "image-a")] },
  });
  let finish;
  let publish = 0;
  const controller = new AbortController();
  const client = async (ref) => {
    await new Promise((r) => (finish = r));
    return new Blob([new Uint8Array(3)], { type: ref.mimeType });
  };
  const old = shared
    .loadReplMediaV2(p, client, controller.signal)
    .then(() => publish++);
  controller.abort();
  finish();
  await assert.rejects(old, { name: "AbortError" });
  assert.equal(publish, 0);
  const component = fs.readFileSync(
    path.join(
      base,
      "agi-stack/apps/desktop/src/features/chat/PlatformPluginToolResultSlots.tsx",
    ),
    "utf8",
  );
  assert.ok(
    component.includes("key={`${sessionKey}:${generation.meta.digest}:"),
  );
  assert.ok(component.includes("replMedia.ownerKey === ownerKey"));
});

test("formal ten MiB per-media limit yields unavailable without dropping surrounding text", () => {
  const output = {
    outputs: [
      { type: "text", text: "before" },
      { type: "text", text: "after" },
    ],
    artifacts: [descriptor("audio", "audio-huge", 10 * 1024 * 1024 + 1)],
    output_order: [
      { source: "text", index: 0 },
      { source: "media", index: 0 },
      { source: "text", index: 1 },
    ],
  };
  const p = project({ kind: "repl_output", output });
  assert.deepEqual(
    p.entries.map((x) => x.kind),
    ["text", "unavailable", "text"],
  );
  assert.equal(shared.replMediaReferencesV2(p).length, 0);
});
test("authenticated byte decoding enforces exact MIME, length, abort and bounded stream", async () => {
  const reference = {
    store: "conversation_tool_media",
    kind: "image",
    artifactId: "cloud-image",
    mimeType: "image/png",
    sizeBytes: 3,
  };
  const signal = new AbortController().signal;
  const response = () =>
    new Response(new Uint8Array([1, 2, 3]), {
      headers: { "content-type": "image/png", "content-length": "3" },
    });
  assert.equal(
    (await shared.readToolResultMediaResponseV2(response(), reference, signal))
      .size,
    3,
  );
  await assert.rejects(
    shared.readToolResultMediaResponseV2(
      response(),
      { ...reference, sizeBytes: 2 },
      signal,
    ),
  );
  await assert.rejects(
    shared.readToolResultMediaResponseV2(
      response(),
      { ...reference, mimeType: "image/jpeg" },
      signal,
    ),
  );
  const aborted = new AbortController();
  aborted.abort();
  await assert.rejects(
    shared.readToolResultMediaResponseV2(response(), reference, aborted.signal),
    { name: "AbortError" },
  );
});
test("Electron cloud media authority permits only the exact scoped binary GET", () => {
  const { authorizeCloudToolMediaEndpoint: authorize } = require(
    path.join(
      base,
      "agi-stack/apps/desktop/electron/main/cloudToolMediaEndpointPolicy.ts",
    ),
  );
  const pathName =
    "https://host.test/api/v1/agent/conversations/conversation/tool-media/cloud-image?tenant_id=tenant&project_id=project";
  const request = { method: "GET", response: { kind: "binary", max_bytes: 3 } };
  assert.deepEqual(authorize(request, new URL(pathName)), {
    kind: "project",
    tenantId: "tenant",
    projectId: "project",
    workspaceId: null,
    conversationId: "conversation",
  });
  for (const input of [
    { ...request, method: "POST" },
    { ...request, body: {} },
    { ...request, form: [] },
    { ...request, mutation: {} },
    {
      ...request,
      response: { kind: "binary", max_bytes: 10 * 1024 * 1024 + 1 },
    },
  ])
    assert.equal(authorize(input, new URL(pathName)), null);
  for (const suffix of ["&other=x", "&project_id=duplicate"])
    assert.equal(authorize(request, new URL(pathName + suffix)), null);
  assert.equal(
    authorize(
      request,
      new URL(pathName.replace("cloud-image", "..%2Fprivate")),
    ),
    null,
  );
});

test("cloud display entries retain bound cloud IDs and take precedence over native raw output", () => {
  const display = {
    kind: "repl_output",
    entries: [
      { kind: "text", text: "cloud-bound" },
      {
        kind: "image",
        store: "conversation_tool_media",
        artifactId: "artifact-real-cloud",
        mimeType: "image/png",
        sizeBytes: 3,
      },
    ],
  };
  const p = project({ kind: "repl_output", output: baseOutput, display });
  assert.equal(p.entries[1].store, "conversation_tool_media");
  assert.equal(p.entries[1].artifactId, "artifact-real-cloud");
  assert.equal(
    project({
      kind: "repl_output",
      output: baseOutput,
      display: {
        kind: "repl_output",
        entries: [{ kind: "image", artifactId: "invalid" }],
      },
    }).kind,
    "text",
  );
  const adapter = fs.readFileSync(
    path.join(base, "web/src/utils/sseEventAdapter.ts"),
    "utf8",
  );
  assert.ok(adapter.includes("validateReplOutputPresentationV2(data.display)"));
});
