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

const appCompositionSource = source(
  'src/plugins/desktopRendererAppCompositionV2.tsx',
);
const artifactCatalogSource = source(
  'src/plugins/desktopRendererArtifactCatalogV2.ts',
);
const authorityProjectionSource = source(
  'src/plugins/desktopRendererAuthorityProjectionV2.ts',
);
const bridgeSource = source(
  'src/features/chat/desktopConversationRendererBridgeV2.ts',
);
const hostSource = source(
  'src/features/chat/PlatformPluginConversationSlots.tsx',
);
const moduleSource = source(
  'src/plugins/desktopConversationRendererModuleV2.ts',
);
const surfaceSource = source('src/plugins/DesktopConversationSurfaceV2.tsx');
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
    new URL(
      '../../../../shared/profiles/memstack-default-bootstrap.v2.json',
      import.meta.url,
    ),
    'utf8',
  ),
);

const compiledBridge =
  '/tmp/agistack-desktop-test-dist/src/features/chat/desktopConversationRendererBridgeV2.js';
const compiledComposition =
  '/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererAppCompositionV2.js';
const compiledModule =
  '/tmp/agistack-desktop-test-dist/src/plugins/desktopConversationRendererModuleV2.js';

const slot = Object.freeze({
  pluginId: 'builtin-shell',
  slot: 'conversation_renderer',
  id: 'conversation-renderer',
  contract: 'ui-builtin:desktop-conversation-renderer',
  moduleRef: 'builtin:desktop-conversation-renderer',
  permission: 'ui.conversation.renderer',
  sandbox: true,
  sourceEntryId: 'builtin-desktop-conversation-renderer',
  grantedPermissions: Object.freeze(['ui.conversation.renderer']),
});

function protocolV2() {
  return Object.freeze({
    decode: (value) => value,
    encode: (message) =>
      Object.freeze({ source: 'memstack-plugin-slot', message }),
    isGuestForSlot: (message, slotId) =>
      typeof message === 'object' &&
      message !== null &&
      ['slot:ready', 'slot:resize', 'slot:action', 'slot:error'].includes(
        message.type,
      ) &&
      message.slotId === slotId,
  });
}

test('conversation renderer is an independent ordered contribution with an explicit grant', () => {
  assert.match(
    artifactCatalogSource,
    /DESKTOP_CONVERSATION_RENDERER_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.conversation-renderer\.v1'/u,
  );
  assert.match(artifactCatalogSource, /slot:\s*'conversation_renderer'/u);
  assert.match(
    artifactCatalogSource,
    /moduleRef:\s*'builtin:desktop-conversation-renderer'/u,
  );
  assert.match(
    artifactCatalogSource,
    /permission:\s*'ui\.conversation\.renderer'/u,
  );

  const surfaceIndex = profile.indexOf(
    'entry_id: builtin-desktop-conversation-surface',
  );
  const rendererIndex = profile.indexOf(
    'entry_id: builtin-desktop-conversation-renderer',
  );
  const routesIndex = profile.indexOf(
    'entry_id: builtin-desktop-tenant-creation-routes',
  );
  assert.ok(surfaceIndex >= 0);
  assert.ok(rendererIndex > surfaceIndex);
  assert.ok(routesIndex > rendererIndex);
  const rendererEntry = profile.slice(rendererIndex, routesIndex);
  assert.match(rendererEntry, /id:\s*desktop\.conversation-renderer/u);
  assert.match(rendererEntry, /order:\s*97/u);
  assert.match(rendererEntry, /desktop\.ui-slots\.conversation-renderer\.v1/u);
  assert.match(
    rendererEntry,
    /permissions:\s*\n\s*- ui\.conversation\.renderer/u,
  );
  assert.deepEqual(rendererManifest.permissions, ['ui.conversation.renderer', 'ui.render']);

  const rendererBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) =>
      entryId === 'builtin-desktop-conversation-renderer',
  );
  assert.deepEqual(rendererBootstrap?.config, {
    id: 'desktop.conversation-renderer',
    kind: 'ui-slot',
    order: 97,
    payload: {
      artifact_refs: ['desktop.ui-slots.conversation-renderer.v1'],
      schema_version: 1,
    },
  });
  assert.deepEqual(rendererBootstrap?.permissions, [
    'ui.conversation.renderer',
  ]);
});

