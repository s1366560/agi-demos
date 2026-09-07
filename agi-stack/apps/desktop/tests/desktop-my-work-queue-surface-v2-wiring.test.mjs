import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererMyWorkQueueV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const surface = source('src/plugins/DesktopMyWorkQueueSurfaceV2.tsx');
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

test('My Work rendering is selected from one typed V2 queue surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopMyWorkQueueCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.doesNotMatch(
    boundary,
    /features\/my-work\/MyWorkQueue|ReactNode|children|fallback|use(?:Layout)?Effect|useState|useReducer|useMemo/u,
  );

  assert.match(surface, /export type DesktopMyWorkQueueInputV2/u);
  assert.match(surface, /export interface DesktopMyWorkQueueSurfacePropsV2/u);
  assert.match(surface, /<MyWorkQueue \{\.\.\.input\} \/>/u);

  assert.match(workbench, /DesktopRendererMyWorkQueueV2/u);
  assert.match(workbench, /myWorkQueue:\s*DesktopMyWorkQueueInputV2/u);
  assert.match(workbench, /<DesktopRendererMyWorkQueueV2 input=\{view\.myWorkQueue\}\s*\/>/u);
  assert.doesNotMatch(workbench, /ComponentProps<typeof MyWorkQueue>|view\.queue/u);
  assert.doesNotMatch(workbench, /<MyWorkQueue\b/u);
  assert.doesNotMatch(workbench, /features\/my-work\/MyWorkQueue/u);

  assert.match(app, /kind:\s*'board',[\s\S]*myWorkQueue:\s*\{/u);
  assert.doesNotMatch(app, /<MyWorkQueue\b|ComponentProps<typeof MyWorkQueue>/u);
});

test('My Work queue resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_MY_WORK_QUEUE_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveMyWorkQueueSurface/u);
  assert.match(compositionPort, /projectDesktopMyWorkQueueCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_my_work_queue_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_my_work_queue_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_my_work_queue_module_unavailable/u);
  assert.match(composition, /import \{ DesktopMyWorkQueueSurfaceV2 \}/u);
  assert.match(composition, /validMyWorkQueueDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'my_work_queue_surface'/u);
  assert.match(composition, /definition\.id === 'my-work-queue'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-my-work-queue-surface'/u);
  assert.match(
    composition,
    /definition\.moduleRef === DESKTOP_MY_WORK_QUEUE_SURFACE_MODULE_REF_V2/u,
  );
  assert.match(composition, /permission === 'ui\.my-work-queue'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'my_work_queue_surface'/u);
  assert.match(sharedSlotTypes, /\| 'my_work_queue_surface'/u);
});

test('My Work queue is ordered after workbench and before activity inbox', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_MY_WORK_QUEUE_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.my-work-queue-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'my_work_queue_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-my-work-queue-surface'/u);

  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  const myWorkIndex = profile.indexOf('entry_id: builtin-desktop-my-work-queue-surface');
  const activityIndex = profile.indexOf('entry_id: builtin-desktop-activity-inbox-surface');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(workbenchIndex >= 0);
  assert.ok(myWorkIndex > workbenchIndex);
  assert.ok(activityIndex > myWorkIndex);
  assert.ok(routesIndex > activityIndex);
  const myWorkEntry = profile.slice(myWorkIndex, activityIndex);
  assert.match(myWorkEntry, /id:\s*desktop\.my-work-queue-surface/u);
  assert.match(myWorkEntry, /order:\s*94/u);
  assert.match(myWorkEntry, /desktop\.ui-slots\.my-work-queue-surface\.v1/u);

  const myWorkBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-my-work-queue-surface',
  );
  assert.deepEqual(myWorkBootstrap.config, {
    id: 'desktop.my-work-queue-surface',
    kind: 'ui-slot',
    order: 94,
    payload: {
      artifact_refs: ['desktop.ui-slots.my-work-queue-surface.v1'],
      schema_version: 1,
    },
  });
});
