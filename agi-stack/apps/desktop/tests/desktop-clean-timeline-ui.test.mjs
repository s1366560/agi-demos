import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'Element',
  'Node',
  'DOMParser',
  'MutationObserver',
  'ResizeObserver',
  'getComputedStyle',
  'requestAnimationFrame',
  'cancelAnimationFrame',
]) {
  const value = key === 'window' ? window : window[key];
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value:
      typeof value === 'function' &&
      ['getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame'].includes(key)
        ? value.bind(window)
        : value,
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react'),
  { act } = React,
  { createRoot } = require('react-dom/client');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents:
      "export {AgentTimeline} from './src/features/chat/ChatTimeline'; export {CurrentActivityHeadlineBar} from './src/features/chat/CurrentActivityHeadline'; export {I18nProvider} from './src/i18n'; export {ToastProvider} from './src/features/feedback/ToastCenter';",
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
    if (['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex'].includes(name))
      return value.default;
    // Node 22 loads ESM namespaces through require; preserve their default export for esbuild.
    return value?.[Symbol.toStringTag] === 'Module' ? { ...value, __esModule: true } : value;
  },
  module,
  module.exports,
);
const { AgentTimeline, CurrentActivityHeadlineBar, I18nProvider, ToastProvider } = module.exports;

function TimelineHarness({ items, running = false }) {
  const [expandedItems, setExpandedItems] = React.useState({});
  return React.createElement(AgentTimeline, {
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
    expandedItems,
    onToggleItem(item) {
      setExpandedItems((current) => ({ ...current, [item.id]: !current[item.id] }));
    },
    onLoadEarlier() {},
    onShowEarlier() {},
    earlierRenderAllowance: 50,
    onRetry() {},
    onRespondToHitl: async () => {},
    respondableHitlRequestIds: [],
    activityPresence: 'recorded',
    running,
  });
}

const call = {
  id: 'call',
  type: 'act',
  toolName: 'read_file',
  tool_execution_id: 'execution',
  toolInput: { path: 'README.md' },
  eventTimeUs: 1000,
  eventCounter: 1,
};
const result = {
  id: 'result',
  type: 'observe',
  toolName: 'read_file',
  tool_execution_id: 'execution',
  toolOutput: 'Read completed',
  eventTimeUs: 2000,
  eventCounter: 2,
};

