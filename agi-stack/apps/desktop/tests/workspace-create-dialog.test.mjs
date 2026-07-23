import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const dialogSource = readFileSync(
  new URL('../src/features/workspace/WorkspaceCreateDialog.tsx', import.meta.url),
  'utf8',
);
const sidebarSource = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.tsx', import.meta.url),
  'utf8',
);
const dockSource = readFileSync(
  new URL('../src/features/workspace/WorkspaceDock.tsx', import.meta.url),
  'utf8',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const qaSource = readFileSync(new URL('../src/qa/WorkspaceCreateQa.tsx', import.meta.url), 'utf8');

test('workspace create dialog exposes explicit fields, accessible radios, and discard protection', () => {
  assert.match(dialogSource, /<Dialog\.Root/);
  assert.match(dialogSource, /<AlertDialog\.Root/);
  assert.match(dialogSource, /role="radiogroup"/);
  assert.match(dialogSource, /workspaceCreateRadioNextValue/);
  assert.match(dialogSource, /aria-live=/);
  assert.match(dialogSource, /AbortController/);
  assert.match(dialogSource, /if \(busy \|\| requestRef\.current\) return/);
  assert.match(dialogSource, /validateWorkspaceCreateDraft/);
  assert.match(dialogSource, /buildWorkspaceCreateInput/);
  assert.match(dialogSource, /useCase === 'programming'/);
  assert.match(dialogSource, /busy/);
});

test('workspace creation is reachable from the workspace header and empty project state', () => {
  assert.match(sidebarSource, /onCreateWorkspace/);
  assert.match(sidebarSource, /workspaceCreateDisabledReason/);
  assert.match(sidebarSource, /workspaceCreate\.open/);
  assert.match(sidebarSource, /<WorkspaceDock[\s\S]*onCreateWorkspace=/);
  assert.match(
    sidebarSource,
    /workspaceCreateDisabledReason \? undefined : onCreateWorkspace/,
  );
  assert.match(dockSource, /availability === 'empty'[\s\S]*workspaceCreate\.open/);
});

test('App binds creation to the submitted scope and activates only the verified workspace', () => {
  assert.match(appSource, /<WorkspaceCreateDialog/);
  assert.match(appSource, /createWorkspaceFromDialog/);
  assert.match(appSource, /workspaceCreateScopeIsCurrent/);
  assert.match(appSource, /configScopeEpochRef\.current/);
  assert.match(appSource, /contextRevisionRef\.current/);
  assert.match(appSource, /mergeWorkspaceIntoProjectCatalog/);
  assert.match(appSource, /selectWorkspace\(created\.id, submittedScope\.projectId\)/);
});

test('workspace creation has a deterministic browser surface for success and failure states', () => {
  assert.match(qaSource, /'success' \| 'duplicate' \| 'error' \| 'scope-change'/);
  assert.match(qaSource, /qaWorkspaceRequest/);
  assert.match(qaSource, /qaWorkspaceCreated/);
  assert.match(qaSource, /new DesktopApiError\('Duplicate workspace', 409/);
  assert.match(qaSource, /new WorkspaceCreateScopeChangedError/);
});