test('conversation renderer resolver validates exact identity and profile-derived grant', () => {
  const { createDesktopRendererAppCompositionPortV2 } = require(
    compiledComposition,
  );
  const { DESKTOP_CONVERSATION_RENDERER_MODULE_V2 } = require(compiledModule);
  const composition = createDesktopRendererAppCompositionPortV2({});

  assert.equal(
    composition.resolveConversationRendererModule(slot),
    DESKTOP_CONVERSATION_RENDERER_MODULE_V2,
  );
  for (const candidate of [
    { ...slot, pluginId: 'other-shell' },
    { ...slot, slot: 'tool_result_renderer' },
    { ...slot, id: 'other-renderer' },
    { ...slot, contract: 'ui-builtin:other-renderer' },
    { ...slot, moduleRef: 'builtin:other-renderer' },
    { ...slot, permission: 'ui.conversation.other' },
    { ...slot, sandbox: false },
    { ...slot, grantedPermissions: [] },
    { ...slot, grantedPermissions: ['ui.conversation.other'] },
  ]) {
    assert.equal(
      composition.resolveConversationRendererModule(candidate),
      null,
    );
  }
});

test('authority projection attaches only the source entry grants to slot definitions', () => {
  assert.match(authorityProjectionSource, /generation\.snapshot\.entries/u);
  assert.match(authorityProjectionSource, /sourceEntryId/u);
  assert.match(authorityProjectionSource, /grantedPermissions/u);
  assert.doesNotMatch(
    authorityProjectionSource,
    /definition\.permission\s*\]/u,
  );
  assert.match(appCompositionSource, /resolveConversationRendererModule/u);
  assert.match(
    appCompositionSource,
    /grantedPermissions\.includes\(definition\.permission\)/u,
  );
});

test('conversation renderer bridge rejects foreign traffic and allows only open-commands', () => {
  const {
    DesktopConversationRendererBridgeV2,
    createDesktopConversationRendererPayloadV2,
  } = require(compiledBridge);
  const posted = [];
  const frameWindow = {
    postMessage: (message, targetOrigin) =>
      posted.push({ message, targetOrigin }),
  };
  const actions = [];
  const heights = [];
  const errors = [];
  const payload = createDesktopConversationRendererPayloadV2({
    commandsLabel: 'Commands',
    conversationId: 'conversation-1',
    disabled: false,
    messageCount: 4,
    sending: true,
    workflowTarget: 'plan',
  });
  const bridge = new DesktopConversationRendererBridgeV2({
    frameWindow,
    onAction: (action) => actions.push(action),
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
    bridge.handleMessage(
      event({ type: 'slot:ready', slotId: slot.id }, { source: {} }),
    ),
    false,
  );
  assert.equal(
    bridge.handleMessage(
      event({ type: 'slot:ready', slotId: slot.id }, { origin: 'file://' }),
    ),
    false,
  );
  assert.equal(
    bridge.handleMessage(event({ type: 'slot:ready', slotId: 'foreign-slot' })),
    false,
  );
  assert.equal(
    bridge.handleMessage(event({ type: 'slot:ready', slotId: slot.id })),
    true,
  );
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

  assert.equal(
    bridge.handleMessage(
      event({
        type: 'slot:action',
        slotId: slot.id,
        name: 'read-message-content',
      }),
    ),
    true,
  );
  assert.deepEqual(actions, []);
  assert.deepEqual(errors, ['desktop_conversation_renderer_action_rejected']);
  assert.equal(
    bridge.handleMessage(
      event({ type: 'slot:action', slotId: slot.id, name: 'open-commands' }),
    ),
    true,
  );
  assert.deepEqual(actions, ['open-commands']);
  assert.equal(
    bridge.handleMessage(
      event({ type: 'slot:resize', slotId: slot.id, height: 88 }),
    ),
    true,
  );
  assert.deepEqual(heights, [88]);
});

test('conversation renderer sends typed updates and disposes exactly once', () => {
  const {
    DesktopConversationRendererBridgeV2,
    createDesktopConversationRendererPayloadV2,
  } = require(compiledBridge);
  const posted = [];
  const frameWindow = {
    postMessage: (message, targetOrigin) =>
      posted.push({ message, targetOrigin }),
  };
  const first = createDesktopConversationRendererPayloadV2({
    commandsLabel: 'Commands',
    conversationId: 'conversation-1',
    disabled: false,
    messageCount: 4,
    sending: false,
    workflowTarget: 'changes',
  });
  const second = createDesktopConversationRendererPayloadV2({
    commandsLabel: 'Commands',
    conversationId: 'conversation-1',
    disabled: true,
    messageCount: 5,
    sending: true,
    workflowTarget: 'artifacts',
  });
  const bridge = new DesktopConversationRendererBridgeV2({
    frameWindow,
    onAction: () => undefined,
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
        name: 'conversation-state',
        data: first,
      },
      { type: 'slot:dispose', slotId: slot.id },
    ],
  );
  assert.ok(posted.every(({ targetOrigin }) => targetOrigin === '*'));
});

