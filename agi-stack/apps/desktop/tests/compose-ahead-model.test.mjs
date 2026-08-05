import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  composeAheadConversationScope,
  composeAheadContextSnapshot,
  composeAheadEligibility,
  conversationResponseIsStreaming,
  createComposeAheadQueueStore,
  nextComposeAheadDispatch,
  parseComposeAheadDefaultIntent,
  readComposeAheadDefaultIntent,
  writeComposeAheadDefaultIntent,
  COMPOSE_AHEAD_DEFAULT_INTENT_STORAGE_KEY,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/composeAheadModel.js';

const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const runInputEligibilitySource = appSource.slice(
  appSource.indexOf('const runInputDeliveryOptions = useMemo'),
  appSource.indexOf('const effectiveRunInputDeliveryValue'),
);

function context(kind, resourceId, executionSlot) {
  return {
    kind,
    resource_id: resourceId,
    label: resourceId,
    metadata: executionSlot ? { execution_slot: executionSlot } : undefined,
  };
}

test('compose-ahead store claims and accepts exactly one FIFO prompt per terminal cycle', () => {
  let sequence = 0;
  const store = createComposeAheadQueueStore({
    now: () => 1_000 + sequence,
    createId: () => `prompt-${(sequence += 1)}`,
  });

  store.enqueue('tenant/project/workspace/conversation', {
    text: 'first',
    contextItems: [],
  });
  store.enqueue('tenant/project/workspace/conversation', {
    text: 'second',
    contextItems: [],
  });
  store.enqueue('tenant/project/workspace/conversation', {
    text: 'third',
    contextItems: [],
  });

  assert.equal(store.claimHead('tenant/project/workspace/conversation')?.text, 'first');
  assert.equal(store.claimHead('tenant/project/workspace/conversation'), undefined);
  assert.deepEqual(
    store.getSnapshot('tenant/project/workspace/conversation').map((prompt) => [
      prompt.text,
      prompt.status,
    ]),
    [
      ['first', 'dispatching'],
      ['second', 'queued'],
      ['third', 'queued'],
    ],
  );

  store.accept('tenant/project/workspace/conversation', 'prompt-1');
  assert.equal(store.claimHead('tenant/project/workspace/conversation')?.text, 'second');
  store.accept('tenant/project/workspace/conversation', 'prompt-2');
  assert.equal(store.claimHead('tenant/project/workspace/conversation')?.text, 'third');
  store.accept('tenant/project/workspace/conversation', 'prompt-3');
  assert.deepEqual(store.getSnapshot('tenant/project/workspace/conversation'), []);
});

test('compose-ahead store isolates conversations and supports remove, fail, and explicit retry', () => {
  let sequence = 0;
  const store = createComposeAheadQueueStore({
    now: () => 2_000,
    createId: () => `isolated-${(sequence += 1)}`,
  });
  const notifications = [];
  const unsubscribe = store.subscribe(() => notifications.push('changed'));

  const first = store.enqueue('scope-a', { text: 'A1', contextItems: [] });
  const middle = store.enqueue('scope-a', { text: 'A2', contextItems: [] });
  store.enqueue('scope-a', { text: 'A3', contextItems: [] });
  store.enqueue('scope-b', { text: 'B1', contextItems: [] });
  store.remove('scope-a', middle.id);
  assert.deepEqual(
    store.getSnapshot('scope-a').map((prompt) => prompt.text),
    ['A1', 'A3'],
  );
  assert.deepEqual(
    store.getSnapshot('scope-b').map((prompt) => prompt.text),
    ['B1'],
  );

  assert.equal(store.claimHead('scope-a')?.id, first.id);
  store.fail('scope-a', first.id);
  assert.equal(store.getSnapshot('scope-a')[0]?.status, 'failed');
  assert.equal(store.retry('scope-a', first.id), true);
  assert.equal(store.getSnapshot('scope-a')[0]?.status, 'queued');
  unsubscribe();
  assert.ok(notifications.length >= 7);
});

