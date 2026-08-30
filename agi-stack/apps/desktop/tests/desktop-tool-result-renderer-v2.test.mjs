import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const appCompositionSource = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const artifactCatalogSource = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const bridgeSource = source('src/features/chat/desktopToolResultRendererBridgeV2.ts');
const hostSource = source('src/features/chat/PlatformPluginToolResultSlots.tsx');
const moduleSource = source('src/plugins/desktopToolResultRendererModuleV2.ts');
const timelineSource = source('src/features/chat/ChatTimeline.tsx');
const electronViteSource = source('electron.vite.config.ts');
const rendererManifest = JSON.parse(
  readFileSync(
    new URL(
      '../../../../config/plugin-manifests-v2/memstack-renderer-contributions.v2.json',
      import.meta.url,
    ),
    'utf8',
  ),
);
const profile = readFileSync(
  new URL(
    '../../../../config/plugin-profiles/memstack-production-target-hosts.v2.yaml',
    import.meta.url,
  ),
  'utf8',
);
const bootstrap = JSON.parse(
  readFileSync(
    new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
    'utf8',
  ),
);

const compiledBridge =
  '/tmp/agistack-desktop-test-dist/src/features/chat/desktopToolResultRendererBridgeV2.js';
const compiledComposition =
  '/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererAppCompositionV2.js';
const compiledModule =
  '/tmp/agistack-desktop-test-dist/src/plugins/desktopToolResultRendererModuleV2.js';

const slot = Object.freeze({
  pluginId: 'builtin-ui',
  slot: 'tool_result_renderer',
  id: 'structured-tool-result',
  contract: 'ui-builtin:structured-tool-result',
  moduleRef: 'builtin:structured-tool-result',
  permission: 'ui.render',
  sandbox: true,
  sourceEntryId: 'builtin-desktop-tool-result-renderer',
  grantedPermissions: Object.freeze(['ui.render']),
});

function protocolV2() {
  return Object.freeze({
    decode: (value) => value,
    encode: (message) => Object.freeze({ source: 'memstack-plugin-slot', message }),
    isGuestForSlot: (message, slotId) =>
      typeof message === 'object' &&
      message !== null &&
      ['slot:ready', 'slot:resize', 'slot:action', 'slot:error'].includes(message.type) &&
      message.slotId === slotId,
  });
}

function payloadInput(overrides = {}) {
  return {
    resultId: 'observe-1',
    toolName: 'memory_search',
    status: 'complete',
    kind: 'search',
    resultLabel: 'Tool result',
    kindLabel: 'Searched',
    statusLabel: 'Complete',
    ...overrides,
  };
}

test('tool result renderer is an independent ordered contribution with an explicit grant', () => {
  assert.match(
    artifactCatalogSource,
    /DESKTOP_TOOL_RESULT_RENDERER_ARTIFACT_ID_V2\s*=\s*\n?\s*'desktop\.ui-slots\.tool-result-renderer\.v1'/u,
  );
  assert.match(artifactCatalogSource, /slot:\s*'tool_result_renderer'/u);
  assert.match(artifactCatalogSource, /moduleRef:\s*'builtin:structured-tool-result'/u);
  assert.match(artifactCatalogSource, /permission:\s*'ui\.render'/u);

  const conversationIndex = profile.indexOf('entry_id: builtin-desktop-conversation-renderer');
  const rendererIndex = profile.indexOf('entry_id: builtin-desktop-tool-result-renderer');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(conversationIndex >= 0);
  assert.ok(rendererIndex > conversationIndex);
  assert.ok(routesIndex > rendererIndex);
  const rendererEntry = profile.slice(rendererIndex, routesIndex);
  assert.match(rendererEntry, /id:\s*desktop\.tool-result-renderer/u);
  assert.match(rendererEntry, /order:\s*98/u);
  assert.match(rendererEntry, /desktop\.ui-slots\.tool-result-renderer\.v1/u);
  assert.match(rendererEntry, /permissions:\s*\n\s*- ui\.render/u);
  assert.deepEqual(rendererManifest.permissions, ['ui.conversation.renderer', 'ui.render']);

  const rendererBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-tool-result-renderer',
  );
  assert.deepEqual(rendererBootstrap?.config, {
    id: 'desktop.tool-result-renderer',
    kind: 'ui-slot',
    order: 98,
    payload: {
      artifact_refs: ['desktop.ui-slots.tool-result-renderer.v1'],
      schema_version: 1,
    },
  });
  assert.deepEqual(rendererBootstrap?.permissions, ['ui.render']);
});

