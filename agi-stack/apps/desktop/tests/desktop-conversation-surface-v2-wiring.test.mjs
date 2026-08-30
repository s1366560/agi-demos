import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererConversationV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const surface = source('src/plugins/DesktopConversationSurfaceV2.tsx');
const workbench = source('src/plugins/DesktopWorkbenchSurfaceV2.tsx');
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

test('conversation canvas is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopConversationCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /data-conversation-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/chat\/(?:ChatPanel|PlatformPluginConversationSlots)|children|fallback|use(?:Layout)?Effect|useState|useReducer|useMemo|useAgentSocket|acquireOperationLease|meta\.digest|\bkey=/u,
  );

  assert.match(surface, /export type DesktopConversationInputV2/u);
  assert.match(surface, /export interface DesktopConversationSurfacePropsV2/u);
  assert.match(surface, /<ChatPanel \{\.\.\.input\} \/>/u);
  assert.match(surface, /<PlatformPluginConversationSlots active\s*\/>/u);
  assert.doesNotMatch(
    surface,
    /useAgentSocket|acquireOperationLease|meta\.digest|generation(?:Digest|Version)|\bkey=|use(?:Layout)?Effect|useState|useReducer/u,
  );

  assert.match(workbench, /DesktopRendererConversationV2/u);
  assert.match(workbench, /chatPanel:\s*DesktopConversationInputV2/u);
  assert.match(workbench, /<DesktopRendererConversationV2 input=\{view\.chatPanel\}\s*\/>/u);
  assert.doesNotMatch(
    workbench,
    /ComponentProps<typeof ChatPanel>|<ChatPanel\b|features\/chat\/ChatPanel|<PlatformPluginConversationSlots\b|features\/chat\/PlatformPluginConversationSlots/u,
  );
  assert.doesNotMatch(app, /<ChatPanel\b|<PlatformPluginConversationSlots\b/u);
});

test('conversation resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveConversationSurface/u);
  assert.match(compositionPort, /projectDesktopConversationCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_conversation_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_conversation_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_conversation_module_unavailable/u);
  assert.match(composition, /import \{ DesktopConversationSurfaceV2 \}/u);
  assert.match(composition, /validConversationDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'conversation_surface'/u);
  assert.match(composition, /definition\.id === 'conversation'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-conversation-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.conversation'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'conversation_surface'/u);
  assert.match(sharedSlotTypes, /\| 'conversation_surface'/u);
});

test('conversation contribution is ordered after activity and before production routes', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_CONVERSATION_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.conversation-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'conversation_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-conversation-surface'/u);

  const activityIndex = profile.indexOf('entry_id: builtin-desktop-activity-inbox-surface');
  const conversationIndex = profile.indexOf('entry_id: builtin-desktop-conversation-surface');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(activityIndex >= 0);
  assert.ok(conversationIndex > activityIndex);
  assert.ok(routesIndex > conversationIndex);
  const conversationEntry = profile.slice(conversationIndex, routesIndex);
  assert.match(conversationEntry, /id:\s*desktop\.conversation-surface/u);
  assert.match(conversationEntry, /order:\s*96/u);
  assert.match(conversationEntry, /desktop\.ui-slots\.conversation-surface\.v1/u);

  const conversationBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-conversation-surface',
  );
  assert.deepEqual(conversationBootstrap?.config, {
    id: 'desktop.conversation-surface',
    kind: 'ui-slot',
    order: 96,
    payload: {
      artifact_refs: ['desktop.ui-slots.conversation-surface.v1'],
      schema_version: 1,
    },
  });
});

test('conversation projection rejects missing, duplicate, wrong, and inactive generations', () => {
  const {
    DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2,
    projectDesktopConversationCompositionV2,
  } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopRendererCompositionPortV2.js');
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'conversation_surface',
    id: 'conversation',
    contract: 'ui-builtin:desktop-conversation-surface',
    moduleRef: DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2,
    permission: 'ui.conversation',
    sandbox: true,
  });
  function ConversationSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveConversationSurface: (definition) =>
      definition.moduleRef === DESKTOP_CONVERSATION_SURFACE_MODULE_REF_V2
        ? ConversationSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  assert.deepEqual(
    projectDesktopConversationCompositionV2(authority('ready', [slot]), port),
    Object.freeze({ status: 'ready', Surface: ConversationSurface }),
  );
  assert.deepEqual(
    projectDesktopConversationCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_conversation_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_conversation_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-conversation' }]),
      'desktop_renderer_conversation_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopConversationCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopConversationCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveConversationSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_conversation_module_unavailable',
    }),
  );
});
