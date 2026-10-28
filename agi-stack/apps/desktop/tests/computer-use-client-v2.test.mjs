import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
const require = createRequire(import.meta.url);
require.extensions[".css"] = () => {};
const {
  createComputerUseClientV2,
  computerUseConsentScopes,
} = require("/tmp/agistack-desktop-test-dist/src/api/computerUseClientV2.js");
const {
  timelineComputerUseScreenshot,
  timelineComputerUseScreenshots,
} = require("/tmp/agistack-desktop-test-dist/src/features/chat/chatTimelinePresentation.js");
const config = {
  mode: "cloud",
  tenantId: "tenant",
  projectId: "project",
  apiKey: "must-stay-out-of-device-request",
};
const snapshot = {
  plugin_id: "memstack-computer-use",
  device_id: "device",
  helper_available: true,
  scope: { tenant_id: "tenant", project_id: "project" },
  instance: { installed: true, enabled: false, revision: 0 },
  pending: [],
  grants: [],
  sessions: [],
};

test("permission buttons use native pending scopes and never widen a connector action", () => {
  assert.deepEqual(
    computerUseConsentScopes({
      capability: "calendar",
      scopes: ["once", "session", "always"],
    }),
    ["once", "session", "always"],
  );
  assert.deepEqual(
    computerUseConsentScopes({
      capability: "connector_action",
      scopes: ["once", "session", "always"],
    }),
    ["once"],
  );
  assert.deepEqual(
    computerUseConsentScopes({ capability: "microphone", scopes: ["once"] }),
    ["once"],
  );
  assert.deepEqual(computerUseConsentScopes(undefined), ["once"]);
  assert.deepEqual(computerUseConsentScopes({ scopes: ["unknown"] }), ["once"]);
});

test("cloud computer use management stays on the native authenticated device channel", async () => {
  const calls = [];
  const client = createComputerUseClientV2(config, async (command, args) => {
    calls.push({ command, args });
    return snapshot;
  });
  assert.equal((await client.snapshot()).instance.enabled, false);
  await client.manage({ action: "enable", expected_revision: 0 });
  assert.equal(calls[0].command, "computer_use_manage_v2");
  assert.equal(calls[0].args.input.credential, "");
  assert.equal(calls[1].args.input.operation.expected_revision, 0);
});
test("native device responses cannot switch project scope", async () => {
  const client = createComputerUseClientV2(config, async () => ({
    ...snapshot,
    scope: { ...snapshot.scope, project_id: "other" },
  }));
  await assert.rejects(client.snapshot(), /cua_snapshot_invalid/u);
});
test("artifact previews are authorized on demand and reject executable image sources", async () => {
  const client = createComputerUseClientV2(config, async () => ({
    artifact_id: "cua-image-a",
    data_url: "data:text/html;base64,AAA=",
  }));
  await assert.rejects(client.preview("cua-image-a"), /cua_preview_invalid/u);
});
test("computer-use screenshot timeline stores an artifact reference without base64", () => {
  const item = {
    toolOutput: JSON.stringify({
      app: "app",
      screenshot: {
        artifact_id: "cua-image-a",
        url: "cua-artifact:cua-image-a",
      },
    }),
    computerUse: { app: "app" },
  };
  const result = timelineComputerUseScreenshot(item);
  assert.equal(result.artifactId, "cua-image-a");
  assert.equal(result.dataUrl, "");
});
test("REPL image descriptors preserve order, deduplicate legacy screenshots and reject active content", () => {
  const artifact = (id, mime = "image/png") => ({kind: "image", artifact_id: id, mime_type: mime});
  const images = timelineComputerUseScreenshots({toolOutput: JSON.stringify({
    screenshot: {artifact_id: "cua-image-a"},
    artifacts: [artifact("cua-image-a"), artifact("cua-image-b", "image/webp"),
      artifact("cua-image-c", "image/svg+xml"), artifact("file:/private/image.png")],
  })});
  assert.deepEqual(images.map(image => image.artifactId), ["cua-image-a", "cua-image-b"]);
  assert.ok(images.every(image => image.dataUrl === ""));
});
test("audio preview reads only owner-scoped artifact chunks and validates byte offsets", async () => {
  const requests = [];
  const client = createComputerUseClientV2(config, async (_command, args) => {
    requests.push(args.input);
    return {
      artifact_id: "cua-audio-a",
      mime_type: "audio/wav",
      offset: 0,
      next_offset: 4,
      eof: true,
      data_base64: "UklGRg==",
    };
  });
  const audio = await client.audio("cua-audio-a");
  assert.equal(audio.size, 4);
  assert.equal(audio.type, "audio/wav");
  assert.equal(requests[0].operation.action, "audio_chunk");
  assert.equal(requests[0].operation.artifact_id, "cua-audio-a");
  assert.equal(requests[0].credential, "");
  const wrong = createComputerUseClientV2(config, async () => ({
    artifact_id: "cua-audio-a",
    mime_type: "audio/wav",
    offset: 0,
    next_offset: 8,
    eof: true,
    data_base64: "UklGRg==",
  }));
  await assert.rejects(wrong.audio("cua-audio-a"), /cua_audio_invalid/u);
});
test("audio preview preserves supported MIME types and rejects a MIME change between chunks", async () => {
  for (const mime of ["audio/mpeg", "audio/x-wav"]) {
    const client = createComputerUseClientV2(config, async () => ({
      artifact_id: "cua-audio-b", mime_type: mime, offset: 0,
      next_offset: 4, eof: true, data_base64: "UklGRg==",
    }));
    assert.equal((await client.audio("cua-audio-b")).type, mime);
  }
  let calls = 0;
  const changed = createComputerUseClientV2(config, async () => {
    const offset = calls++ * 4;
    return { artifact_id: "cua-audio-b", mime_type: offset ? "audio/mpeg" : "audio/wav",
      offset, next_offset: offset + 4, eof: offset > 0, data_base64: "UklGRg==" };
  });
  await assert.rejects(changed.audio("cua-audio-b"), /cua_audio_invalid/u);
});
test("account connection stays on native OAuth management without provider credentials", async () => {
  let request;
  const client = createComputerUseClientV2(config, async (_command, args) => {
    request = args.input;
    return snapshot;
  });
  await client.manage({
    action: "connector_connect",
    provider: "google",
    client_id: "public-client-id",
  });
  assert.equal(request.operation.client_id, "public-client-id");
  assert.equal(request.credential, "");
  assert.equal(request.operation.provider, "google");
});
