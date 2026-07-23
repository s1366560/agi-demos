import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  composeAheadConversationScope,
  composeAheadContextSnapshot,
  composeAheadEligibility,
  conversationResponseIsStreaming,
  createComposeAheadQueueStore,
} from '/tmp/agistack-desktop-test-dist/src/features/chat/composeAheadModel.js';

const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
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
  assert.match(chatPanelSource, /composeAheadQueueStore\.claimHead/);
  assert.match(chatPanelSource, /composeAheadQueueStore\.accept/);
  assert.match(chatPanelSource, /composeAheadQueueStore\.retry/);
  assert.match(chatPanelSource, /dispatchMonitorRef/);
  assert.match(chatPanelSource, /window\.clearTimeout\(dispatchMonitorRef\.current\.timerId\)/);
});