test('compose-ahead snapshots only Web-compatible skill and subagent context', () => {
  const source = [
    context('skill', 'release-guard', 'skill'),
    context('agent', 'reviewer', 'subagent'),
    context('agent', 'primary-agent', 'agent'),
    context('attachment', '/sandbox/report.pdf'),
    context('command', '/review', 'command'),
  ];

  const snapshot = composeAheadContextSnapshot(source);
  assert.deepEqual(
    snapshot.contextItems.map((item) => [item.resource_id, item.metadata?.execution_slot]),
    [
      ['release-guard', 'skill'],
      ['reviewer', 'subagent'],
    ],
  );
  assert.equal(snapshot.hasUnsupportedContext, true);

  source[0].label = 'mutated';
  source[0].metadata.execution_slot = 'agent';
  assert.equal(snapshot.contextItems[0].label, 'release-guard');
  assert.equal(snapshot.contextItems[0].metadata?.execution_slot, 'skill');
});

test('compose-ahead eligibility preserves attachments, references, IME text, and disabled state', () => {
  const queueable = composeAheadEligibility({
    content: 'continue with the next check',
    streaming: true,
    disabled: false,
    uploading: false,
    contextItems: [context('skill', 'release-guard', 'skill')],
    referenceCount: 0,
  });
  assert.deepEqual(queueable, { canQueue: true, reason: null });

  assert.equal(
    composeAheadEligibility({
      content: 'inspect the attachment',
      streaming: true,
      disabled: false,
      uploading: false,
      contextItems: [context('attachment', '/sandbox/report.pdf')],
      referenceCount: 0,
    }).reason,
    'unsupported_context',
  );
  assert.equal(
    composeAheadEligibility({
      content: 'inspect the selected range',
      streaming: true,
      disabled: false,
      uploading: false,
      contextItems: [],
      referenceCount: 1,
    }).reason,
    'references',
  );
  assert.equal(
    composeAheadEligibility({
      content: 'wait',
      streaming: true,
      disabled: true,
      uploading: false,
      contextItems: [],
      referenceCount: 0,
    }).reason,
    'disabled',
  );
});

test('conversation response state is scoped and stops only on structured terminal evidence', () => {
  const base = {
    activeConversationId: 'conversation-a',
    sending: false,
    activityPresence: 'recorded',
    timelineItems: [],
  };
  assert.equal(
    conversationResponseIsStreaming({
      ...base,
      signals: [
        {
          id: 'signal-a',
          content: 'task',
          status: 'acknowledged',
          detail: 'streaming',
          createdAt: '2026-07-24T00:00:00Z',
          conversationId: 'conversation-a',
          messageId: 'message-a',
          eventType: 'text_delta',
        },
      ],
    }),
    true,
  );
  assert.equal(
    conversationResponseIsStreaming({
      ...base,
      signals: [
        {
          id: 'signal-b',
          content: 'task',
          status: 'acknowledged',
          detail: 'streaming elsewhere',
          createdAt: '2026-07-24T00:00:00Z',
          conversationId: 'conversation-b',
          messageId: 'message-b',
          eventType: 'text_delta',
        },
      ],
    }),
    false,
  );
  assert.equal(
    conversationResponseIsStreaming({
      ...base,
      signals: [],
      timelineItems: [
        {
          id: 'user-a',
          type: 'user_message',
          eventTimeUs: 1,
          eventCounter: 1,
          role: 'user',
          content: 'hello',
        },
        {
          id: 'assistant-a',
          type: 'assistant_message',
          eventTimeUs: 2,
          eventCounter: 2,
          role: 'assistant',
          content: 'working',
          metadata: { streaming: true },
        },
      ],
    }),
    true,
  );
  assert.equal(
    conversationResponseIsStreaming({
      ...base,
      signals: [],
      timelineItems: [
        {
          id: 'assistant-complete',
          type: 'assistant_message',
          eventTimeUs: 3,
          eventCounter: 3,
          role: 'assistant',
          content: 'done',
          metadata: { streaming: false },
        },
      ],
    }),
    false,
  );
});

test('compose-ahead scope binds tenant, project, workspace, and conversation identity', () => {
  assert.equal(
    composeAheadConversationScope({
      id: 'conversation-a',
      tenant_id: 'tenant-a',
      project_id: 'project-a',
      workspace_id: 'workspace-a',
    }),
    'tenant-a\u0000project-a\u0000workspace-a\u0000conversation-a',
  );
  assert.equal(composeAheadConversationScope(null), null);
});

