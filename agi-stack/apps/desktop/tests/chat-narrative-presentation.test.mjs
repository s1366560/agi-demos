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
  assert.match(chatSource, /className="session-message-body"/);
  assert.match(chatSource, /<MessageActionMenu content=\{content\} \/>/);
  assert.doesNotMatch(chatSource, /className="session-thread-avatar"/);
  assert.match(chatSource, /className="session-message-context sr-only"/);
  assert.match(chatStyles, /\.session-thread-message\.user \{[\s\S]*background: #161d27/);
  assert.match(chatStyles, /\.session-thread-message\.agent \{[\s\S]*background: transparent/);
  assert.match(chatStyles, /\.session-thread-message\.agent \.transcript-meta \{[\s\S]*opacity: 0/);
});

test('debug activity collapses by structural event kind without text routing', () => {
  assert.match(chatSource, /groupNarrativeActivity\(buildSessionNarrative\(displayItems\)\)/);
  assert.match(
    chatSource,
    /return timelineKind\(item\) === 'runtime' && !isImportantTimelineItem\(item\)/,
  );
  assert.match(chatSource, /className="timeline-debug-group"/);
  assert.match(chatSource, /className=\{`timeline-tool-group status-\$\{node\.status\}`\}/);
  assert.match(chatSource, /toolCallPresentationKind\(pair\)/);
  assert.match(chatSource, /className=\{`timeline-worklog-row kind-\$\{presentationKind\}/);
  assert.doesNotMatch(chatSource, /open=\{node\.status !== 'complete'/);
  assert.doesNotMatch(chatSource, /match\([^)]*item\.(content|description|reason)/);
  assert.match(chatStyles, /\.timeline-tool-group,[\s\S]*border: 0;[\s\S]*background: transparent/);
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

test('doom-loop detection is immediately visible without expanding routine activity', () => {
  const importancePolicy = chatSource.match(
    /function isImportantTimelineItem\(item: AgentTimelineItem\): boolean \{[\s\S]*?\n\}/,
  )?.[0];

  assert.ok(importancePolicy, 'timeline importance policy must remain explicit');
  assert.match(importancePolicy, /item\.type === 'doom_loop_detected'/);
  assert.doesNotMatch(importancePolicy, /item\.type === 'doom_loop_intervened'/);
  assert.match(
    chatSource,
    /function isTimelineItemInitiallyExpanded[\s\S]*isImportantTimelineItem\(item\)[\s\S]*doom_loop_detected/,
  );
  assert.match(
    chatSource,
    /expanded=\{expandedItems\[item\.id\] \?\? isTimelineItemInitiallyExpanded\(item\)\}/,
  );
  assert.match(
    chatSource,
    /current\[item\.id\] \?\? isTimelineItemInitiallyExpanded\(item\)/,
  );
});

test('conversation terminal events stay visible while their raw payloads stay collapsed', () => {
  const importancePolicy = chatSource.match(
    /function isImportantTimelineItem\(item: AgentTimelineItem\): boolean \{[\s\S]*?\n\}/,
  )?.[0];
  const expansionPolicy = chatSource.match(
    /function isTimelineItemInitiallyExpanded\(item: AgentTimelineItem\): boolean \{[\s\S]*?\n\}/,
  )?.[0];

  assert.ok(importancePolicy, 'timeline importance policy must remain explicit');
  assert.ok(expansionPolicy, 'timeline expansion policy must remain explicit');
  assert.match(importancePolicy, /agent_goal_completed/);
  assert.match(importancePolicy, /agent_conversation_finished/);
  assert.match(expansionPolicy, /agent_goal_completed/);
  assert.match(expansionPolicy, /agent_conversation_finished/);
});

test('narrow session timelines preserve lifecycle status labels', () => {
  assert.match(
    chatStyles,
    /@container \(max-width: 520px\)[\s\S]*timeline-row-meta > span:not\(:last-child\):not\(\.timeline-status\)/,
  );
});

test('artifact batch events use artifact presentation instead of generic runtime presentation', () => {
  assert.match(
    chatSource,
    /item\.type\.startsWith\('artifact_'\) \|\| item\.type === 'artifacts_batch'/,
  );
  assert.match(chatSource, /item\.type === 'artifact_created'[\s\S]*chat\.artifactCreated/);
  assert.match(chatSource, /item\.type === 'artifact_ready'[\s\S]*chat\.artifactReady/);
  assert.match(chatSource, /item\.type === 'artifact_error'[\s\S]*chat\.artifactFailed/);
  assert.match(chatSource, /item\.type === 'artifacts_batch'[\s\S]*chat\.artifactsBatch/);
});

test('agent suggestions render as actionable follow-ups without becoming timeline log rows', () => {
  assert.match(chatSource, /latestAgentSuggestions\(/);
  assert.match(chatSource, /timelineItemsForDisplay\(/);
  assert.match(chatSource, /<AgentSuggestionChips/);
  assert.match(chatSource, /activityPresence === 'recorded'/);
  assert.match(chatSource, /handleComposerSend\(suggestion, \[\]\)/);
  assert.match(chatStyles, /\.agent-suggestion-list/);
  assert.match(chatStyles, /\.agent-suggestion-chip/);
});

test('session composer exposes localized context actions and compact delivery controls', () => {
  assert.match(chatSource, /<ComposerPlusMenu/);
  assert.match(chatSource, /t\('composer\.addedContext'\)/);
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
    'session.workedFor',
    'session.toolKind.command',
    'session.toolKind.edit',
    'session.runActivity',
    'session.activityMemoryCaptured',
    'session.activityUpdated',
    'session.activityCheckpoint',
    'session.failedShort',
    'chat.messageActions',
    'chat.copyMessage',
    'chat.status.waitingForInput',
    'chat.status.blocked',
    'chat.routingDecision',
    'chat.toolSelection',
    'chat.toolPolicy',
    'chat.toolsetChange',
    'chat.toolsCount',
    'chat.toolsProgress',
    'chat.filteredToolsCount',
    'chat.skillMatched',
    'chat.skillExecution',
    'chat.skillTool',
    'chat.skillFallback',
    'chat.modelSwitch',
    'chat.modelOverride',
    'chat.contextStatus',
    'chat.contextCompressed',
    'chat.mcpAppRegistered',
    'chat.mcpAppResult',
    'chat.memoryRecalled',
    'chat.memoryCaptured',
    'chat.taskStarted',
    'chat.taskCompleted',
    'chat.artifactCreated',
    'chat.artifactReady',
    'chat.artifactFailed',
    'chat.artifactsBatch',
    'chat.artifactsCount',
    'chat.sandboxEvent',
    'chat.desktopEvent',
    'chat.terminalEvent',
    'chat.httpServiceEvent',
    'chat.doomLoopDetected',
    'chat.doomLoopIntervened',
    'chat.agentGoalCompleted',
    'chat.agentConversationFinished',
    'chat.callsCount',
    'chat.suggestedFollowUps',
    'chat.sendSuggestion',
    'chat.memoriesCount',
    'chat.tokensCount',
    'chat.tokensProgress',
    'chat.messagesCount',
    'chat.messagesProgress',
    'chat.status.scheduled',
    'chat.workflowShortcuts',
    'chat.executionSummary',
    'chat.summary.steps',
    'chat.summary.tasks',
    'chat.summary.remaining',
    'chat.summary.artifacts',
    'chat.summary.calls',
    'chat.summary.tokens',
    'chat.summary.cost',
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

test('completed Agent replies render the authoritative execution summary', () => {
  assert.match(chatSource, /function AssistantExecutionSummary/);
  assert.match(chatSource, /assistantExecutionSummary\(item\)/);
  assert.match(chatSource, /className="assistant-execution-summary"/);
  assert.match(chatStyles, /\.assistant-execution-summary/);
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
