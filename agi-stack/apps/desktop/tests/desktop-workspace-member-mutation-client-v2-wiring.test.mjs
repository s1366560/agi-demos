import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceMemberMutationClientProviderV2.ts',
);

test('App publishes one stable V2 workspace-member mutation Provider', () => {
  assert.match(app, /createDesktopWorkspaceMemberMutationClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceMemberMutationClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceMemberMutationClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceMemberMutationClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('workspace-member handlers bind only the V2 mutation authority to submitted scope', () => {
  const factory = arrowFunctionSource(app, 'workspaceMemberMutationClient');
  assert.match(
    factory,
    /desktopWorkspaceMemberMutationClientV2\.bindOperation\(\{/u,
  );
  for (const field of ['tenantId', 'projectId', 'workspaceId']) {
    assert.match(factory, new RegExp(`${field}: scope\\.${field}`));
  }
  assert.doesNotMatch(factory, /new DesktopApiClient\(/u);

  for (const [handlerName, methodName] of [
    ['addWorkspaceMemberFromDialog', 'addWorkspaceMemberForProject'],
    ['updateWorkspaceMemberRoleFromDialog', 'updateWorkspaceMemberRoleForProject'],
    ['removeWorkspaceMemberFromDialog', 'removeWorkspaceMemberForProject'],
  ]) {
    const handler = asyncArrowFunctionSource(app, handlerName);
    assert.match(
      handler,
      new RegExp(
        `workspaceMemberMutationClient\\(\\s*submittedScope,?\\s*\\)\\s*\\.${methodName}`,
      ),
    );
    assert.doesNotMatch(handler, /new DesktopApiClient\(/u);
  }
});

test('workspace-member mutation Provider exposes no member read-model authority', () => {
  for (const method of [
    'addWorkspaceMemberForProject',
    'removeWorkspaceMemberForProject',
    'updateWorkspaceMemberRoleForProject',
  ]) {
    assert.match(provider, new RegExp(`${method}:`));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(provider, /listWorkspaceMembers/u);
  assert.doesNotMatch(provider, /createWorkspaceForProject|updateWorkspaceForProject/u);
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