test('tool result renderer resolver validates exact identity and profile-derived grant', () => {
  const { createDesktopRendererAppCompositionPortV2 } = require(compiledComposition);
  const { DESKTOP_TOOL_RESULT_RENDERER_MODULE_V2 } = require(compiledModule);
  const composition = createDesktopRendererAppCompositionPortV2({});

  assert.equal(
    composition.resolveToolResultRendererModule(slot),
    DESKTOP_TOOL_RESULT_RENDERER_MODULE_V2,
  );
  for (const candidate of [
    { ...slot, pluginId: 'other-ui' },
    { ...slot, slot: 'conversation_renderer' },
    { ...slot, id: 'other-renderer' },
    { ...slot, contract: 'ui-builtin:other-renderer' },
    { ...slot, moduleRef: 'builtin:other-renderer' },
    { ...slot, permission: 'ui.other' },
    { ...slot, sandbox: false },
    { ...slot, grantedPermissions: [] },
    { ...slot, grantedPermissions: ['ui.other'] },
  ]) {
    assert.equal(composition.resolveToolResultRendererModule(candidate), null);
  }
});

test('tool result renderer bridge rejects foreign traffic and every guest action', () => {
  const { DesktopToolResultRendererBridgeV2, createDesktopToolResultRendererPayloadV2 } = require(
    compiledBridge,
  );
  const posted = [];
  const frameWindow = {
    postMessage: (message, targetOrigin) => posted.push({ message, targetOrigin }),
  };
  const heights = [];
  const errors = [];
  const payload = createDesktopToolResultRendererPayloadV2(payloadInput());
  const bridge = new DesktopToolResultRendererBridgeV2({
    frameWindow,
    onError: (error) => errors.push(error),
    onResize: (height) => heights.push(height),
    payload,
    protocol: protocolV2(),
    slotId: slot.id,
  });
  const event = (message, overrides = {}) => ({
    data: message,
    origin: 'null',
    source: frameWindow,
    ...overrides,
  });

  assert.equal(
    bridge.handleMessage(event({ type: 'slot:ready', slotId: slot.id }, { source: {} })),
    false,
  );
  assert.equal(
    bridge.handleMessage(event({ type: 'slot:ready', slotId: slot.id }, { origin: 'file://' })),
    false,
  );
  assert.equal(bridge.handleMessage(event({ type: 'slot:ready', slotId: 'foreign-slot' })), false);
  assert.equal(bridge.handleMessage(event({ type: 'slot:ready', slotId: slot.id })), true);
  assert.equal(
    bridge.handleMessage(event({ type: 'slot:action', slotId: slot.id, name: 'read-result' })),
    true,
  );
  assert.deepEqual(errors, ['desktop_tool_result_renderer_action_rejected']);
  assert.equal(
    bridge.handleMessage(event({ type: 'slot:resize', slotId: slot.id, height: 88 })),
    true,
  );
  assert.deepEqual(heights, [88]);
  assert.deepEqual(posted, [
    {
      message: protocolV2().encode({
        type: 'slot:init',
        slotId: slot.id,
        payload,
      }),
      targetOrigin: '*',
    },
  ]);
});

test('tool result renderer sends typed updates and disposes exactly once', () => {
  const { DesktopToolResultRendererBridgeV2, createDesktopToolResultRendererPayloadV2 } = require(
    compiledBridge,
  );
  const posted = [];
  const frameWindow = {
    postMessage: (message, targetOrigin) => posted.push({ message, targetOrigin }),
  };
  const first = createDesktopToolResultRendererPayloadV2(payloadInput());
  const second = createDesktopToolResultRendererPayloadV2(
    payloadInput({
      resultId: 'observe-2',
      toolName: 'run_tests',
      status: 'failed',
      kind: 'check',
      kindLabel: 'Checked',
      statusLabel: 'Failed',
    }),
  );
  const bridge = new DesktopToolResultRendererBridgeV2({
    frameWindow,
    onError: () => undefined,
    onResize: () => undefined,
    payload: first,
    protocol: protocolV2(),
    slotId: slot.id,
  });

  bridge.updatePayload(second);
  assert.deepEqual(posted, []);
  bridge.activate();
  bridge.activate();
  bridge.handleMessage({
    data: { type: 'slot:ready', slotId: slot.id },
    origin: 'null',
    source: frameWindow,
  });
  bridge.updatePayload(first);
  bridge.dispose();
  bridge.dispose();

  assert.deepEqual(
    posted.map(({ message }) => message.message),
    [
      { type: 'slot:init', slotId: slot.id, payload: second },
      {
        type: 'slot:event',
        slotId: slot.id,
        name: 'tool-result',
        data: first,
      },
      { type: 'slot:dispose', slotId: slot.id },
    ],
  );
  assert.ok(posted.every(({ targetOrigin }) => targetOrigin === '*'));
});

