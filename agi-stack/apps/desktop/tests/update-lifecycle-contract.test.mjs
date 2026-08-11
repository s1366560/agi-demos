import assert from 'node:assert/strict';
import test from 'node:test';

const { createUpdateLifecycleState, parseUpdateLifecycleState } = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/updateLifecycle.js'
);

test('update lifecycle v2 exposes the locked phases, versions, retryability, and actions', () => {
  const state = createUpdateLifecycleState({
    phase: 'downloaded',
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    recoveryVersion: '0.1.0',
    progress: 100,
    reasonCode: null,
    retryable: false,
    allowedActions: ['restart_to_apply'],
  });

  assert.deepEqual(state, {
    schemaVersion: 2,
    phase: 'downloaded',
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    recoveryVersion: '0.1.0',
    progress: 100,
    reasonCode: null,
    retryable: false,
    allowedActions: ['restart_to_apply'],
  });
  assert.equal(Object.isFrozen(state), true);
  assert.equal(Object.isFrozen(state.allowedActions), true);

  for (const phase of [
    'idle',
    'checking',
    'available',
    'downloading',
    'downloaded',
    'applying',
    'verifying',
    'recovered',
    'failed',
    'disabled',
    'not_available',
  ]) {
    assert.equal(
      parseUpdateLifecycleState({
        ...state,
        phase,
        allowedActions: [],
      }).phase,
      phase,
    );
  }

  assert.throws(
    () => parseUpdateLifecycleState({ ...state, phase: 'installing' }),
    /update lifecycle state is invalid/u,
  );
  assert.throws(
    () =>
      parseUpdateLifecycleState({
        ...state,
        allowedActions: ['restart_to_apply', 'restart_to_apply'],
      }),
    /update lifecycle state is invalid/u,
  );
});
