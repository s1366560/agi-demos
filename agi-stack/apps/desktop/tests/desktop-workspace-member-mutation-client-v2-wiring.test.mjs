import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const legacyProviderPath = new URL(
  '../src/features/workspace/desktopWorkspaceMemberMutationClientProviderV2.ts',
  import.meta.url,
);

test('App owns one stable generation-bound workspace-member mutation operation set', () => {
  assert.match(app, /createDesktopWorkspaceMemberMutationOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceMemberMutationOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceMemberMutationOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceMemberMutationClientProviderV2/u);
  assert.doesNotMatch(app, /desktopWorkspaceMemberMutationClientProviderV2\.publish/u);
  assert.equal(existsSync(legacyProviderPath), false);
});

test('workspace-member handlers use only V2 operations with submitted frozen scope', () => {
  for (const [handlerName, operationName] of [
    ['addWorkspaceMemberFromDialog', 'addWorkspaceMember'],
    ['updateWorkspaceMemberRoleFromDialog', 'updateWorkspaceMemberRole'],
    ['removeWorkspaceMemberFromDialog', 'removeWorkspaceMember'],
  ]) {
    const handler = asyncArrowFunctionSource(app, handlerName);
    assert.match(
      handler,
      new RegExp(`desktopWorkspaceMemberMutationOperationsV2\\.${operationName}\\(\\{`),
    );
    assert.equal(
      (handler.match(/assertWorkspaceMemberMutationScope\(submittedScope\)/gu) ?? []).length,
      2,
    );
    for (const field of ['tenantId', 'projectId', 'workspaceId']) {
      assert.match(handler, new RegExp(`${field}: submittedScope\\.${field}`));
    }
    assert.match(handler, /workspaceId: submittedScope\.workspaceId/u);
    assert.match(handler, /userId/u);
    assert.match(handler, /signal/u);
    assert.doesNotMatch(handler, /new DesktopApiClient\(|bindOperation|ForProject/u);
    assert.ok(
      handler.indexOf('await desktopWorkspaceMemberMutationOperationsV2') <
        handler.indexOf('updateDataset'),
    );
  }

  assert.match(asyncArrowFunctionSource(app, 'addWorkspaceMemberFromDialog'), /role,/u);
  assert.match(asyncArrowFunctionSource(app, 'updateWorkspaceMemberRoleFromDialog'), /role,/u);
  assert.doesNotMatch(asyncArrowFunctionSource(app, 'removeWorkspaceMemberFromDialog'), /role,/u);
});

test('workspace-member mutation authority remains separate from roster and lifecycle reads', () => {
  const module = source('src/plugins/desktopWorkspaceMemberMutationAuthorityModuleV2.ts');
  for (const method of ['addMember', 'removeMember', 'updateMemberRole']) {
    assert.match(module, new RegExp(method));
  }
  assert.match(module, /acquireServiceOperationLease/u);
  assert.doesNotMatch(module, /listWorkspaceMembers|createWorkspaceForProject/u);
  assert.doesNotMatch(app, /workspaceMemberMutationClient/u);
});

function asyncArrowFunctionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = async`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  };', start);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end + 5);
}
