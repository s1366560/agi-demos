import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  getSessionWorkPanelOptions,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionWorkPanelOptions.js');
const state = (capabilityMode, timelineItems = []) => ({
  capabilityMode,
  timelineItems,
  toolInvocations: [],
  artifactCanvas: { tabs: [] },
  artifactVersions: [],
  mcpAppCanvas: { tabs: [] },
});

test('work panel retains unsupported menu entries with explicit reasons', () => {
  const code = getSessionWorkPanelOptions(state('code'));
  const work = getSessionWorkPanelOptions(state('work'));
  assert.deepEqual(
    code.map(({ id }) => id),
    work.map(({ id }) => id),
  );
  assert.equal(new Set(code.map(({ id }) => id)).size, code.length);
  assert.equal(code.find(({ id }) => id === 'terminal').available, true);
  assert.equal(work.find(({ id }) => id === 'terminal').reasonKey, 'rightbar.unsupportedMode');
  assert.equal(code.find(({ id }) => id === 'artifacts').available, false);
  assert.equal(work.find(({ id }) => id === 'artifacts').available, true);
  assert.equal(code.find(({ id }) => id === 'overview').group, 'details');
});

test('detail capabilities follow projected event presence without changing menu order', () => {
  const empty = getSessionWorkPanelOptions(state('unavailable'));
  const populated = getSessionWorkPanelOptions(
    state('unavailable', [
      {
        id: 'context-1',
        type: 'context_status',
        payload: {
          current_tokens: 100,
          token_budget: 1000,
          occupancy_pct: 10,
          compression_level: 'none',
        },
        eventTimeUs: 1,
        eventCounter: 1,
      },
    ]),
  );
  assert.deepEqual(
    empty.map(({ id }) => id),
    populated.map(({ id }) => id),
  );
  assert.equal(empty.find(({ id }) => id === 'context').available, false);
  assert.equal(populated.find(({ id }) => id === 'context').available, true);
  assert.equal(populated.find(({ id }) => id === 'activity').available, true);
  assert.equal(populated.find(({ id }) => id === 'graph').available, false);
});

test('concrete artifact content remains reachable in code sessions', () => {
  for (const content of [
    { artifactCanvas: { tabs: [{ id: 'snippet-1' }] } },
    { artifactVersions: [{ artifact_id: 'artifact-1' }] },
  ]) {
    const options = getSessionWorkPanelOptions({ ...state('code'), ...content });
    assert.equal(options.find(({ id }) => id === 'artifacts').available, true);
    assert.equal(options.find(({ id }) => id === 'artifacts').reasonKey, undefined);
  }
});

test('menu reasons distinguish unsupported capabilities from missing runtime content', () => {
  const options = getSessionWorkPanelOptions(state('work'));
  const reason = (id) => options.find((entry) => entry.id === id).reasonKey;
  assert.equal(reason('terminal'), 'rightbar.unsupportedMode');
  assert.equal(reason('apps'), 'rightbar.noApps');
  for (const id of ['agents', 'graph', 'insights', 'context', 'runtime']) {
    assert.equal(reason(id), 'rightbar.awaitingData');
  }
  assert.equal(reason('plan'), undefined);
});
