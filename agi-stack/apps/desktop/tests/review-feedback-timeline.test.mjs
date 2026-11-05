import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents: [
      "export {AgentTimeline} from './src/features/chat/ChatTimeline';",
      "export {I18nProvider} from './src/i18n';",
      "export {ToastProvider} from './src/features/feedback/ToastCenter';",
      "export {timelineItemFromSocketEvent,mergeLiveTimelineEvent} from './src/features/chat/appTimelineEventModel';",
      "export {mergeConversationTimelineItems,timelineItemsForDisplay} from './src/features/chat/chatTimelineModel';",
      "export {timelineKind} from './src/features/chat/chatTimelinePresentation';",
    ].join('\n'),
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false,
  bundle: true,
  platform: 'node',
  format: 'cjs',
  packages: 'external',
  loader: { '.css': 'empty', '.svg': 'text' },
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.PROD': 'true' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  (name) => {
    const value = require(name);
    return ['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex'].includes(name)
      ? value.default
      : value;
  },
  module,
  module.exports
);
const {
  AgentTimeline,
  I18nProvider,
  ToastProvider,
  timelineItemFromSocketEvent,
  mergeLiveTimelineEvent,
  mergeConversationTimelineItems,
  timelineItemsForDisplay,
  timelineKind,
} = module.exports;

// Shape emitted by native append_review_decision: a review remains in its original run/turn.
const feedbackEvent = (extra = {}) => ({
  id: 'review_decision-2000000-2',
  type: 'review_decision',
  event_type: 'review_decision',
  conversation_id: 'conversation',
  message_id: 'original-message',
  eventTimeUs: 2000000,
  eventCounter: 2,
  role: 'user',
  content: 'Continue the missing fixture step.',
  data: {
    run_id: 'run',
    revision: 4,
    decision_id: 'decision',
    action: 'request_changes',
    feedback: 'Continue the missing fixture step.',
    source: 'local_user',
    role: 'user',
    content: 'Continue the missing fixture step.',
  },
  ...extra,
});

const renderTimeline = (items) =>
  renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(
        ToastProvider,
        null,
        React.createElement(AgentTimeline, {
          imagePreviewClient: null,
          state: {
            conversationId: 'conversation',
            items,
            approvalRequests: [],
            artifactVersions: [],
            artifactDeliveries: [],
            toolInvocations: [],
            loading: false,
            loadingEarlier: false,
            error: null,
            hasMore: false,
            firstCursor: null,
            lastCursor: null,
          },
          expandedItems: {},
          onToggleItem() {},
          onLoadEarlier() {},
          onShowEarlier() {},
          earlierRenderAllowance: 50,
          onRetry() {},
          onRespondToHitl: async () => {},
          respondableHitlRequestIds: [],
          activityPresence: 'recorded',
        })
      )
    )
  );

test('native review feedback preserves its explicit user role/content and original run identity', () => {
  const event = feedbackEvent({ content: '  Preserve\nthis exact feedback.  ' });
  const item = timelineItemFromSocketEvent(event);
  assert.equal(item.type, 'review_decision');
  assert.equal(item.role, 'user');
  assert.equal(item.content, event.content);
  assert.equal(item.message_id, 'original-message');
  assert.equal(item.executionMessageId, undefined);
  assert.equal(item.payload.revision, 4);
  assert.equal(timelineKind(item), 'user');
  const nested = feedbackEvent();
  delete nested.role;
  delete nested.content;
  assert.equal(timelineItemFromSocketEvent(nested).role, 'user');
  assert.equal(timelineItemFromSocketEvent(nested).content, nested.data.content);
});

test('approval and malformed review events never infer a user bubble from feedback text', () => {
  const cases = [
    feedbackEvent({ data: { action: 'approve', role: 'user', feedback: null } }),
    feedbackEvent({ role: 'assistant' }),
    feedbackEvent({ role: '', data: { action: 'request_changes', role: 'user', content: 'body' } }),
    feedbackEvent({
      role: undefined,
      data: { action: 'request_changes', feedback: 'I am a user' },
    }),
    feedbackEvent({
      content: ' ',
      data: { action: 'request_changes', role: 'user', feedback: 'body' },
    }),
    feedbackEvent({
      content: undefined,
      data: { action: 'request_changes', role: 'user', feedback: 'body' },
    }),
  ];
  for (const event of cases) {
    const item = timelineItemFromSocketEvent(event);
    assert.equal(item.role, undefined);
    assert.equal(item.content, undefined);
    assert.equal(timelineKind(item), 'runtime');
    assert.equal(
      timelineItemsForDisplay([item]).filter((entry) => entry.role === 'user').length,
      0
    );
    assert.doesNotMatch(renderTimeline([item]), /transcript-message[^>]*\buser\b/);
  }
});

test('live feedback, repeated socket delivery and persisted history produce one feedback bubble', () => {
  const original = {
    id: 'user_message-1000000-1',
    type: 'user_message',
    role: 'user',
    content: 'Original request.',
    message_id: 'original-message',
    eventTimeUs: 1000000,
    eventCounter: 1,
  };
  const event = feedbackEvent();
  const live = mergeLiveTimelineEvent(mergeLiveTimelineEvent([original], event), event);
  const history = {
    id: event.id,
    type: event.type,
    role: event.role,
    content: event.content,
    message_id: event.message_id,
    eventTimeUs: event.eventTimeUs,
    eventCounter: event.eventCounter,
    payload: event.data,
  };
  for (const items of [
    mergeConversationTimelineItems(live, [history]),
    mergeConversationTimelineItems([original, history], live),
  ]) {
    const visible = timelineItemsForDisplay(items);
    assert.equal(visible.filter((item) => item.id === history.id).length, 1);
    assert.equal(visible.filter((item) => item.role === 'user').length, 2);
    const html = renderTimeline(items);
    assert.equal((html.match(/Continue the missing fixture step\./g) ?? []).length, 1);
    assert.equal(
      (html.match(/data-timeline-anchor-id="review_decision-2000000-2"/g) ?? []).length,
      1
    );
    assert.match(html, /Original request\./);
    assert.match(html, /transcript-message[^>]*\buser\b/);
  }
});