test('Desktop composer exposes an accessible queue without replacing run-input queue_next', () => {
  assert.match(chatPanelSource, /className="compose-ahead-queue"/);
  assert.match(chatPanelSource, /aria-live="polite"/);
  assert.match(chatPanelSource, /composeAheadEligibility/);
  assert.match(chatPanelSource, /event\.nativeEvent\.isComposing/);
  assert.match(chatPanelSource, /event\.shiftKey/);
  assert.match(chatPanelSource, /runInputDeliveryOptions\.length === 0/);
  assert.match(chatPanelSource, /composeAheadQueueStore\.claimNext/);
  assert.match(chatPanelSource, /composeAheadQueueStore\.accept/);
  assert.match(chatPanelSource, /composeAheadQueueStore\.retry/);
  assert.match(chatPanelSource, /dispatchMonitorRef/);
  assert.match(chatPanelSource, /window\.clearTimeout\(dispatchMonitorRef\.current\.timerId\)/);
});

test('canonical Agent Workspace fails closed instead of auto-sending through compose-ahead', () => {
  assert.match(chatPanelSource, /composeAheadFallbackAllowed = false/);
  assert.match(
    chatPanelSource,
    /Boolean\(composeAheadScope\) &&\s+composeAheadFallbackAllowed &&\s+runInputDeliveryOptions\.length === 0/,
  );
  assert.match(appSource, /composeAheadFallbackAllowed=\{false\}/);
});

test('canonical terminal run authority overrides stale streaming signals', () => {
  assert.match(chatPanelSource, /canonicalRunStatus\?: DesktopRunStatus \| null/);
  assert.match(
    chatPanelSource,
    /!sessionRunStatusIsTerminal\(canonicalRunStatus\) &&\s+rawResponseStreaming/,
  );
  assert.match(
    appSource,
    /canonicalRunStatus=\{currentArtifactRun\?\.status \?\? null\}/,
  );
});

test('canonical Cloud run inputs are available for every active Agent Workspace mode', () => {
  assert.doesNotMatch(
    runInputEligibilitySource,
    /sessionDetailViewModel\?\.capabilityMode !== 'code'/,
  );
  assert.match(runInputEligibilitySource, /currentArtifactRun\.status === 'running'/);
  assert.match(runInputEligibilitySource, /options\.push\('steer_now'\)/);
  assert.match(runInputEligibilitySource, /options\.push\('queue_next'\)/);
});

test('Desktop composer steers through the socket with truthful queued fallback', () => {
  assert.match(chatPanelSource, /composeAheadQueueStore\.setIntent/);
  assert.match(chatPanelSource, /composeAheadQueueStore\.move/);
  assert.match(chatPanelSource, /composeAheadQueueStore\.applySteerFallback/);
  assert.match(chatPanelSource, /agentSteerMessageOutcome/);
  assert.match(chatPanelSource, /steerDispatchRef/);
  assert.match(chatPanelSource, /showToast\('info', t\('chat\.composeAhead\.steerFallback'\)\)/);
  assert.match(chatPanelSource, /readComposeAheadDefaultIntent/);
  assert.match(chatPanelSource, /writeComposeAheadDefaultIntent/);
  assert.match(chatPanelSource, /PickerMenu/);
  assert.match(chatPanelSource, /onDragStart/);
  assert.match(chatPanelSource, /is-intent-\$\{prompt\.intent\}/);
});

test('compose-ahead steer intent dispatches before plain queued prompts', () => {
  let sequence = 0;
  const store = createComposeAheadQueueStore({
    now: () => 3_000,
    createId: () => `intent-${(sequence += 1)}`,
  });
  const scope = 'scope-intent';
  store.enqueue(scope, { text: 'queued-first', contextItems: [] });
  store.enqueue(scope, { text: 'steer-me', contextItems: [], intent: 'steer' });
  store.enqueue(scope, { text: 'queued-last', contextItems: [] });

  // While streaming only steer prompts dispatch, ahead of FIFO position.
  const steered = store.claimNext(scope, true);
  assert.equal(steered?.text, 'steer-me');
  assert.equal(steered?.status, 'dispatching');
  assert.equal(store.claimNext(scope, true), undefined);

  store.accept(scope, steered.id);
  // Once idle, remaining prompts flush in queue order.
  assert.equal(store.claimNext(scope, false)?.text, 'queued-first');
  assert.deepEqual(
    nextComposeAheadDispatch(store.getSnapshot(scope), false)?.text,
    'queued-last',
  );
});

