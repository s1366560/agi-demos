import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

const chatSource = [
  'features/chat/ChatPanel.tsx',
  'features/chat/ChatTimeline.tsx',
  'features/chat/ChatTranscript.tsx',
  'features/chat/chatTimelinePresentation.tsx',
].map(readSource).join('\n');
const chatStyles = readSource('features/chat/ChatPanel.css');
const i18nSource = readSource('i18n.tsx');

test('session messages use the mission-control narrative hierarchy', () => {
  assert.match(chatSource, /function NarrativeMessageFrame/);
  assert.match(chatSource, /className="session-thread-avatar"/);
  assert.match(chatSource, /className="session-message-body"/);
  assert.match(chatSource, /<MessageActionMenu content=\{content\} \/>/);
  assert.match(chatSource, /kind === 'user' \?/);
  assert.match(chatSource, /<PersonIcon \/>/);
  assert.match(chatSource, /kind === 'agent' \?/);
  assert.match(chatSource, /<CodeIcon \/>/);
  assert.match(chatSource, /<ActivityLogIcon \/>/);
  assert.match(chatStyles, /grid-template-columns: 34px minmax\(0, 1fr\)/);
  assert.match(chatStyles, /\.session-thread-message\.user \.session-message-body/);
});

test('debug activity collapses by structural event kind without text routing', () => {
  assert.match(chatSource, /groupNarrativeActivity\(buildSessionNarrative\(state\.items\)\)/);
  assert.match(
    chatSource,
    /return timelineKind\(item\) === 'runtime' && !isImportantTimelineItem\(item\)/,
  );
  assert.match(chatSource, /className="timeline-debug-group"/);
  assert.match(chatSource, /className=\{`timeline-tool-group status-\$\{node\.status\}`\}/);
  assert.doesNotMatch(chatSource, /open=\{node\.status !== 'complete'/);
  assert.doesNotMatch(chatSource, /match\([^)]*item\.(content|description|reason)/);
});

test('raw task and error payloads stay collapsed until a person opens them', () => {
  const importancePolicy = chatSource.match(
    /function isImportantTimelineItem\(item: AgentTimelineItem\): boolean \{[\s\S]*?\n\}/,
  )?.[0];

  assert.ok(importancePolicy, 'timeline importance policy must remain explicit');
  assert.match(importancePolicy, /timelineHitlType\(item\) && !item\.answered/);
  assert.match(importancePolicy, /item\.type === 'work_plan'/);
  assert.doesNotMatch(importancePolicy, /item\.isError|item\.error/);
  assert.doesNotMatch(importancePolicy, /startsWith\('task_'\)|artifact_error/);
});

test('session composer exposes localized context actions and compact delivery controls', () => {
  assert.match(chatSource, /t\('session\.attach'\)/);
  assert.match(chatSource, /t\('session\.context'\)/);
  assert.match(chatSource, /className="composer-delivery-switch"/);
  assert.match(chatSource, /t\('session\.steerNow'\)/);
  assert.match(chatSource, /t\('session\.queueNext'\)/);
  assert.match(chatStyles, /\.session-composer-context-actions/);
  assert.match(chatStyles, /\.session-chat-narrative \.composer-delivery-switch/);
});

test('chat copy and diagnostics are localized in both supported locales', () => {
  for (const key of [
    'session.today',
    'session.workspaceAgent',
    'session.runActivity',
    'session.activityMemoryCaptured',
    'session.activityUpdated',
    'session.activityCheckpoint',
    'session.failedShort',
    'chat.messageActions',
    'chat.copyMessage',
    'chat.status.waitingForInput',
    'chat.workflowShortcuts',
  ]) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length,
      2,
      `${key} must exist in English and Chinese`,
    );
  }
  assert.doesNotMatch(chatSource, /aria-label="[A-Za-z]/);
  assert.doesNotMatch(chatSource, /placeholder="[A-Za-z]/);
});

test('narrative content is bounded without discarding authoritative markdown', () => {
  assert.match(chatStyles, /\.session-message-body[\s\S]*max-width: 100%/);
  assert.match(chatStyles, /\.markdown-content table[\s\S]*overflow-x: auto/);
  assert.match(chatStyles, /\.timeline-details pre[\s\S]*overflow: auto/);
  assert.match(chatSource, /const REMARK_PLUGINS = \[remarkGfm\]/);
  assert.match(
    chatSource,
    /<ReactMarkdown remarkPlugins=\{REMARK_PLUGINS\} components=\{MARKDOWN_COMPONENTS\}>/,
  );
});
