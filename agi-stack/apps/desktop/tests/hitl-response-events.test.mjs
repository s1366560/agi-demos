import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { applyHitlResponseStreamEvent, hitlResponsePresentation } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/hitlResponseEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const cardSource = readFileSync(
  new URL('../src/features/chat/HitlResponseCard.tsx', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/SessionSteeringQa.tsx', import.meta.url), 'utf8');
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

function asked(type, requestId, extra = {}) {
  return {
    id: `${type}-${requestId}`,
    type,
    eventTimeUs: 1_000_000,
    eventCounter: 1,
    requestId,
    payload: { request_id: requestId },
    ...extra,
  };
}

test('live HITL replies update their original request without appending response rows', () => {
  const pending = [
    asked('clarification_asked', 'clarify-1'),
    asked('decision_asked', 'decision-1'),
    asked('env_var_requested', 'env-1'),
    asked('permission_asked', 'permission-1'),
    asked('a2ui_action_asked', 'a2ui-1'),
  ];
  const responses = [
    { type: 'clarification_answered', data: { request_id: 'clarify-1', answer: 'Redis' } },
    { event_type: 'decision_answered', payload: { requestId: 'decision-1', decision: 'Ship' } },
    {
      type: 'env_var_provided',
      data: {
        request_id: 'env-1',
        saved_variables: ['API_TOKEN'],
        values: { API_TOKEN: 'must-never-render' },
      },
    },
    { type: 'permission_replied', data: { request_id: 'permission-1', granted: false } },
    {
      type: 'a2ui_action_answered',
      data: {
        request_id: 'a2ui-1',
        action_name: 'approve',
        source_component_id: 'approve-button',
      },
    },
  ];

  const settled = responses.reduce((items, event) => {
    const result = applyHitlResponseStreamEvent(items, event);
    assert.equal(result.handled, true);
    assert.equal(result.items.length, pending.length);
    return result.items;
  }, pending);

  assert.deepEqual(
    settled.map(({ answered }) => answered),
    [true, true, true, true, true],
  );
  assert.equal(settled[0].answer, 'Redis');
  assert.equal(settled[1].decision, 'Ship');
  assert.deepEqual(settled[2].providedVariables, ['API_TOKEN']);
  assert.doesNotMatch(JSON.stringify(settled), /must-never-render/);
  assert.equal(settled[3].granted, false);
  assert.equal(settled[4].actionName, 'approve');
  assert.equal(settled[4].sourceComponentId, 'approve-button');
});

test('HITL reply matching is request- and request-type-specific while legacy permission replies remain supported', () => {
  const pending = [asked('clarification_asked', 'shared'), asked('permission_asked', 'shared')];
  const permission = applyHitlResponseStreamEvent(pending, {
    type: 'permission_granted',
    data: { request_id: 'shared', granted: true },
  });

  assert.equal(permission.handled, true);
  assert.equal(permission.items[0].answered, undefined);
  assert.equal(permission.items[1].answered, true);
  assert.equal(permission.items[1].granted, true);

  const local = applyHitlResponseStreamEvent([asked('decision_asked', 'local-decision')], {
    type: 'hitl_responded',
    payload: { request_id: 'local-decision', hitl_type: 'decision', answered: true },
  });
  assert.equal(local.handled, true);
  assert.equal(local.items[0].answered, true);

  const unrelated = applyHitlResponseStreamEvent(pending, {
    type: 'cost_update',
    data: { total_tokens: 42 },
  });
  assert.equal(unrelated.handled, false);
  assert.equal(unrelated.items, pending);
});

test('answered HITL cards expose safe localized response summaries', () => {
  assert.deepEqual(
    hitlResponsePresentation({ ...asked('clarification_asked', '1'), answered: true, answer: 'Redis' }, 'clarification'),
    { labelKey: 'chat.response.answer', value: 'Redis' },
  );
  assert.deepEqual(
    hitlResponsePresentation({ ...asked('decision_asked', '2'), answered: true, decision: 'Ship' }, 'decision'),
    { labelKey: 'chat.response.decision', value: 'Ship' },
  );
  assert.deepEqual(
    hitlResponsePresentation(
      { ...asked('env_var_requested', '3'), answered: true, providedVariables: ['API_TOKEN'] },
      'env_var',
    ),
    { labelKey: 'chat.response.variables', value: 'API_TOKEN' },
  );
  assert.deepEqual(
    hitlResponsePresentation({ ...asked('permission_asked', '4'), answered: true, granted: false }, 'permission'),
    { labelKey: 'chat.response.permission', valueKey: 'chat.response.denied' },
  );
  assert.deepEqual(
    hitlResponsePresentation({ ...asked('a2ui_action_asked', '5'), answered: true, actionName: 'approve' }, 'a2ui_action'),
    { labelKey: 'chat.response.action', value: 'approve' },
  );
});

test('Desktop wires reply folding into live ingestion and the QA surface exercises it', () => {
  assert.match(appSource, /applyHitlResponseStreamEvent\(existing, event\)/);
  assert.match(appSource, /hitlResponse\.handled[\s\S]*return hitlResponse\.items/);
  assert.match(cardSource, /hitlResponsePresentation\(item, hitlType\)/);
  assert.match(cardSource, /timeline-hitl-response/);
  assert.match(qaSource, /hitl-response-events/);
  assert.match(qaSource, /applyHitlResponseStreamEvent/);
  for (const key of [
    'chat.response.answer',
    'chat.response.decision',
    'chat.response.variables',
    'chat.response.permission',
    'chat.response.action',
    'chat.response.allowed',
    'chat.response.denied',
  ]) {
    assert.equal(i18nSource.split(`'${key}'`).length - 1, 2, `${key} must cover both locales`);
  }
});
