import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererActivityInboxV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const surface = source('src/plugins/DesktopActivityInboxSurfaceV2.tsx');
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

test('activity inbox rendering is selected from one typed V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopActivityInboxCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.doesNotMatch(boundary, /ReactNode|children|fallback/u);

  assert.match(surface, /export type DesktopActivityInboxInputV2/u);
  assert.match(surface, /export interface DesktopActivityInboxSurfacePropsV2/u);
  assert.match(surface, /<ActivityInbox \{\.\.\.input\} \/>/u);

  assert.match(workbench, /DesktopRendererActivityInboxV2/u);
  assert.match(workbench, /activityInbox:\s*DesktopActivityInboxInputV2/u);
  assert.match(workbench, /<DesktopRendererActivityInboxV2 input=\{view\.activityInbox\}\s*\/>/u);
  assert.doesNotMatch(workbench, /ComponentProps<typeof ActivityInbox>|view\.inbox/u);
  assert.doesNotMatch(workbench, /<ActivityInbox\b/u);
  assert.doesNotMatch(workbench, /features\/activity\/ActivityInbox/u);

  assert.match(app, /kind:\s*'activity',[\s\S]*activityInbox:\s*\{/u);
  assert.doesNotMatch(app, /<ActivityInbox\b|ComponentProps<typeof ActivityInbox>/u);
});

test('activity inbox resolver validates the exact slot contract and fails closed', () => {
  assert.match(compositionPort, /DESKTOP_ACTIVITY_INBOX_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveActivityInboxSurface/u);
  assert.match(compositionPort, /projectDesktopActivityInboxCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_activity_inbox_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_activity_inbox_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_activity_inbox_module_unavailable/u);
  assert.match(composition, /import \{ DesktopActivityInboxSurfaceV2 \}/u);
  assert.match(composition, /validActivityInboxDefinitionV2/u);
  assert.match(composition, /slot === 'activity_inbox_surface'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-activity-inbox-surface'/u);
  assert.match(composition, /permission === 'ui\.activity-inbox'/u);
  assert.match(localSlotTypes, /\| 'activity_inbox_surface'/u);
  assert.match(sharedSlotTypes, /\| 'activity_inbox_surface'/u);
});

test('activity inbox is an ordered production artifact after workbench and before routes', () => {
  assert.match(
    artifactCatalog,
    /DESKTOP_ACTIVITY_INBOX_SURFACE_ARTIFACT_ID_V2\s*=\s*'desktop\.ui-slots\.activity-inbox-surface\.v1'/u,
  );
  assert.match(artifactCatalog, /slot:\s*'activity_inbox_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-activity-inbox-surface'/u);

  const workbenchIndex = profile.indexOf('entry_id: builtin-desktop-workbench-surface');
  const activityIndex = profile.indexOf('entry_id: builtin-desktop-activity-inbox-surface');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(workbenchIndex >= 0);
  assert.ok(activityIndex > workbenchIndex);
  assert.ok(routesIndex > activityIndex);
  const activityEntry = profile.slice(activityIndex, routesIndex);
  assert.match(activityEntry, /id:\s*desktop\.activity-inbox-surface/u);
  assert.match(activityEntry, /order:\s*95/u);
  assert.match(activityEntry, /desktop\.ui-slots\.activity-inbox-surface\.v1/u);

  const activityBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-activity-inbox-surface',
  );
  assert.deepEqual(activityBootstrap.config, {
    id: 'desktop.activity-inbox-surface',
    kind: 'ui-slot',
    order: 95,
    payload: {
      artifact_refs: ['desktop.ui-slots.activity-inbox-surface.v1'],
      schema_version: 1,
    },
  });
});
