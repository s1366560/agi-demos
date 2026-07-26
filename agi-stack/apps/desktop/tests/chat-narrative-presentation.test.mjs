import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  canConfirmMessageDeletion,
  filterHiddenMessages,
  findRetryMessageContent,
  hideMessageInScope,
  messageActionsForVisibleMessage,
  messageDeletionExcerpt,
  messageDeletionFocusNeighborId,
  quoteMessageForComposer,
  resolveRetryDispatch,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/chatMessageActionModel.js',
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
const readOptionalSource = (path) => {
  const url = new URL(`../src/${path}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
};

const chatSource = [
  'features/chat/ChatPanel.tsx',
  'features/chat/ChatTimeline.tsx',
  'features/chat/ChatTranscript.tsx',
  'features/chat/chatTimelinePresentation.tsx',
].map(readSource).join('\n');
const chatStyles = readSource('features/chat/ChatPanel.css');
const i18nSource = readSource('i18n.tsx');
const appSource = readSource('App.tsx');
const conversationSummarySource = readOptionalSource(
  'features/chat/ConversationSummaryCard.tsx',
);
const conversationSummaryQaSource = readOptionalSource(
  'qa/ConversationSummaryQa.tsx',
);
const lifecycleVisibilityQaSource = readOptionalSource(
  'qa/LifecycleVisibilityQa.tsx',
);
const aggregatedSourcesSource = readOptionalSource(
  'features/chat/AggregatedSourcesCard.tsx',
);
const aggregatedSourcesQaSource = readOptionalSource(
  'qa/AggregatedSourcesQa.tsx',
);
const sessionConversationQaSource = readSource('qa/SessionConversationQa.tsx');

test('session messages use the mission-control narrative hierarchy', () => {
  assert.match(chatSource, /function NarrativeMessageFrame/);
  assert.match(chatSource, /className="session-message-body"/);
  assert.match(chatSource, /<MessageActionMenu[\s\S]*content=\{content\}/);
  assert.doesNotMatch(chatSource, /className="session-thread-avatar"/);
  assert.match(chatSource, /className="session-message-context sr-only"/);
  assert.match(chatStyles, /\.session-thread-message\.user \{[\s\S]*background: #161d27/);
  assert.match(chatStyles, /\.session-thread-message\.agent \{[\s\S]*background: transparent/);
  assert.match(chatStyles, /\.session-thread-message\.agent \.transcript-meta \{[\s\S]*opacity: 0/);
  assert.match(
    chatStyles,
    /\.session-chat-narrative \.message\.session-thread-message\.user \{[\s\S]*width: fit-content;[\s\S]*margin-left: auto;/,
  );
});

test('selected cloud conversations expose the Web-compatible summary surface', () => {
  assert.match(chatSource, /<ConversationSummaryCard/);
  assert.match(
    chatSource,
    /summary=\{composeAheadConversation\?\.summary \?\? null\}/,
  );
  assert.match(
    chatSource,
    /regenerationAvailable=\{turnCollapseRuntime\.mode === 'cloud'\}/,
  );
  assert.match(
    appSource,
    /onRegenerateConversationSummary=\{regenerateConversationSummary\}/,
  );
  const summaryHandlerSource =
    appSource.match(
      /const regenerateConversationSummary = async[\s\S]*?\n  };\n\n  const deleteConversation/,
    )?.[0] ?? '';
  assert.doesNotMatch(summaryHandlerSource, /!normalizedWorkspaceId/);
  assert.match(conversationSummarySource, /aria-expanded=\{expanded\}/);
  assert.match(conversationSummarySource, /role="alert"/);
  assert.match(conversationSummarySource, /session\.conversationSummaryRegenerate/);
  assert.match(conversationSummarySource, /session\.conversationSummaryLocalOnly/);
  assert.match(chatStyles, /\.conversation-summary-card/);
  assert.match(i18nSource, /'session\.conversationSummaryTitle'/);
  assert.match(conversationSummaryQaSource, /data-testid="summary-request-log"/);
  assert.match(conversationSummaryQaSource, /data-testid="summary-selection"/);
});

test('message action availability matches the Web role and streaming contract', () => {
  assert.deepEqual(messageActionsForVisibleMessage('user', false), {
    copy: true,
    reply: true,
    edit: true,
    delete: true,
    retry: false,
    retryDisabled: false,
    saveTemplate: false,
  });
  assert.deepEqual(messageActionsForVisibleMessage('agent', false), {
    copy: true,
    reply: true,
    edit: false,
    delete: false,
    retry: true,
    retryDisabled: false,
    saveTemplate: true,
  });
  assert.deepEqual(messageActionsForVisibleMessage('agent', true), {
    copy: true,
    reply: true,
    edit: false,
    delete: false,
    retry: true,
    retryDisabled: true,
    saveTemplate: false,
  });
  assert.deepEqual(messageActionsForVisibleMessage('runtime', false), {
    copy: true,
    reply: false,
    edit: false,
    delete: false,
    retry: false,
    retryDisabled: false,
    saveTemplate: false,
  });
});

test('lifecycle visibility QA replays Web-hidden Agent state events through the real timeline', () => {
  for (const type of [
    'agent_spawned',
    'agent_completed',
    'agent_stopped',
    'agent_message_sent',
    'agent_message_received',
  ]) {
    assert.match(lifecycleVisibilityQaSource, new RegExp(`'${type}'`));
  }
  assert.match(lifecycleVisibilityQaSource, /<AgentTimeline/);
  assert.match(lifecycleVisibilityQaSource, /Replay live lifecycle burst/);
  assert.match(lifecycleVisibilityQaSource, /data-testid="visible-message-order"/);
  assert.match(lifecycleVisibilityQaSource, /qa-user[\s\S]*qa-assistant/);
});

test('Desktop renders structured multi-call sources as one accessible aggregated card', () => {
  assert.match(chatSource, /<AggregatedSourcesCard items=\{node\.items\} \/>/);
  assert.match(aggregatedSourcesSource, /aggregateStructuredToolSources\(items\)/);
  assert.match(aggregatedSourcesSource, /data-testid="aggregated-sources-card"/);
  assert.match(aggregatedSourcesSource, /<details[\s\S]*<summary/);
  assert.match(aggregatedSourcesSource, /target="_blank"/);
  assert.match(aggregatedSourcesSource, /rel="noopener noreferrer"/);
  assert.match(chatStyles, /\.aggregated-sources-card/);
  for (const key of [
    'chat.aggregatedSources.title',
    'chat.aggregatedSources.metrics',
    'chat.aggregatedSources.other',
    'chat.aggregatedSources.open',
  ]) {
    assert.match(i18nSource, new RegExp(`'${key.replaceAll('.', '\\.')}'`));
  }
  assert.match(aggregatedSourcesQaSource, /<AgentTimeline/);
  assert.match(aggregatedSourcesQaSource, /data-testid="source-qa-authority"/);
});

test('local deletion is exact, idempotent, scoped, and preserves neighboring events', () => {
  const messages = [
    {
      id: 'user-1',
      conversationId: 'conversation-1',
      kind: 'user',
      content: 'First prompt',
    },
    {
      id: 'agent-1',
      conversationId: 'conversation-1',
      kind: 'agent',
      content: 'First answer',
    },
    {
      id: 'user-2',
      conversationId: 'conversation-1',
      kind: 'user',
      content: 'Delete this prompt',
    },
    {
      id: 'runtime-2',
      conversationId: 'conversation-1',
      kind: 'runtime',
      content: 'Tool activity',
    },
    {
      id: 'agent-2',
      conversationId: 'conversation-1',
      kind: 'agent',
      content: 'Keep this later answer',
    },
  ];
  const scopeKey = 'tenant-1:project-1:conversation-1';
  const target = {
    scopeKey,
    messageId: 'user-2',
  };

  assert.equal(canConfirmMessageDeletion(target, scopeKey, messages), true);
  assert.equal(
    canConfirmMessageDeletion(target, 'tenant-1:project-1:conversation-2', messages),
    false,
  );
  assert.equal(
    canConfirmMessageDeletion({ ...target, messageId: 'agent-2' }, scopeKey, messages),
    false,
  );
  assert.equal(messageDeletionFocusNeighborId(messages, 'user-2'), 'runtime-2');

  const first = hideMessageInScope(null, scopeKey, 'user-2');
  const duplicate = hideMessageInScope(first, scopeKey, 'user-2');
  assert.equal(duplicate, first);
  assert.deepEqual(
    filterHiddenMessages(messages, duplicate, scopeKey).map((message) => message.id),
    ['user-1', 'agent-1', 'runtime-2', 'agent-2'],
  );
  assert.deepEqual(hideMessageInScope(duplicate, 'other-scope', 'user-3'), {
    scopeKey: 'other-scope',
    hiddenMessageIds: ['user-3'],
  });
});

test('local deletion confirmation uses the Web-compatible 80 character excerpt', () => {
  assert.equal(messageDeletionExcerpt('  keep surrounding spaces  '), '  keep surrounding spaces  ');
  assert.equal(messageDeletionExcerpt('x'.repeat(81)), `${'x'.repeat(80)}…`);
  assert.equal(messageDeletionExcerpt(''), '');
});

test('reply drafts quote visible multiline text and cap the Web-compatible excerpt', () => {
  assert.equal(
    quoteMessageForComposer('  first line\nsecond line  '),
    '> first line\n> second line\n\n',
  );
  assert.equal(
    quoteMessageForComposer('x'.repeat(504)),
    `> ${'x'.repeat(500)}…\n\n`,
  );
  assert.equal(quoteMessageForComposer('   '), null);
});

test('retry resolves only the nearest user prompt in the current conversation', () => {
  const messages = [
    {
      id: 'foreign-user',
      conversationId: 'conversation-2',
      kind: 'user',
      content: 'Do not resend',
    },
    {
      id: 'user-1',
      conversationId: 'conversation-1',
      kind: 'user',
      content: 'First prompt',
    },
    {
      id: 'agent-1',
      conversationId: 'conversation-1',
      kind: 'agent',
      content: 'First answer',
    },
    {
      id: 'user-2',
      conversationId: 'conversation-1',
      kind: 'user',
      content: 'Nearest prompt',
    },
    {
      id: 'agent-2',
      conversationId: 'conversation-1',
      kind: 'agent',
      content: 'Retry this answer',
    },
  ];

  assert.equal(
    findRetryMessageContent(messages, 'agent-2', 'conversation-1'),
    'Nearest prompt',
  );
  assert.equal(findRetryMessageContent(messages, 'agent-2', 'conversation-2'), null);
  assert.equal(findRetryMessageContent(messages, 'user-2', 'conversation-1'), null);
  assert.equal(findRetryMessageContent(messages, 'missing', 'conversation-1'), null);
});

test('retry dispatch lock rejects duplicate or otherwise blocked sends', () => {
  assert.deepEqual(resolveRetryDispatch(null, 'agent-1', false), {
    accepted: true,
    lock: 'agent-1',
  });
  assert.deepEqual(resolveRetryDispatch('agent-1', 'agent-1', false), {
    accepted: false,
    lock: 'agent-1',
  });
  assert.deepEqual(resolveRetryDispatch(null, 'agent-1', true), {
    accepted: false,
    lock: null,
  });
});

test('Desktop wires message actions through the scoped composer and send authority', () => {
  assert.match(chatSource, /messageActionsForVisibleMessage\(kind, streaming\)/);
  assert.match(chatSource, /onReplyMessage=\{replyToTimelineMessage\}/);
  assert.match(chatSource, /onEditMessage=\{editTimelineMessage\}/);
  assert.match(chatSource, /onDeleteMessage=\{requestTimelineMessageDeletion\}/);
  assert.match(chatSource, /onRetryMessage=\{retryTimelineMessage\}/);
  assert.match(chatSource, /onSaveTemplateMessage=\{saveTimelineMessageAsTemplate\}/);
  assert.match(chatSource, /<MessageDeleteDialog/);
  assert.match(chatSource, /canConfirmMessageDeletion\(/);
  assert.match(chatSource, /hideMessageInScope\(/);
  assert.match(chatSource, /filterHiddenMessages\(/);
  assert.match(chatSource, /messageDeletionFocusNeighborId\(/);
  assert.match(chatSource, /<SavePromptTemplateDialog/);
  assert.match(chatSource, /target=\{saveTemplateRequest\}/);
  assert.match(chatSource, /findRetryMessageContent\(/);
  assert.match(chatSource, /resolveRetryDispatch\(/);
  assert.match(chatSource, /handleComposerSend\(retryContent, \[\]\)/);
  assert.match(
    chatSource,
    /draftRequest\.conversationId !== activeConversationId[\s\S]*setInput\(draftRequest\.content\)/,
  );
  assert.match(chatSource, /ref=\{composerInputRef\}/);
  assert.match(chatSource, /retryDisabled=\{disabled \|\| sending \|\| Boolean\(retryingMessageId\)\}/);
  assert.match(chatStyles, /\.session-message-actions button:disabled/);
  assert.match(chatStyles, /\.session-message-action-notice/);
  assert.match(chatStyles, /\.message-delete-dialog-note/);
  assert.match(
    chatSource,
    /data-timeline-anchor-id=\{item\.id\}\s+tabIndex=\{-1\}\s+>/,
  );
  assert.match(i18nSource, /deleteMessageRestorationNote/);
  assert.match(i18nSource, /messageRemoved/);
  assert.match(sessionConversationQaSource, /MessageDeleteDialog/);
  assert.doesNotMatch(chatSource, /api\.(delete|remove)Message/);
});

test('assistant execution summaries render structured input, output, and reasoning tokens', () => {
  assert.match(chatSource, /assistantCostTracking\(item\)/);
  assert.match(chatSource, /t\('chat\.input'\)/);
  assert.match(chatSource, /t\('chat\.output'\)/);
  assert.match(chatSource, /t\('session\.activityReasoning'\)/);
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
  assert.match(importancePolicy, /timelineHitlType\(item\)/);
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

test('Agent definition mutations stay visible without expanding management payloads', () => {
  const importancePolicy = chatSource.match(
    /function isImportantTimelineItem\(item: AgentTimelineItem\): boolean \{[\s\S]*?\n\}/,
  )?.[0];
  const expansionPolicy = chatSource.match(
    /function isTimelineItemInitiallyExpanded\(item: AgentTimelineItem\): boolean \{[\s\S]*?\n\}/,
  )?.[0];

  assert.ok(importancePolicy, 'timeline importance policy must remain explicit');
  assert.ok(expansionPolicy, 'timeline expansion policy must remain explicit');
  assert.match(importancePolicy, /agent_definition_/);
  assert.match(expansionPolicy, /agent_definition_/);
});

test('answered HITL requests remain visible as resolved narrative cards', () => {
  const importancePolicy = chatSource.match(
    /function isImportantTimelineItem\(item: AgentTimelineItem\): boolean \{[\s\S]*?\n\}/,
  )?.[0];

  assert.ok(importancePolicy, 'timeline importance policy must remain explicit');
  assert.match(importancePolicy, /if \(timelineHitlType\(item\)\) return true/);
  assert.doesNotMatch(importancePolicy, /timelineHitlType\(item\) && !item\.answered/);
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

test('task recovery titles bypass the generic task event fallback', () => {
  assert.match(chatSource, /!taskRecoveryEventTypes\.has\(item\.type\)/);
  for (const eventType of [
    'task_execution_session_updated',
    'task_execution_incident_opened',
    'task_recovery_action_started',
    'task_recovery_action_completed',
  ]) {
    assert.match(chatSource, new RegExp(`'${eventType}'`));
  }
  assert.match(chatSource, /chat\.taskExecutionSessionUpdated/);
  assert.match(chatSource, /chat\.taskExecutionIncidentOpened/);
  assert.match(chatSource, /chat\.taskRecoveryActionStarted/);
  assert.match(chatSource, /chat\.taskRecoveryActionCompleted/);
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
  assert.match(i18nSource, /'session\.statusActive': '活跃'/);
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
    'chat.replyMessage',
    'chat.editMessage',
    'chat.retryMessage',
    'chat.retryNoUserMessage',
    'chat.status.waitingForInput',
    'chat.status.blocked',
    'chat.retrying',
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
    'chat.agentDefinitionCreated',
    'chat.agentDefinitionUpdated',
    'chat.agentDefinitionDeleted',
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

test('reasoning and tool disclosures follow the Web transcript defaults', () => {
  assert.match(
    chatSource,
    /isTimelineItemInitiallyExpanded[\s\S]*item\.type === 'thought'[\s\S]*return true/,
  );
  assert.match(
    chatSource,
    /const lastToolGroupIndex = useMemo\([\s\S]*narrative\.length - 1[\s\S]*narrative\[index\]\.kind === 'tool_group'/,
  );
  assert.match(
    chatSource,
    /timelineGroupOpen\(\s*node\.items,\s*expandedGroupItems,\s*index === lastToolGroupIndex/,
  );
  assert.match(
    chatSource,
    /className="timeline-tool-group-summary"[\s\S]*aria-expanded=\{open\}/,
  );
  assert.match(
    chatSource,
    /\{isThought \? null : <span className="timeline-row-summary">\{summary\}<\/span>\}/,
  );
  assert.match(
    sessionConversationQaSource,
    /current\[toggleItem\.id\]\s*\?\?\s*isTimelineItemInitiallyExpanded\(toggleItem\)/,
  );
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
