import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { IabTabRegistry } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/iab/iabTabRegistry.js',
);

test('iab tab ids are incrementing integers that are never reused', () => {
  const registry = new IabTabRegistry();
  const first = registry.createTab();
  const second = registry.createTab();
  const third = registry.createTab();
  assert.deepEqual([first, second, third], [1, 2, 3]);
  assert.equal(registry.hasTab(second), true);
  registry.removeTab(second);
  assert.equal(registry.hasTab(second), false);
  assert.equal(registry.createTab(), 4);
  assert.deepEqual(registry.listTabIds(), [1, 3, 4]);
});

test('iab tab groups are idempotent per key and validate membership', () => {
  const registry = new IabTabRegistry();
  const tabId = registry.createTab();
  const groupA = registry.ensureTabGroup('run-1');
  assert.equal(registry.ensureTabGroup('run-1'), groupA);
  const groupB = registry.ensureTabGroup('run-2');
  assert.notEqual(groupA, groupB);

  registry.assignTab(tabId, groupA);
  assert.equal(registry.tabGroupId(tabId), groupA);
  assert.equal(registry.ungroupTab(tabId), true);
  assert.equal(registry.ungroupTab(tabId), false);
  assert.equal(registry.tabGroupId(tabId), null);

  assert.throws(() => registry.assignTab(tabId, 999), /group 999/);
  assert.throws(() => registry.assignTab(999, groupA), /tab 999/);
});

test('turnEnded planning closes unmarked agent tabs and ungroups kept tabs', () => {
  const registry = new IabTabRegistry();
  const agentUnmarked = registry.createTab();
  const agentDeliverable = registry.createTab();
  const userTab = registry.createTab();
  const groupId = registry.ensureTabGroup('run-1');
  registry.assignTab(agentUnmarked, groupId);
  registry.assignTab(agentDeliverable, groupId);
  registry.assignTab(userTab, groupId);

  const plan = registry.planTurnEnded([
    { tabId: agentUnmarked, origin: 'agent', mark: null },
    { tabId: agentDeliverable, origin: 'agent', mark: 'deliverable' },
    { tabId: userTab, origin: 'user', mark: null },
    { tabId: 999, origin: 'agent', mark: null },
  ]);

  assert.deepEqual(plan.closeTabIds, [agentUnmarked]);
  assert.deepEqual([...plan.ungroupTabIds].sort(), [agentDeliverable, userTab]);
  assert.deepEqual(plan.unknownTabIds, [999]);
});

test('turnEnded planning dedupes repeated lease tabIds', () => {
  const registry = new IabTabRegistry();
  const tabId = registry.createTab();
  const plan = registry.planTurnEnded([
    { tabId, origin: 'agent', mark: null },
    { tabId, origin: 'agent', mark: 'handoff' },
  ]);
  assert.deepEqual(plan.closeTabIds, [tabId]);
  assert.deepEqual(plan.ungroupTabIds, []);
});