test('conversation renderer payload is frozen, typed, and excludes content and callbacks', () => {
  const { createDesktopConversationRendererPayloadV2 } = require(
    compiledBridge,
  );
  const payload = createDesktopConversationRendererPayloadV2({
    commandsLabel: 'Commands',
    conversationId: 'conversation-1',
    disabled: false,
    messageCount: 4,
    sending: true,
    workflowTarget: 'plan',
  });
  assert.deepEqual(Object.keys(payload).sort(), [
    'commandsLabel',
    'conversationId',
    'disabled',
    'messageCount',
    'schemaVersion',
    'sending',
    'workflowTarget',
  ]);
  assert.equal(payload.schemaVersion, 1);
  assert.equal(Object.isFrozen(payload), true);
  assert.doesNotMatch(
    JSON.stringify(payload),
    /content|callback|messageBody|onOpenCommands/u,
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
  assert.match(moduleSource, /slot:ready/u);
  assert.match(moduleSource, /slot:init/u);
  assert.match(moduleSource, /slot:event/u);
  assert.match(moduleSource, /slot:dispose/u);
  assert.match(moduleSource, /slot:action/u);
  assert.match(moduleSource, /open-commands/u);
  assert.doesNotMatch(
    moduleSource,
    /fetch\(|XMLHttpRequest|localStorage|sessionStorage/u,
  );
  assert.match(electronViteSource, /'@agistack\/plugin-slots'/u);
});

test('surface forwards only structural conversation state and keeps the socket lease owner intact', () => {
  assert.match(
    surfaceSource,
    /conversationId=\{input\.selectedConversationId/u,
  );
  assert.match(surfaceSource, /messageCount=\{input\.messages\.length\}/u);
  assert.match(
    surfaceSource,
    /workflowTarget=\{input\.activeWorkflowTarget\}/u,
  );
  assert.match(surfaceSource, /sending=\{input\.sending\}/u);
  assert.match(surfaceSource, /disabled=\{Boolean\(input\.disabledReason\)\}/u);
  assert.match(surfaceSource, /onOpenCommands=\{input\.onOpenCommands\}/u);
  assert.doesNotMatch(
    hostSource + bridgeSource + moduleSource,
    /useAgentSocket|acquireOperationLease|generation(?:Digest|Version)|meta\.digest|key=\{[^}]*conversationId|key=\{[^}]*generation|message\.content/u,
  );
});
