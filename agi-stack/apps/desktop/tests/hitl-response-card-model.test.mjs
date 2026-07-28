import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildDecisionResponse,
  buildEnvVarResponse,
  formatHitlRemaining,
  hitlDecisionView,
  hitlEnvVarView,
  hitlRequestExpiry,
  toggleDecisionSelection,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/hitlResponseCardModel.js',
);
const cardSource = readFileSync(
  new URL('../src/features/chat/HitlResponseCard.tsx', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

function item(type, payload) {
  return {
    id: `${type}-1`,
    type,
    eventTimeUs: 1_000_000,
    eventCounter: 1,
    requestId: `${type}-request`,
    payload,
  };
}

test('HITL cards submit the request authority revision, never the run revision', () => {
  assert.match(cardSource, /approvalRequest\?\.authority_revision/u);
  assert.doesNotMatch(cardSource, /approvalRequest\?\.run_revision/u);
});

test('decision model consumes explicit single or multiple selection contracts and rich option facts', () => {
  const multiple = hitlDecisionView(
    item('decision_asked', {
      selection_mode: 'multiple',
      max_selections: 2,
      allow_custom: true,
      default_option: 'safe',
      options: [
        {
          id: 'safe',
          label: 'Safe rollout',
          description: 'Roll out in stages.',
          recommended: true,
          risk_level: 'low',
          estimated_time: '2 hours',
          estimated_cost: '$20',
          risks: ['Longer lead time'],
        },
        {
          id: 'fast',
          label: 'Fast rollout',
          risk_level: 'high',
          risks: ['Larger blast radius'],
        },
      ],
    }),
  );

  assert.deepEqual(multiple, {
    selectionMode: 'multiple',
    maxSelections: 2,
    allowCustom: false,
    defaultOption: 'safe',
    options: [
      {
        value: 'safe',
        label: 'Safe rollout',
        description: 'Roll out in stages.',
        recommended: true,
        riskLevel: 'low',
        estimatedTime: '2 hours',
        estimatedCost: '$20',
        risks: ['Longer lead time'],
      },
      {
        value: 'fast',
        label: 'Fast rollout',
        description: null,
        recommended: false,
        riskLevel: 'high',
        estimatedTime: null,
        estimatedCost: null,
        risks: ['Larger blast radius'],
      },
    ],
  });
  assert.deepEqual(toggleDecisionSelection([], 'safe', multiple), ['safe']);
  assert.deepEqual(toggleDecisionSelection(['safe'], 'fast', multiple), ['safe', 'fast']);
  assert.deepEqual(toggleDecisionSelection(['safe', 'fast'], 'other', multiple), [
    'safe',
    'fast',
  ]);
  assert.deepEqual(toggleDecisionSelection(['safe', 'fast'], 'safe', multiple), ['fast']);
  assert.deepEqual(buildDecisionResponse(['safe', 'fast'], false, '', multiple), {
    decision: ['safe', 'fast'],
  });
  assert.equal(buildDecisionResponse([], true, 'undefined-custom', multiple), null);

  const textOnlyLooksMultiple = hitlDecisionView(
    item('decision_asked', {
      question: 'Choose multiple approaches',
      options: [{ id: 'one', label: 'One' }],
    }),
  );
  assert.equal(textOnlyLooksMultiple.selectionMode, 'single');
});

test('custom decisions require the explicit single-select custom radio', () => {
  const single = hitlDecisionView(
    item('decision_asked', {
      selection_mode: 'single',
      allow_custom: true,
      default_option: 'safe',
      options: [{ id: 'safe', label: 'Safe rollout' }],
    }),
  );

  assert.equal(single.allowCustom, true);
  assert.deepEqual(buildDecisionResponse(['safe'], false, 'Custom rollout', single), {
    decision: 'safe',
  });
  assert.equal(buildDecisionResponse([], true, '   ', single), null);
  assert.deepEqual(buildDecisionResponse(['safe'], true, ' Custom rollout ', single), {
    decision: 'Custom rollout',
  });
});

test('environment model preserves declared input types and submits only declared fields plus save', () => {
  const view = hitlEnvVarView(
    item('env_var_requested', {
      allow_save: true,
      fields: [
        { name: 'REGION', label: 'Region', required: true, input_type: 'text' },
        {
          name: 'TOKEN',
          label: 'Token',
          required: true,
          secret: true,
          input_type: 'api_key',
          description: 'Deployment credential',
        },
        { name: 'NOTES', label: 'Notes', required: false, input_type: 'textarea' },
        { name: 'ENDPOINT', label: 'Endpoint', required: false, input_type: 'url' },
        { name: 'CONFIG', label: 'Config', required: false, input_type: 'file_path' },
        { label: 'Malformed' },
      ],
    }),
  );

  assert.equal(view.allowSave, true);
  assert.deepEqual(
    view.fields.map(({ name, inputType, inputElement, secret }) => ({
      name,
      inputType,
      inputElement,
      secret,
    })),
    [
      { name: 'REGION', inputType: 'text', inputElement: 'input', secret: false },
      { name: 'TOKEN', inputType: 'api_key', inputElement: 'password', secret: true },
      { name: 'NOTES', inputType: 'textarea', inputElement: 'textarea', secret: false },
      { name: 'ENDPOINT', inputType: 'url', inputElement: 'url', secret: false },
      { name: 'CONFIG', inputType: 'file_path', inputElement: 'input', secret: false },
    ],
  );
  assert.equal(buildEnvVarResponse({ REGION: 'us', TOKEN: '', EXTRA: 'drop' }, true, view), null);
  assert.deepEqual(
    buildEnvVarResponse(
      { REGION: 'us', TOKEN: 'secret-never-presented', EXTRA: 'drop' },
      true,
      view,
    ),
    {
      values: { REGION: 'us', TOKEN: 'secret-never-presented', NOTES: '', ENDPOINT: '', CONFIG: '' },
      save: true,
    },
  );
});

test('expiry model counts down valid timestamps and fails closed for expired or malformed authority', () => {
  const now = Date.parse('2026-07-28T01:00:00Z');
  const future = hitlRequestExpiry(
    item('decision_asked', { expires_at: '2026-07-28T01:01:01Z' }),
    undefined,
    now,
  );
  assert.deepEqual(future, {
    state: 'active',
    expiresAt: '2026-07-28T01:01:01Z',
    remainingSeconds: 61,
    canRespond: true,
  });
  assert.equal(formatHitlRemaining(future.remainingSeconds), '01:01');

  assert.equal(
    hitlRequestExpiry(
      item('decision_asked', { expires_at: '2026-07-28T00:59:59Z' }),
      undefined,
      now,
    ).state,
    'expired',
  );
  assert.deepEqual(
    hitlRequestExpiry(item('decision_asked', { expires_at: 'later' }), undefined, now),
    {
      state: 'invalid',
      expiresAt: 'later',
      remainingSeconds: 0,
      canRespond: false,
    },
  );
  assert.equal(
    hitlRequestExpiry(item('decision_asked', {}), undefined, now).canRespond,
    true,
  );
});

test('HITL card uses structured models for multi-select, field types, save, expiry, and read-only state', () => {
  for (const sourceContract of [
    /hitlDecisionView\(item\)/,
    /hitlEnvVarView\(item\)/,
    /hitlRequestExpiry\(item, approvalRequest, nowMs\)/,
    /type="checkbox"/,
    /checked=\{customDecisionSelected\}/,
    /disabled=\{responseDisabled \|\| busy \|\| !customDecisionSelected\}/,
    /setCustomDecisionSelected\(false\)/,
    /field\.inputElement === 'textarea'/,
    /buildEnvVarResponse\(envValues, saveEnvironmentValues, envVarView\)/,
    /responsePresentation/,
  ]) {
    assert.match(cardSource, sourceContract);
  }
  for (const key of [
    'chat.expiresIn',
    'chat.requestExpired',
    'chat.invalidExpiry',
    'chat.selectOneOrMore',
    'chat.selectionLimit',
    'chat.confirmSelection',
    'chat.recommended',
    'chat.risk',
    'chat.estimatedTime',
    'chat.estimatedCost',
    'chat.saveEnvironmentValues',
    'chat.optionalField',
  ]) {
    assert.equal(i18nSource.split(`'${key}'`).length - 1, 2, `${key} must cover both locales`);
  }
});
