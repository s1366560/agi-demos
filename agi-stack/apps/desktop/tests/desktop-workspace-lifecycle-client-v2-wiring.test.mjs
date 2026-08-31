import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceLifecycleClientProviderV2.ts',
);

test('App publishes one stable V2 workspace lifecycle Provider', () => {
  assert.match(app, /createDesktopWorkspaceLifecycleClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceLifecycleClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceLifecycleClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceLifecycleClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('workspace lifecycle handlers bind only V2 mutation authority to submitted scope', () => {
  const factory = arrowFunctionSource(app, 'workspaceLifecycleClient');
  assert.match(factory, /desktopWorkspaceLifecycleClientV2\.bindOperation\(\{/u);
  for (const field of ['tenantId', 'projectId', 'workspaceId']) {
    assert.match(factory, new RegExp(`${field}: scope\\.${field}`));
  }
  assert.doesNotMatch(factory, /new DesktopApiClient\(/u);

  const createHandler = asyncArrowFunctionSource(app, 'createWorkspaceFromDialog');
  assert.match(createHandler, /workspaceLifecycleClient\(\{/u);
  assert.match(createHandler, /tenantId: submittedScope\.tenantId/u);
  assert.match(createHandler, /projectId: submittedScope\.projectId/u);
  assert.match(createHandler, /workspaceId: ''/u);
  assert.match(createHandler, /creationClient\.createWorkspaceForProject/u);
  assert.doesNotMatch(createHandler, /new DesktopApiClient\(/u);

  const updateHandler = asyncArrowFunctionSource(app, 'updateWorkspaceFromDialog');
  assert.match(updateHandler, /workspaceLifecycleClient\(submittedScope\)/u);
  assert.match(updateHandler, /settingsClient\.updateWorkspaceForProject/u);
  assert.doesNotMatch(updateHandler, /new DesktopApiClient\(/u);
});

test('workspace lifecycle Provider exposes no workspace reads or adjacent mutations', () => {
  for (const method of ['createWorkspaceForProject', 'updateWorkspaceForProject']) {
    assert.match(provider, new RegExp(`${method}:`));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(provider, /listWorkspacesForProject|createWorkspace:/u);
  assert.doesNotMatch(
    provider,
    /addWorkspaceMemberForProject|updateWorkspaceMemberRoleForProject|removeWorkspaceMemberForProject/u,
  );
  assert.doesNotMatch(
    provider,
    /listWorkspaceAutonomyAttentions|resolveWorkspaceAutonomyAttention|retryWorkspaceAutonomyAttention/u,
  );
});

function arrowFunctionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = (`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n\n  const ', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}

function asyncArrowFunctionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = async`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  };', start);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end + 5);
}
