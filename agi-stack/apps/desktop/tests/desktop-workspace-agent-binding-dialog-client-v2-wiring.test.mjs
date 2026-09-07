import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const authority = source('src/plugins/desktopWorkspaceAgentBindingAuthorityModuleV2.ts');
const legacyProvider = source(
  'src/features/workspace/desktopWorkspaceAgentBindingDialogClientProviderV2.ts',
);

test('App creates one stable generation-backed workspace Agent-binding operation port', () => {
  assert.match(app, /createDesktopWorkspaceAgentBindingOperationsV2/u);
  assert.match(
    app,
    /const desktopWorkspaceAgentBindingOperationsV2 = useMemo\([\s\S]*?createDesktopWorkspaceAgentBindingOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.doesNotMatch(app, /createDesktopWorkspaceAgentBindingDialogClientProviderV2/u);
  assert.doesNotMatch(app, /desktopWorkspaceAgentBindingDialogClientProviderV2\.publish/u);
  assert.equal(legacyProvider, '');
});

test('workspace Agent-binding handlers use exact submitted scope through V2 operations', () => {
  const scopeFactory = functionSource(app, 'workspaceAgentBindingOperationScope');
  for (const field of ['tenantId', 'projectId', 'workspaceId']) {
    assert.match(scopeFactory, new RegExp(`${field}: scope\\.${field}`, 'u'));
  }
  assert.match(scopeFactory, /signal/u);
  assert.doesNotMatch(scopeFactory, /new DesktopApiClient\(/u);

  for (const [handlerName, methodName] of [
    ['loadWorkspaceAgentDefinitionsFromDialog', 'listWorkspaceBindingAgentDefinitions'],
    ['bindWorkspaceAgentFromDialog', 'bindWorkspaceAgent'],
    ['unbindWorkspaceAgentFromDialog', 'unbindWorkspaceAgent'],
  ]) {
    const handler = asyncFunctionSource(app, handlerName);
    assert.match(
      handler,
      new RegExp(`desktopWorkspaceAgentBindingOperationsV2\\.${methodName}`, 'u'),
    );
    assert.equal(countMatches(handler, /assertWorkspaceAgentBindingScope\(submittedScope\)/gu), 2);
    assert.ok(
      handler.indexOf('assertWorkspaceAgentBindingScope(submittedScope)') <
        handler.indexOf(`desktopWorkspaceAgentBindingOperationsV2.${methodName}`),
    );
    assert.ok(
      handler.lastIndexOf('assertWorkspaceAgentBindingScope(submittedScope)') >
        handler.indexOf(`desktopWorkspaceAgentBindingOperationsV2.${methodName}`),
    );
    assert.doesNotMatch(handler, /new DesktopApiClient\(|\.bindOperation\(/u);
  }
});

test('workspace Agent-binding V2 service owns exactly the three dialog operations', () => {
  for (const method of ['listAgentDefinitions', 'bindAgent', 'unbindAgent']) {
    assert.match(authority, new RegExp(`readonly ${method}:`, 'u'));
  }
  assert.match(authority, /acquireServiceOperationLease/u);
  assert.match(authority, /kind: 'project'/u);
  assert.doesNotMatch(authority, /refreshRuntime|listWorkspaceAgents/u);
  assert.doesNotMatch(
    authority,
    /createWorkspaceForProject|updateWorkspaceForProject|addWorkspaceMemberForProject/u,
  );
  assert.doesNotMatch(
    app,
    /desktopWorkspaceAgentBindingDialogClientV2|workspaceAgentBindingClient/u,
  );
});

function functionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = (`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n\n  const ', start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}

function asyncFunctionSource(sourceText, name) {
  const start = sourceText.indexOf(`const ${name} = async`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf('\n  };', start);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end + 5);
}

function countMatches(value, pattern) {
  return [...value.matchAll(pattern)].length;
}