test('compose-ahead idle dispatch still prioritizes pending steer prompts', () => {
  let sequence = 0;
  const store = createComposeAheadQueueStore({
    now: () => 3_500,
    createId: () => `priority-${(sequence += 1)}`,
  });
  const scope = 'scope-priority';
  store.enqueue(scope, { text: 'plain', contextItems: [] });
  store.enqueue(scope, { text: 'urgent', contextItems: [], intent: 'steer' });

  assert.equal(store.claimNext(scope, false)?.text, 'urgent');
  assert.equal(store.claimNext(scope, false)?.text, 'plain');
});

test('compose-ahead move reorders prompts and clamps the target index', () => {
  let sequence = 0;
  const store = createComposeAheadQueueStore({
    now: () => 4_000,
    createId: () => `move-${(sequence += 1)}`,
  });
  const scope = 'scope-move';
  const first = store.enqueue(scope, { text: 'A', contextItems: [] });
  const second = store.enqueue(scope, { text: 'B', contextItems: [] });
  const third = store.enqueue(scope, { text: 'C', contextItems: [] });

  assert.equal(store.move(scope, third.id, 0), true);
  assert.deepEqual(
    store.getSnapshot(scope).map((prompt) => prompt.text),
    ['C', 'A', 'B'],
  );
  assert.equal(store.move(scope, first.id, 99), true);
  assert.deepEqual(
    store.getSnapshot(scope).map((prompt) => prompt.text),
    ['C', 'B', 'A'],
  );
  assert.equal(store.move(scope, first.id, 2), false);
  assert.equal(store.move(scope, 'missing', 0), false);
  assert.equal(store.move('other-scope', first.id, 0), false);
  assert.equal(store.move(scope, second.id, -5), true);
  assert.deepEqual(
    store.getSnapshot(scope).map((prompt) => prompt.text),
    ['B', 'C', 'A'],
  );
});

test('compose-ahead intent toggle and steer fallback keep queue state truthful', () => {
  let sequence = 0;
  const store = createComposeAheadQueueStore({
    now: () => 5_000,
    createId: () => `steer-${(sequence += 1)}`,
  });
  const scope = 'scope-steer';
  const prompt = store.enqueue(scope, { text: 'guide', contextItems: [] });
  assert.equal(prompt.intent, 'queue');

  assert.equal(store.setIntent(scope, prompt.id, 'steer'), true);
  assert.equal(store.getSnapshot(scope)[0]?.intent, 'steer');
  assert.equal(store.setIntent(scope, prompt.id, 'steer'), false);

  const claimed = store.claimNext(scope, true);
  assert.equal(claimed?.status, 'dispatching');
  // A dispatching steer cannot be re-toggled mid-flight.
  assert.equal(store.setIntent(scope, prompt.id, 'queue'), false);

  // Fallback demotes the steer back to a queued plain prompt atomically.
  assert.equal(store.applySteerFallback(scope, prompt.id), true);
  const demoted = store.getSnapshot(scope)[0];
  assert.equal(demoted?.status, 'queued');
  assert.equal(demoted?.intent, 'queue');
  assert.equal(store.applySteerFallback(scope, prompt.id), false);
});

test('compose-ahead default intent persists through injected storage', () => {
  assert.equal(parseComposeAheadDefaultIntent(null), 'queue');
  assert.equal(parseComposeAheadDefaultIntent('steer'), 'steer');
  assert.equal(parseComposeAheadDefaultIntent('garbage'), 'queue');
  assert.equal(readComposeAheadDefaultIntent(null), 'queue');

  const memory = new Map();
  const storage = {
    getItem: (key) => (memory.has(key) ? memory.get(key) : null),
    setItem: (key, value) => memory.set(key, value),
  };
  assert.equal(readComposeAheadDefaultIntent(storage), 'queue');
  writeComposeAheadDefaultIntent('steer', storage);
  assert.equal(memory.get(COMPOSE_AHEAD_DEFAULT_INTENT_STORAGE_KEY), 'steer');
  assert.equal(readComposeAheadDefaultIntent(storage), 'steer');
  writeComposeAheadDefaultIntent('queue', storage);
  assert.equal(readComposeAheadDefaultIntent(storage), 'queue');

  const hostileStorage = {
    getItem: () => {
      throw new Error('denied');
    },
    setItem: () => {
      throw new Error('denied');
    },
  };
  assert.equal(readComposeAheadDefaultIntent(hostileStorage), 'queue');
  writeComposeAheadDefaultIntent('steer', hostileStorage);
});
