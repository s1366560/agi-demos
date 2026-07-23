import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  conversationExportFilename,
  conversationExportToHtml,
  conversationExportToMarkdown,
  createConversationExportSnapshot,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/conversationExportModel.js',
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const chatPanelSource = readSource('features/chat/ChatPanel.tsx');
const exportMenuSource = readSource('features/chat/ConversationExportMenu.tsx');
const chatStyles = readSource('features/chat/ChatPanel.css');
const i18nSource = readSource('i18n.tsx');
const packageSource = readFileSync(new URL('../package.json', import.meta.url), 'utf8');

const baseTimeUs = Date.parse('2026-07-24T00:00:00.000Z') * 1_000;
const longToolOutput = `${'x'.repeat(520)}<private>`;
const sourceItems = [
  {
    id: 'user-1',
    type: 'user_message',
    eventTimeUs: baseTimeUs,
    eventCounter: 1,
    content: 'Inspect the export.',
  },
  {
    id: 'thought-1',
    type: 'thought',
    eventTimeUs: baseTimeUs + 1_000_000,
    eventCounter: 2,
    content: 'I should preserve event order.',
  },
  {
    id: 'act-1',
    type: 'act',
    eventTimeUs: baseTimeUs + 2_000_000,
    eventCounter: 3,
    toolName: 'read_file',
    toolInput: { path: '/workspace/report.md' },
  },
  {
    id: 'observe-1',
    type: 'observe',
    eventTimeUs: baseTimeUs + 3_000_000,
    eventCounter: 4,
    toolName: 'read_file',
    toolOutput: longToolOutput,
    isError: true,
  },
  {
    id: 'assistant-1',
    type: 'assistant_message',
    eventTimeUs: baseTimeUs + 4_000_000,
    eventCounter: 5,
    content: 'Export ready.',
  },
  {
    id: 'ack-1',
    type: 'ack',
    eventTimeUs: baseTimeUs + 5_000_000,
    eventCounter: 6,
  },
];

const snapshot = createConversationExportSnapshot({
  conversationId: 'conversation-123',
  title: 'Export test',
  items: sourceItems,
});

const renderOptions = {
  exportedAt: new Date('2026-07-24T01:02:03.000Z'),
  formatTimestamp: (timestampMs) => new Date(timestampMs).toISOString(),
};

test('conversation export snapshots ordered Web-supported events by value', () => {
  assert.equal(snapshot.conversationId, 'conversation-123');
  assert.equal(snapshot.title, 'Export test');
  assert.deepEqual(
    snapshot.events.map((event) => event.type),
    ['user_message', 'thought', 'act', 'observe', 'assistant_message'],
  );
  assert.equal(snapshot.events[2].toolInput, '{\n  "path": "/workspace/report.md"\n}');
  assert.equal(snapshot.events[3].toolOutput, longToolOutput);

  sourceItems[0].content = 'Changed after export';
  sourceItems[2].toolInput.path = '/workspace/changed.md';
  assert.equal(snapshot.events[0].content, 'Inspect the export.');
  assert.equal(snapshot.events[2].toolInput, '{\n  "path": "/workspace/report.md"\n}');
});

test('Markdown export mirrors Web labels, ordering, filename, and 500-character truncation', () => {
  const markdown = conversationExportToMarkdown(snapshot, renderOptions);
  assert.equal(conversationExportFilename(snapshot, 'markdown'), 'conversation-conversation-123.md');
  assert.ok(markdown.startsWith('# Conversation Export\n\n> Exported at 2026-07-24T01:02:03.000Z'));
  assert.ok(
    markdown.indexOf('## User') <
      markdown.indexOf('<details><summary>Thinking</summary>'),
  );
  assert.ok(
    markdown.indexOf('<details><summary>Thinking</summary>') <
      markdown.indexOf('> **Tool Call**: `read_file`'),
  );
  assert.ok(markdown.includes('> **Result** (read_file) Error'));
  assert.ok(markdown.includes(`${'x'.repeat(500)}...(truncated)`));
  assert.ok(!markdown.includes('x'.repeat(501)));
  assert.ok(markdown.endsWith('Export ready.\n'));
});

test('PDF HTML mirrors Web ordering, escaping, filename, and 300-character truncation', () => {
  const html = conversationExportToHtml(snapshot, renderOptions);
  assert.equal(conversationExportFilename(snapshot, 'pdf'), 'conversation-conversation-123.pdf');
  assert.ok(html.includes('Conversation Export'));
  assert.ok(html.includes('Exported at 2026-07-24T01:02:03.000Z'));
  assert.ok(html.indexOf('User - 2026-07-24T00:00:00.000Z') < html.indexOf('Thinking:'));
  assert.ok(html.indexOf('Thinking:') < html.indexOf('<strong>Tool:</strong>'));
  assert.ok(html.includes(`${'x'.repeat(300)}...`));
  assert.ok(!html.includes('x'.repeat(301)));
  assert.ok(!html.includes('<private>'));
});

test('Desktop exposes localized, accessible renderer-only Markdown and PDF controls', () => {
  assert.match(chatPanelSource, /createConversationExportSnapshot/);
  assert.match(chatPanelSource, /<ConversationExportMenu/);
  assert.match(exportMenuSource, /downloadConversationMarkdown/);
  assert.match(exportMenuSource, /downloadConversationPdf/);
  assert.match(exportMenuSource, /aria-label=\{t\('chat\.exportConversation'\)\}/);
  assert.match(exportMenuSource, /aria-busy=\{exportingFormat !== null\}/);
  assert.match(exportMenuSource, /role=\{notice\.kind === 'error' \? 'alert' : 'status'\}/);
  assert.match(exportMenuSource, /\.focus\(\)/);
  assert.match(chatStyles, /\.chat-conversation-export/);
  assert.equal(i18nSource.match(/'chat\.exportConversation':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.exportMarkdown':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.exportPdf':/g)?.length, 2);
  assert.equal(i18nSource.match(/'chat\.exportFailed':/g)?.length, 2);
  assert.match(packageSource, /"html2pdf\.js": "\^0\.14\.0"/);
  assert.doesNotMatch(exportMenuSource, /ipcRenderer|window\.desktop|window\.electron/);
});
