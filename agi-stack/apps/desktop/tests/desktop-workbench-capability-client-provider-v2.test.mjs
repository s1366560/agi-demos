import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const providerSource = readFileSync(new URL('../src/features/runtime/desktopWorkbenchCapabilityClientProviderV2.ts', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const module = { exports: {} };
new Function('require', 'module', 'exports', ts.transpileModule(providerSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)((name) => { throw new Error(`unexpected production dependency: ${name}`); }, module, module.exports);
const { createDesktopWorkbenchCapabilityClientProviderV2, DesktopWorkbenchCapabilityClientProviderErrorV2 } = module.exports;
const config = { mode: 'local', tenantId: 'tenant-1', projectId: 'project-1', workspaceId: 'workspace-1' };
const snapshotOperationsV2 = { loadSnapshot: async () => ({ mode: 'local', capabilities: [] }) };

test('desktop workbench capability client provider fails closed before publication', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  assert.throws(() => provider.resolve(), (error) => {
    assert.ok(error instanceof DesktopWorkbenchCapabilityClientProviderErrorV2);
    assert.equal(error.reasonCode, 'desktop_workbench_capability_client_unpublished');
    assert.equal(error.message, error.reasonCode);
    return true;
  });
});
test('each publication returns one frozen capability client binding', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const local = provider.publish({ config, snapshotOperationsV2 });
  const cloud = provider.publish({ config: { ...config, mode: 'cloud' }, snapshotOperationsV2 });
  assert.ok(Object.isFrozen(local));
  assert.ok(Object.isFrozen(cloud));
  assert.ok(Object.isFrozen(local.client));
  assert.notEqual(local, cloud);
  assert.notEqual(local.client, cloud.client);
  assert.equal(typeof local.client.loadSnapshot, 'function');
  assert.equal(provider.resolve(), cloud);
});
test('failed capability client publication keeps the last-good binding', () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const lastGood = provider.publish({ config, snapshotOperationsV2 });
  const poisonedConfig = { get mode() { throw new Error('candidate_capability_config_invalid'); } };
  assert.throws(() => provider.publish({ config: poisonedConfig, snapshotOperationsV2 }), /candidate_capability_config_invalid/);
  assert.equal(provider.resolve(), lastGood);
  assert.throws(() => provider.publish({ config }), /desktop_workbench_snapshot_operations_required/);
  assert.equal(provider.resolve(), lastGood);
});
test('publication freezes config and forwards each signal only to the captured required operation', async () => {
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const captured = [];
  const mutableConfig = { ...config };
  const operations = { async loadSnapshot(input) { captured.push(input); return { projectId: input.config.projectId }; } };
  const input = { config: mutableConfig, snapshotOperationsV2: operations };
  const binding = provider.publish(input);
  mutableConfig.projectId = 'other';
  input.snapshotOperationsV2 = { loadSnapshot() { throw new Error('replacement'); } };
  const controller = new AbortController();
  assert.deepEqual(await binding.client.loadSnapshot(controller.signal), { projectId: 'project-1' });
  assert.ok(Object.isFrozen(captured[0].config));
  assert.equal(captured[0].signal, controller.signal);
  assert.equal(captured.length, 1);
  await binding.client.loadSnapshot();
  await binding.client.loadSnapshot();
  assert.ok(captured[1].signal instanceof AbortSignal);
  assert.equal(captured[1].signal.aborted, false);
  assert.notEqual(captured[1].signal, captured[2].signal);
});
test('disabled authority rejection is preserved without static fallback or eager reads', async () => {
  let calls = 0;
  const rejection = new Error('desktop_workbench_snapshot_disabled');
  const provider = createDesktopWorkbenchCapabilityClientProviderV2();
  const binding = provider.publish({ config, snapshotOperationsV2: { async loadSnapshot() { calls++; throw rejection; } } });
  assert.equal(calls, 0);
  await assert.rejects(binding.client.loadSnapshot(), (error) => error === rejection);
  assert.equal(calls, 1);
});
test('App publishes only the required snapshot port and config', () => {
  const start = appSource.indexOf('const desktopWorkbenchCapabilityClientV2 = useMemo(');
  const end = appSource.indexOf('const sandboxRuntime =', start);
  assert.ok(start >= 0 && end > start);
  const publication = appSource.slice(start, end);
  assert.match(publication, /snapshotOperationsV2: desktopWorkbenchSnapshotOperationsV2/u);
  assert.doesNotMatch(publication, /automationApi|projectBlackboardOperationsV2|tenantTasksOperationsV2/u);
  assert.match(appSource, /createDesktopWorkbenchSnapshotOperationsV2\([\s\S]*?desktopPluginMarketplaceGenerationActionsRefV2\.current/u);
  assert.doesNotMatch(providerSource, /new DesktopApiClient|createDesktopWorkbenchCapabilityClient\(|createProjectWorkspacesV2Client/u);
  assert.match(appSource, /useDesktopCapabilitySnapshot\([\s\S]*?desktopWorkbenchCapabilityClientV2\.client/u);
});
