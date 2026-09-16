import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// Desktop conversation-flow parity with the web client (audit sections 1.7,
// 1.8, 1.11): streaming tool-call "preparing" state, code-block header
// casing/short-snippet suppression, and markdown heading scale.

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { ToastProvider } = require('/tmp/agistack-desktop-test-dist/src/features/feedback/ToastCenter.js');
const { CodeBlockFrame } = require('/tmp/agistack-desktop-test-dist/src/features/chat/HighlightedCode.js');

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const chatTimelineSource = readSource('features/chat/ChatTimeline.tsx');
const chatTimelineCss = readSource('features/chat/ChatTimeline.css');
const highlightedCodeSource = readSource('features/chat/HighlightedCode.tsx');
const chatTimelineModelSource = readSource('features/chat/chatTimelineModel.ts');
const i18nSource = readSource('i18n.tsx');

function withStoredLocale(locale, render) {
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: (key) => (key === 'agistack.desktop.locale' ? locale : null),
      setItem: () => {},
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    return render();
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
}

function renderCodeBlock(props) {
  return withStoredLocale('en', () =>
    renderToStaticMarkup(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(
          ToastProvider,
          null,
          React.createElement(CodeBlockFrame, props),
        ),
      ),
    ),
  );
}

// --- 1.7 Streaming "preparing" state ---------------------------------------

test('preparing status flows from the stream-merge model into the timeline row', () => {
  // The model owns the signal: act_delta merges set argsStreaming, the
  // canonical act clears it, and pair status surfaces "preparing".
  assert.match(chatTimelineModelSource, /argsStreaming: kind === 'delta'/);
  assert.match(
    chatTimelineModelSource,
    /export type ToolCallPairStatus = 'preparing' \| 'running' \| 'complete' \| 'failed'/,
  );
  assert.match(chatTimelineModelSource, /if \(toolCallArgumentsStreaming\(pair\.call\)\) return 'preparing'/);

  // The row renders the web-style blue pill with a pulsing dot and keeps the
  // live arguments block visible instead of the collapsed details.
  assert.match(chatTimelineSource, /status === 'preparing'/);
  assert.match(chatTimelineSource, /className="timeline-status preparing"/);
  assert.match(chatTimelineSource, /className="timeline-status-dot"/);
  assert.match(chatTimelineSource, /t\('chat\.status\.preparing'\)/);
  assert.match(chatTimelineSource, /<ToolCallPreparingBody pair=\{pair\} \/>/);
  assert.match(chatTimelineSource, /t\('chat\.buildingArguments'\)/);
  assert.match(chatTimelineSource, /t\('chat\.preparingToolCall'\)/);
  assert.match(chatTimelineSource, /className="timeline-tool-args-stream"/);
  assert.match(chatTimelineSource, /className="timeline-tool-args-caret"/);
  assert.match(chatTimelineSource, /className="timeline-tool-preparing-empty"/);
});

test('preparing styles use the running blue family with reduced-motion fallbacks', () => {
  assert.match(chatTimelineCss, /\.timeline-status\.preparing \{[\s\S]*?--desktop-status-running-rgb/);
  assert.match(chatTimelineCss, /\.timeline-rail-dot\.is-preparing \{/);
  assert.match(chatTimelineCss, /\.timeline-details pre\.timeline-tool-args-stream \{/);
  assert.match(chatTimelineCss, /\.timeline-tool-args-caret \{[\s\S]*?animation: tool-preparing-pulse/);
  assert.match(chatTimelineCss, /\.timeline-tool-preparing-empty \{[\s\S]*?border: 1px dashed/);
  assert.match(
    chatTimelineCss,
    /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\.timeline-status-dot,[\s\S]*?\.timeline-tool-args-caret[\s\S]*?animation: none/,
  );
});

test('the desktop-only streaming caret CSS is removed', () => {
  assert.ok(!chatTimelineCss.includes('.streaming-caret'));
  assert.ok(!chatTimelineCss.includes('streaming-caret-blink'));
});

test('preparing i18n keys exist in both dictionaries', () => {
  for (const key of [
    'chat.status.preparing',
    'chat.buildingArguments',
    'chat.preparingToolCall',
  ]) {
    const occurrences = i18nSource.split(`'${key}':`).length - 1;
    assert.equal(occurrences, 2, `${key} must exist in en and zh dictionaries`);
  }
});

// --- 1.8 Code blocks --------------------------------------------------------

test('short single-line snippets render without the header (web heuristic)', () => {
  assert.match(
    highlightedCodeSource,
    /const isShortSnippet = !code\.includes\('\\n'\) && code\.length < 80/,
  );

  const shortMarkup = renderCodeBlock({ code: 'const answer = 42;', language: 'ts' });
  assert.ok(!shortMarkup.includes('code-block-head'), 'short snippet omits the header');
  assert.match(shortMarkup, /code-block-frame is-headerless/);
  assert.match(shortMarkup.replace(/<[^>]+>/g, ''), /const answer = 42;/);

  const longMarkup = renderCodeBlock({
    code: `const answer = 42;\nconsole.log(answer);`,
    language: 'ts',
  });
  assert.match(longMarkup, /code-block-head/);
  assert.match(longMarkup, /code-block-lang">typescript</);
  assert.match(longMarkup, /aria-label="Copy code"/);
});

test('single-line snippets of 80+ characters keep the header', () => {
  const markup = renderCodeBlock({
    code: `export const token = "${'a'.repeat(90)}";`,
    language: 'ts',
  });
  assert.match(markup, /code-block-head/);
});

test('code-block language label is normal-case xs medium, not uppercase tracked', () => {
  assert.match(chatTimelineCss, /\.code-block-lang \{[\s\S]*?font-size: var\(--desktop-text-xs\);[\s\S]*?font-weight: 500;/);
  const langRule = chatTimelineCss.match(/\.code-block-lang \{[\s\S]*?\}/)?.[0] ?? '';
  assert.ok(!langRule.includes('text-transform'), 'label must not uppercase');
  assert.ok(!langRule.includes('letter-spacing'), 'label must not track');
});

// --- 1.11 Markdown headings --------------------------------------------------

test('markdown headings keep a real scale with semibold weight', () => {
  assert.match(chatTimelineCss, /\.markdown-content h1 \{[\s\S]*?font-size: 1\.75em;/);
  assert.match(chatTimelineCss, /\.markdown-content h2 \{[\s\S]*?font-size: 1\.5em;/);
  assert.match(chatTimelineCss, /\.markdown-content h3 \{[\s\S]*?font-size: 1\.25em;/);
  const sharedRule =
    chatTimelineCss.match(
      /\.markdown-content h1,\s*\.markdown-content h2,\s*\.markdown-content h3,\s*\.markdown-content h4,\s*\.markdown-content h5,\s*\.markdown-content h6 \{\s*color: var\(--desktop-chat-text\);\s*font-weight: 600;\s*line-height: 1\.4;\s*\}/,
    )?.[0] ?? '';
  assert.match(sharedRule, /font-weight: 600;/);
  assert.ok(!chatTimelineCss.includes('font-size: 1.06em'), 'old flat cap removed');
});
