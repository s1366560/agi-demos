import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererNewThreadComposerV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const surface = source('src/plugins/DesktopNewThreadComposerSurfaceV2.tsx');
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

test('new-thread rendering is selected from one typed V2 composer surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopNewThreadComposerCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /data-new-thread-composer-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/task\/NewThreadComposer|ReactNode|children|fallback|use(?:Layout)?Effect|useState|useReducer|useMemo/u,
  );

  assert.match(surface, /export type DesktopNewThreadComposerInputV2/u);
  assert.match(surface, /export interface DesktopNewThreadComposerSurfacePropsV2/u);
  assert.match(
    surface,
    /<NewThreadComposer key=\{input\.scopeKey\} \{\.\.\.input\.composer\} \/>/u,
  );

  assert.match(workbench, /DesktopRendererNewThreadComposerV2/u);
  assert.match(workbench, /newThreadComposer:\s*DesktopNewThreadComposerInputV2/u);
  assert.match(
    workbench,
    /<DesktopRendererNewThreadComposerV2 input=\{view\.newThreadComposer\}\s*\/>/u,
  );
  assert.doesNotMatch(
    workbench,
    /ComponentProps<typeof NewThreadComposer>|view\.composer|composerScopeKey/u,
  );
  assert.doesNotMatch(workbench, /<NewThreadComposer\b|features\/task\/NewThreadComposer/u);

  assert.match(
    app,
    /kind:\s*'home',[\s\S]*newThreadComposer:\s*\{[\s\S]*scopeKey:\s*newThreadComposerScopeKey,[\s\S]*composer:\s*\{/u,
  );
  assert.doesNotMatch(app, /<NewThreadComposer\b|ComponentProps<typeof NewThreadComposer>/u);
});

test('new-thread composer resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_NEW_THREAD_COMPOSER_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveNewThreadComposerSurface/u);
  assert.match(compositionPort, /projectDesktopNewThreadComposerCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_new_thread_composer_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_new_thread_composer_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_new_thread_composer_module_unavailable/u);
  assert.match(composition, /import \{ DesktopNewThreadComposerSurfaceV2 \}/u);
  assert.match(composition, /validNewThreadComposerDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'new_thread_composer_surface'/u);
  assert.match(composition, /definition\.id === 'new-thread-composer'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-new-thread-composer-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_NEW_THREAD_COMPOSER_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.new-thread-composer'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'new_thread_composer_surface'/u);
  assert.match(sharedSlotTypes, /\| 'new_thread_composer_surface'/u);
});

test('new-thread composer is ordered after workbench and before My Work', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_NEW_THREAD_COMPOSER_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.new-thread-composer-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'new_thread_composer_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-new-thread-composer-surface'/u);

  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  const composerIndex = profile.indexOf('entry_id: builtin-desktop-new-thread-composer-surface');
  const myWorkIndex = profile.indexOf('entry_id: builtin-desktop-my-work-queue-surface');
  const activityIndex = profile.indexOf('entry_id: builtin-desktop-activity-inbox-surface');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(workbenchIndex >= 0);
  assert.ok(composerIndex > workbenchIndex);
  assert.ok(myWorkIndex > composerIndex);
  assert.ok(activityIndex > myWorkIndex);
  assert.ok(routesIndex > activityIndex);
  const composerEntry = profile.slice(composerIndex, myWorkIndex);
  assert.match(composerEntry, /id:\s*desktop\.new-thread-composer-surface/u);
  assert.match(composerEntry, /order:\s*93/u);
  assert.match(composerEntry, /desktop\.ui-slots\.new-thread-composer-surface\.v1/u);

  const composerBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-new-thread-composer-surface',
  );
  assert.deepEqual(composerBootstrap?.config, {
    id: 'desktop.new-thread-composer-surface',
    kind: 'ui-slot',
    order: 93,
    payload: {
      artifact_refs: ['desktop.ui-slots.new-thread-composer-surface.v1'],
      schema_version: 1,
    },
  });
});
