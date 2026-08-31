import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function compiledPlugin(fileName) {
  const nested = `/tmp/agistack-desktop-test-dist/apps/desktop/src/plugins/${fileName}`;
  return existsSync(nested) ? nested : `/tmp/agistack-desktop-test-dist/src/plugins/${fileName}`;
}

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const artifactCatalog = source('src/plugins/desktopRendererArtifactCatalogV2.ts');
const boundary = source('src/plugins/DesktopRendererNewTaskFlowV2.tsx');
const composition = source('src/plugins/desktopRendererAppCompositionV2.tsx');
const compositionPort = source('src/plugins/desktopRendererCompositionPortV2.ts');
const flow = source('src/features/task/NewTaskFlow.tsx');
const localSlotTypes = source('src/plugins/uiSlotRegistry.ts');
const noProjectQa = source('src/qa/NoProjectEntryQa.tsx');
const shell = source('src/plugins/DesktopAuthenticatedShellSurfaceV2.tsx');
const sharedSlotTypes = source('../../packages/plugin-slots/src/types.ts');
const standaloneQa = source('src/qa/NewTaskFlowQa.tsx');
const surface = source('src/plugins/DesktopNewTaskFlowSurfaceV2.tsx');
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

test('new task flow is selected from one typed pinned-generation V2 surface', () => {
  assert.match(boundary, /useDesktopRendererGenerationV2\(\)/u);
  assert.match(boundary, /projectDesktopNewTaskFlowCompositionV2/u);
  assert.match(boundary, /<Surface input=\{input\}\s*\/>/u);
  assert.match(boundary, /if \(!input\.open\) return null/u);
  assert.match(boundary, /createPortal\(/u);
  assert.match(boundary, /className="new-task-backdrop"/u);
  assert.match(boundary, /data-new-task-flow-state=\{composition\.status\}/u);
  assert.match(boundary, /data-reason-code=\{loading \? undefined : composition\.reasonCode\}/u);
  assert.match(boundary, /onClick=\{input\.onClose\}/u);
  assert.doesNotMatch(
    boundary,
    /features\/task\/NewTaskFlow|NewTaskDefinitionStage|NewTaskPlanningStage|NewTaskReviewStage|fallback|acquireOperationLease|meta\.digest|generation(?:Digest|Version)|\bkey=/u,
  );
  assert.doesNotMatch(boundary, /use(?:Layout)?Effect|useState|useReducer|useMemo|useRef/u);

  assert.match(surface, /export type DesktopNewTaskFlowInputV2/u);
  assert.match(surface, /ComponentProps<typeof NewTaskFlow>/u);
  assert.match(surface, /export interface DesktopNewTaskFlowSurfacePropsV2/u);
  assert.match(surface, /<NewTaskFlow \{\.\.\.input\}\s*\/>/u);
  assert.doesNotMatch(surface, /useDesktopRendererGenerationV2|acquireOperationLease/u);
  assert.doesNotMatch(surface, /\bkey=|use(?:Layout)?Effect|useState|useReducer|useMemo|useRef/u);

  assert.match(shell, /DesktopRendererNewTaskFlowV2/u);
  assert.match(shell, /newTask:\s*DesktopNewTaskFlowInputV2/u);
  assert.match(shell, /<DesktopRendererNewTaskFlowV2\s+input=\{surfaces\.newTask\}/u);
  assert.doesNotMatch(shell, /<NewTaskFlow\b/u);
  assert.doesNotMatch(shell, /features\/task\/NewTaskFlow/u);
  assert.doesNotMatch(app, /<NewTaskFlow\b/u);
});

test('new task flow resolver validates the exact builtin same-realm slot contract', () => {
  assert.match(compositionPort, /DESKTOP_NEW_TASK_FLOW_SURFACE_MODULE_REF_V2/u);
  assert.match(compositionPort, /resolveNewTaskFlowSurface/u);
  assert.match(compositionPort, /projectDesktopNewTaskFlowCompositionV2/u);
  assert.match(compositionPort, /desktop_renderer_new_task_flow_contribution_missing/u);
  assert.match(compositionPort, /desktop_renderer_new_task_flow_contribution_ambiguous/u);
  assert.match(compositionPort, /desktop_renderer_new_task_flow_module_unavailable/u);
  assert.match(composition, /import \{ DesktopNewTaskFlowSurfaceV2 \}/u);
  assert.match(composition, /validNewTaskFlowDefinitionV2/u);
  assert.match(composition, /definition\.pluginId === 'builtin-shell'/u);
  assert.match(composition, /slot === 'new_task_flow_surface'/u);
  assert.match(composition, /definition\.id === 'new-task-flow'/u);
  assert.match(composition, /contract === 'ui-builtin:desktop-new-task-flow-surface'/u);
  assert.match(composition, /definition\.moduleRef === DESKTOP_NEW_TASK_FLOW_SURFACE_MODULE_REF_V2/u);
  assert.match(composition, /permission === 'ui\.new-task-flow'/u);
  assert.match(composition, /definition\.sandbox/u);
  assert.match(localSlotTypes, /\| 'new_task_flow_surface'/u);
  assert.match(sharedSlotTypes, /\| 'new_task_flow_surface'/u);
});

test('new task flow contribution is explicit in the production profile and catalog', () => {
  const artifactDeclaration = new RegExp(
    String.raw`DESKTOP_NEW_TASK_FLOW_SURFACE_ARTIFACT_ID_V2\s*=\s*\n?\s*` +
      String.raw`'desktop\.ui-slots\.new-task-flow-surface\.v1'`,
    'u',
  );
  assert.match(artifactCatalog, artifactDeclaration);
  assert.match(artifactCatalog, /slot:\s*'new_task_flow_surface'/u);
  assert.match(artifactCatalog, /moduleRef:\s*'builtin:desktop-new-task-flow-surface'/u);

  const rightSidebarIndex = profile.indexOf('entry_id: builtin-desktop-right-sidebar-surface');
  const newTaskFlowIndex = profile.indexOf('entry_id: builtin-desktop-new-task-flow-surface');
  const routesIndex = profile.indexOf('entry_id: builtin-desktop-tenant-creation-routes');
  assert.ok(rightSidebarIndex >= 0);
  assert.ok(newTaskFlowIndex > rightSidebarIndex);
  assert.ok(routesIndex > newTaskFlowIndex);
  const newTaskFlowEntry = profile.slice(newTaskFlowIndex, routesIndex);
  assert.match(newTaskFlowEntry, /id:\s*desktop\.new-task-flow-surface/u);
  assert.match(newTaskFlowEntry, /order:\s*101/u);
  assert.match(newTaskFlowEntry, /desktop\.ui-slots\.new-task-flow-surface\.v1/u);

  const newTaskFlowBootstrap = bootstrap.entries.find(
    ({ entry_id: entryId }) => entryId === 'builtin-desktop-new-task-flow-surface',
  );
  assert.deepEqual(newTaskFlowBootstrap?.config, {
    id: 'desktop.new-task-flow-surface',
    kind: 'ui-slot',
    order: 101,
    payload: {
      artifact_refs: ['desktop.ui-slots.new-task-flow-surface.v1'],
      schema_version: 1,
    },
  });
});

test('new task flow projection rejects malformed, duplicate, and inactive generations', () => {
  const {
    DESKTOP_NEW_TASK_FLOW_SURFACE_MODULE_REF_V2,
    projectDesktopNewTaskFlowCompositionV2,
  } = require(compiledPlugin('desktopRendererCompositionPortV2.js'));
  const slot = Object.freeze({
    pluginId: 'builtin-shell',
    slot: 'new_task_flow_surface',
    id: 'new-task-flow',
    contract: 'ui-builtin:desktop-new-task-flow-surface',
    moduleRef: DESKTOP_NEW_TASK_FLOW_SURFACE_MODULE_REF_V2,
    permission: 'ui.new-task-flow',
    sandbox: true,
  });
  function NewTaskFlowSurface() {
    return null;
  }
  const port = Object.freeze({
    resolveNewTaskFlowSurface: (definition) =>
      definition.moduleRef === DESKTOP_NEW_TASK_FLOW_SURFACE_MODULE_REF_V2
        ? NewTaskFlowSurface
        : null,
  });
  const authority = (status, slotDefinitions) => Object.freeze({ status, slotDefinitions });

  const ready = projectDesktopNewTaskFlowCompositionV2(authority('ready', [slot]), port);
  assert.deepEqual(ready, Object.freeze({ status: 'ready', Surface: NewTaskFlowSurface }));
  const unrelated = projectDesktopNewTaskFlowCompositionV2(
    authority('ready', [slot, { ...slot, slot: 'workbench_surface', id: 'unrelated' }]),
    port,
  );
  assert.equal(unrelated.status, 'ready');
  assert.equal(unrelated.Surface, ready.Surface);
  assert.deepEqual(
    projectDesktopNewTaskFlowCompositionV2(authority('loading', []), port),
    Object.freeze({ status: 'loading' }),
  );
  for (const [state, reasonCode] of [
    [authority('ready', []), 'desktop_renderer_new_task_flow_contribution_missing'],
    [
      authority('ready', [slot, { ...slot, id: 'duplicate' }]),
      'desktop_renderer_new_task_flow_contribution_ambiguous',
    ],
    [
      authority('ready', [{ ...slot, moduleRef: 'builtin:wrong-new-task-flow' }]),
      'desktop_renderer_new_task_flow_module_unavailable',
    ],
    [authority('unavailable', []), 'desktop_renderer_generation_unavailable'],
    [authority('disabled', []), 'desktop_renderer_generation_disabled'],
  ]) {
    assert.deepEqual(
      projectDesktopNewTaskFlowCompositionV2(state, port),
      Object.freeze({ status: 'unavailable', reasonCode }),
    );
  }
  assert.deepEqual(
    projectDesktopNewTaskFlowCompositionV2(
      authority('ready', [slot]),
      Object.freeze({ resolveNewTaskFlowSurface: () => null }),
    ),
    Object.freeze({
      status: 'unavailable',
      reasonCode: 'desktop_renderer_new_task_flow_module_unavailable',
    }),
  );
});

test('new task flow seam preserves App ownership, modal lifecycles, and QA harnesses', () => {
  assert.match(app, /const \[newTaskOpen, setNewTaskOpen\] = useState\(false\)/u);
  assert.match(app, /const \[newTaskResumeDraft, setNewTaskResumeDraft\]/u);
  assert.match(app, /newTask:\s*\{[\s\S]*open:\s*newTaskOpen/u);
  assert.match(app, /workspaceAuthority:\s*newTaskWorkspaceAuthority/u);
  assert.match(app, /onSessionPersisted:\s*persistNewTaskSession/u);
  assert.match(app, /onSessionReady:\s*activateNewTaskSession/u);
  assert.match(app, /onRunAgentTurn:\s*runNewTaskAgentTurn/u);
  assert.match(app, /onOpenRuntimeSettings:\s*\(\) => \{[\s\S]*setNewTaskOpen\(false\)/u);

  assert.match(flow, /const \[phase, setPhase\] = useState<NewTaskFlowPhase>\('define'\)/u);
  assert.match(flow, /const flowEpochRef = useRef\(0\)/u);
  assert.match(flow, /const previousFocusRef = useRef<HTMLElement \| null>\(null\)/u);
  assert.match(flow, /document\.addEventListener\('keydown', handleKeyDown\)/u);
  assert.match(flow, /window\.setTimeout\(\(\) => previousFocusRef\.current\?\.focus\(\), 0\)/u);
  assert.match(flow, /abortController\.abort\(\)/u);
  assert.match(flow, /if \(!open\) return null/u);
  assert.match(flow, /return createPortal\(/u);

  assert.match(standaloneQa, /<NewTaskFlow\b/u);
  assert.match(noProjectQa, /<NewTaskFlow\b/u);
  assert.doesNotMatch(boundary, /<NewTaskFlow\b|NewTaskResumeDraft|NewTaskAgentTurnInput|fallback/u);
});