test('tool result renderer payload is frozen and excludes result data', () => {
  const { createDesktopToolResultRendererPayloadV2 } = require(compiledBridge);
  const payload = createDesktopToolResultRendererPayloadV2(
    payloadInput({
      toolInput: { token: 'INPUT_SECRET' },
      toolOutput: { token: 'OUTPUT_SECRET' },
      display: { details: 'DISPLAY_SECRET' },
      content: 'CONTENT_SECRET',
    }),
  );
  assert.deepEqual(Object.keys(payload).sort(), [
    'kind',
    'kindLabel',
    'resultId',
    'resultLabel',
    'schemaVersion',
    'status',
    'statusLabel',
    'toolName',
  ]);
  assert.equal(payload.schemaVersion, 1);
  assert.equal(Object.isFrozen(payload), true);
  assert.doesNotMatch(
    JSON.stringify(payload),
    /INPUT_SECRET|OUTPUT_SECRET|DISPLAY_SECRET|CONTENT_SECRET|toolInput|toolOutput/u,
  );
});

test('host uses one opaque-origin srcDoc iframe with fixed CSP and shared protocol', () => {
  assert.match(hostSource, /@agistack\/plugin-slots/u);
  assert.match(hostSource, /sandbox="allow-scripts"/u);
  assert.match(hostSource, /onLoad=\{handleFrameLoad\}/u);
  assert.match(hostSource, /frameLoadedRef\.current/u);
  assert.match(hostSource, /bridgeRef\.current\?\.activate\(\)/u);
  assert.doesNotMatch(hostSource, /allow-same-origin|\ssrc=/u);
  assert.match(hostSource, /srcDoc=\{module\.srcDoc\}/u);
  assert.match(hostSource, /event\.source|handleMessage\(event\)/u);
  assert.match(hostSource, /bridge\.dispose\(\)/u);
  assert.match(moduleSource, /Content-Security-Policy/u);
  assert.match(moduleSource, /default-src 'none'/u);
  assert.match(moduleSource, /connect-src 'none'/u);
  assert.match(moduleSource, /slot:ready/u);
  assert.match(moduleSource, /slot:init/u);
  assert.match(moduleSource, /slot:event/u);
  assert.match(moduleSource, /slot:dispose/u);
  assert.doesNotMatch(
    hostSource + bridgeSource + moduleSource,
    /fetch\(|XMLHttpRequest|localStorage|sessionStorage|useAgentSocket|acquireOperationLease|generation(?:Digest|Version)|meta\.digest/u,
  );
  assert.match(electronViteSource, /'@agistack\/plugin-slots'/u);
});

test('timeline invokes the renderer only for result items and keeps raw evidence in the builtin owner', () => {
  assert.match(
    timelineSource,
    /import \{ PlatformPluginToolResultSlots \} from '\.\/PlatformPluginToolResultSlots'/u,
  );
  assert.match(timelineSource, /<PlatformPluginToolResultSlots/u);
  assert.match(timelineSource, /pair\.result \?\?/u);
  assert.match(timelineSource, /item\.type === 'observe'/u);
  assert.match(timelineSource, /<TimelinePayloadBlock[\s\S]*item\.toolOutput/u);
  assert.doesNotMatch(
    hostSource,
    /AgentTimelineItem|toolInput|toolOutput|fileMetadata|display\??\.|content\??\.|result:\s*unknown/u,
  );
  assert.match(appCompositionSource, /resolveToolResultRendererModule/u);
});
