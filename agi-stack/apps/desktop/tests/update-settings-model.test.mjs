import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const { updateLifecyclePresentation } = await import(
  'file:///tmp/agistack-desktop-test-dist/src/features/settings/updateSettingsModel.js'
);
const updatePageSource = readFileSync(
  new URL('../src/features/settings/UpdateSettingsPage.tsx', import.meta.url),
  'utf8',
);

function state(overrides = {}) {
  return {
    schemaVersion: 2,
    phase: 'idle',
    currentVersion: '0.1.0',
    candidateVersion: null,
    recoveryVersion: null,
    progress: null,
    reasonCode: null,
    retryable: false,
    allowedActions: ['check'],
    ...overrides,
  };
}

test('update settings present protocol states without exposing internal reason codes', () => {
  assert.deepEqual(updateLifecyclePresentation(state()), {
    phaseKey: 'settings.updatesPhase.idle',
    reasonKey: null,
    progress: null,
    tone: 'neutral',
  });
  assert.deepEqual(
    updateLifecyclePresentation(
      state({
        phase: 'failed',
        reasonCode: 'update_recovery_journal_invalid',
        retryable: true,
      }),
    ),
    {
      phaseKey: 'settings.updatesPhase.failed',
      reasonKey: 'settings.updatesReason.recoveryJournalInvalid',
      progress: null,
      tone: 'danger',
    },
  );
  assert.equal(
    updateLifecyclePresentation(
      state({ phase: 'failed', reasonCode: 'future_internal_detail' }),
    ).reasonKey,
    'settings.updatesReason.unknown',
  );
});

test('update settings clamp progress and distinguish successful verification', () => {
  assert.deepEqual(
    updateLifecyclePresentation(
      state({
        phase: 'downloading',
        candidateVersion: '0.1.1',
        progress: 120,
        allowedActions: [],
      }),
    ),
    {
      phaseKey: 'settings.updatesPhase.downloading',
      reasonKey: null,
      progress: 100,
      tone: 'progress',
    },
  );
  assert.equal(
    updateLifecyclePresentation(
      state({ phase: 'recovered', recoveryVersion: '0.1.0' }),
    ).tone,
    'success',
  );
});

test('update settings page subscribes to preload authority and exposes only allowed actions', () => {
  assert.match(updatePageSource, /window\.__MEMSTACK_DESKTOP__\?\.updates/u);
  assert.match(updatePageSource, /updates\.getState\(\)/u);
  assert.match(updatePageSource, /updates\.subscribe/u);
  assert.match(updatePageSource, /allowedActions\.includes\('check'\)/u);
  assert.match(updatePageSource, /allowedActions\.includes\('restart_to_apply'\)/u);
  assert.match(updatePageSource, /aria-live="polite"/u);
  assert.match(updatePageSource, /<progress/u);
  assert.doesNotMatch(updatePageSource, /reasonCode\}/u);
});