for (const status of ['running', 'complete', 'failed']) {
  test(`tool activity is initially ${status === 'failed' ? 'expanded' : 'collapsed'} when ${status}, and respects user disclosure`, async () => {
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    const items =
      status === 'running'
        ? [call]
        : [
            call,
            {
              ...result,
              isError: status === 'failed',
              toolOutput: status === 'failed' ? 'File permission denied' : result.toolOutput,
            },
          ];
    const render = async () => {
      await act(async () =>
        root.render(
          React.createElement(
            I18nProvider,
            null,
            React.createElement(
              ToastProvider,
              null,
              React.createElement(TimelineHarness, { items }),
            ),
          ),
        ),
      );
    };
    try {
      await render();
      const group = container.querySelector('.timeline-tool-group');
      assert.ok(group, 'tool activity retains its disclosure');
      const summary = group.querySelector('summary');
      const initiallyOpen = status === 'failed';
      assert.equal(group.open, initiallyOpen);
      assert.equal(summary.getAttribute('aria-expanded'), String(initiallyOpen));
      if (status === 'failed') {
        assert.ok(
          container.querySelector('.timeline-step.status-failed'),
          'failed step stays visible',
        );
        assert.match(group.querySelector('.timeline-tool-group-preview').textContent, /read_file/);
        assert.doesNotMatch(container.textContent, /File permission denied/);
        assert.match(container.textContent, /failed|失败|错误/i);
      }
      await act(async () => summary.click());
      assert.equal(group.open, !initiallyOpen);
      await render();
      assert.equal(group.open, !initiallyOpen, 'new render preserves explicit user choice');
      await act(async () => summary.click());
      assert.equal(group.open, initiallyOpen);
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  });
}

test('local sending without artifact presence activates only the latest user turn', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const items = [
    { id: 'older-user', type: 'user_message', role: 'user', content: 'Earlier', eventTimeUs: 10 },
    { ...call, id: 'older-call', tool_execution_id: 'older', eventTimeUs: 20 },
    { id: 'current-user', type: 'user_message', role: 'user', content: 'Current', eventTimeUs: 30 },
    { ...call, id: 'current-call', tool_execution_id: 'current', eventTimeUs: 40 },
  ];
  const render = async (running) =>
    act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(
            ToastProvider,
            null,
            React.createElement(TimelineHarness, { items, running }),
          ),
        ),
      ),
    );
  try {
    await render(true);
    const groups = container.querySelectorAll('.timeline-tool-group');
    assert.equal(groups.length, 2);
    assert.match(groups[0].querySelector('summary').textContent, /Execution steps|执行记录/);
    assert.match(groups[1].querySelector('summary').textContent, /Working|正在执行/);
    assert.equal(groups[0].open, false);
    assert.equal(groups[1].open, true);
    assert.ok(groups[0].querySelector('.timeline-step.status-recorded'));
    assert.ok(groups[1].querySelector('.timeline-step.status-running'));
    await render(false);
    assert.match(groups[1].querySelector('summary').textContent, /Execution steps|执行记录/);
    assert.ok(groups[1].querySelector('.timeline-step.status-recorded'));
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test('local sending shows pre-tool working feedback and terminal completion removes it', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const user = { id: 'u', type: 'user_message', role: 'user', content: 'Start', eventTimeUs: 1000 };
  const render = async (items, running) =>
    act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(
            ToastProvider,
            null,
            React.createElement(TimelineHarness, { items, running }),
          ),
        ),
      ),
    );
  try {
    await render([user], true);
    assert.ok(container.querySelector('.timeline-working-indicator'));
    await render([user, { id: 'done', type: 'complete', eventTimeUs: 2000 }], true);
    assert.equal(Boolean(container.querySelector('.timeline-working-indicator')), false);
    await render([user], false);
    assert.equal(Boolean(container.querySelector('.timeline-working-indicator')), false);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test('adjacent diagnostic events fold into tool_group and summary shows tool preview', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  const items = [
    { id: 'u-1', type: 'user_message', role: 'user', content: 'Check file', eventTimeUs: 500 },
    { id: 'ack-1', type: 'tool_selection', content: 'accepted', eventTimeUs: 800, payload: { run_id: 'run-1' } },
    { ...call, payload: { ...call.payload, run_id: 'run-1' } },
    { ...result, payload: { ...result.payload, run_id: 'run-1' } },
    { id: 'ack-2', type: 'tool_progress', content: 'done', eventTimeUs: 2500, payload: { run_id: 'run-1' } },
  ];
  try {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(
            ToastProvider,
            null,
            React.createElement(TimelineHarness, { items }),
          ),
        ),
      ),
    );
    const groups = container.querySelectorAll('.timeline-tool-group');
    assert.equal(groups.length, 1);
    const topLevelDiagnosticLinks = [...container.querySelectorAll('.timeline-diagnostic-link')].filter(
      (el) => !el.closest('.timeline-tool-group'),
    );
    assert.equal(topLevelDiagnosticLinks.length, 0);
    const preview = groups[0].querySelector('.timeline-tool-group-preview');
    assert.ok(preview && preview.textContent.includes('read_file'));
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test('stalled activity headline exposes inline cancel button without duplicate clock', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  let cancelled = 0;
  const oldMs = Date.now() - 180_000;
  try {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(CurrentActivityHeadlineBar, {
            activity: {
              kind: 'subagent',
              label: 'builtin:sisyphus',
              titleKey: null,
              detail: 'echo',
              startedAtMs: oldMs,
              lastActivityAtMs: oldMs,
              activeSubagentCount: 1,
              entries: [],
            },
            sessionKey: 'session-1',
            presence: 'live',
            onStopResponse: () => {
              cancelled += 1;
            },
          }),
        ),
      ),
    );
    assert.ok(container.querySelector('.current-activity-headline-row .current-activity-stalled'));
    assert.equal(container.querySelector('.current-activity-headline').children.length, 1,
      'the warning stays in the existing row rather than adding footer height');
    assert.equal(container.querySelector('.current-activity-stalled-clock'), null);
    const cancelBtn = container.querySelector('.current-activity-stalled-cancel');
    assert.ok(cancelBtn);
    await act(async () => cancelBtn.click());
    assert.equal(cancelled, 1);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test('diagnostics from another run remain independently inspectable', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(I18nProvider, null,
      React.createElement(ToastProvider, null, React.createElement(TimelineHarness, { items: [
        { id: 'foreign-ack', type: 'tool_progress', content: 'accepted', eventTimeUs: 800, payload: { run_id: 'other-run' } },
        { ...call, payload: { run_id: 'current-run' } },
        { ...result, payload: { run_id: 'current-run' } },
      ] })),
    )));
    const group = container.querySelector('.timeline-tool-group');
    assert.ok(group);
    assert.ok(!JSON.parse(group.dataset.timelineAnchorMembers).includes('foreign-ack'));
    assert.ok([...container.querySelectorAll('.timeline-diagnostic-link')].some(
      (node) => !node.closest('.timeline-tool-group') &&
        JSON.parse(node.dataset.timelineAnchorMembers).includes('foreign-ack'),
    ));
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test('recorded incomplete steps use static recorded presentation without running state', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  try {
    await act(async () => root.render(React.createElement(I18nProvider, null,
      React.createElement(ToastProvider, null, React.createElement(TimelineHarness, { items: [call] })),
    )));
    const group = container.querySelector('.timeline-tool-group');
    assert.ok(group.classList.contains('status-recorded'));
    await act(async () => group.querySelector('summary').click());
    assert.ok(container.querySelector('.timeline-step.status-recorded'));
    assert.equal(container.querySelector('.timeline-step.status-running'), null);
    assert.match(container.textContent, /Recorded/);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});
