import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const provider = source(
  'src/features/workspace/desktopWorkspaceAgentBindingDialogClientProviderV2.ts',
);

test('App publishes one stable V2 workspace Agent-binding dialog Provider', () => {
  assert.match(app, /createDesktopWorkspaceAgentBindingDialogClientProviderV2/u);
  assert.match(
    app,
    /const desktopWorkspaceAgentBindingDialogClientProviderV2 = useMemo\([\s\S]*?createDesktopWorkspaceAgentBindingDialogClientProviderV2\(\)[\s\S]*?\[\],[\s\S]*?\);/u,
  );
  assert.match(
    app,
    /desktopWorkspaceAgentBindingDialogClientProviderV2\.publish\(\{ config \}\)/u,
  );
});

test('workspace Agent-binding dialog handlers use only a submitted-scope V2 operation binding', () => {
  const factory = arrowFunctionSource(app, 'workspaceAgentBindingClient');
  assert.match(
    factory,
    /desktopWorkspaceAgentBindingDialogClientV2\.bindOperation\(\{/u,
  );
  for (const field of ['tenantId', 'projectId', 'workspaceId']) {
    assert.match(factory, new RegExp(`${field}: scope\\.${field}`));
  }
  assert.doesNotMatch(factory, /new DesktopApiClient\(/u);

  for (const [handlerName, methodName] of [
    [
      'loadWorkspaceAgentDefinitionsFromDialog',
      'listWorkspaceBindingAgentDefinitionsForProject',
    ],
    ['bindWorkspaceAgentFromDialog', 'bindWorkspaceAgentForProject'],
    ['unbindWorkspaceAgentFromDialog', 'unbindWorkspaceAgentForProject'],
  ]) {
    const handler = asyncArrowFunctionSource(app, handlerName);
    assert.match(handler, new RegExp(`workspaceAgentBindingClient[\\s\\S]*?${methodName}`));
    assert.doesNotMatch(handler, /new DesktopApiClient\(/u);
  }
});

test('workspace Agent-binding dialog Provider exposes no runtime refresh or read-model authority', () => {
  for (const method of [
    'listWorkspaceBindingAgentDefinitionsForProject',
    'bindWorkspaceAgentForProject',
    'unbindWorkspaceAgentForProject',
  ]) {
    assert.match(provider, new RegExp(`${method}:`));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(provider, /refreshRuntime|listWorkspaceAgents/u);
  assert.doesNotMatch(
    provider,
    /createWorkspaceForProject|updateWorkspaceForProject|addWorkspaceMemberForProject/u,
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
