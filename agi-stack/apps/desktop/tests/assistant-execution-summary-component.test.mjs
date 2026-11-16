import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents: "export {AgentTimeline} from './src/features/chat/ChatTimeline'; export {I18nProvider} from './src/i18n'; export {ToastProvider} from './src/features/feedback/ToastCenter';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false, bundle: true, platform: 'node', format: 'cjs', packages: 'external',
  loader: { '.css': 'empty', '.svg': 'text' },
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.PROD': 'true' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  (name) => {
    const value = require(name);
    if (['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex'].includes(name)) return value.default;
    return value?.[Symbol.toStringTag] === 'Module' ? { ...value, __esModule: true } : value;
  }, module, module.exports,
);
const { AgentTimeline, I18nProvider, ToastProvider } = module.exports;

function render(metadata) {
  return renderToStaticMarkup(React.createElement(I18nProvider, null,
    React.createElement(ToastProvider, null, React.createElement(AgentTimeline, {
      imagePreviewClient: null,
      state: {
        conversationId: 'summary-test',
        items: [{ id: 'answer', type: 'assistant_message', role: 'assistant',
          content: 'Readable answer first.', metadata, eventTimeUs: 1000000, eventCounter: 1 }],
        approvalRequests: [], artifactVersions: [], artifactDeliveries: [], toolInvocations: [],
        loading: false, loadingEarlier: false, error: null, hasMore: false,
        firstCursor: null, lastCursor: null,
      },
      expandedItems: {}, onToggleItem: () => {}, onLoadEarlier: () => {},
      onShowEarlier: () => {}, earlierRenderAllowance: 0, onRetry: () => {},
      onRespondToHitl: async () => {}, respondableHitlRequestIds: [], activityPresence: 'recorded',
    })),
  ));
}

test('execution metrics follow the answer in a closed native disclosure', () => {
  const html = render({ executionSummary: {
    stepCount: 2, callCount: 3, totalTokens: { input: 100, output: 20, total: 120 },
    totalCost: 0.02, totalCostFormatted: '$0.020000',
  } });
  const disclosure = html.match(/<details[^>]*class="assistant-execution-summary"[^>]*>/)?.[0];
  assert.ok(disclosure);
  assert.doesNotMatch(disclosure, /\bopen(?:=|\s|>)/);
  assert.match(html, /<summary>Execution summary<\/summary>/);
  assert.ok(html.indexOf('Readable answer first.') < html.indexOf(disclosure));
  assert.match(html, /<small>Tokens<\/small><strong>120<\/strong>/);
  assert.match(html, /<small>Input<\/small><strong>100<\/strong>/);
  assert.match(html, /<small>Output<\/small><strong>20<\/strong>/);
  assert.match(html, /\$0\.020000/);
});

test('answers without execution evidence do not create an empty disclosure', () => {
  const html = render({});
  assert.match(html, /Readable answer first\./);
  assert.doesNotMatch(html, /assistant-execution-summary/);
});
