import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const composerSource = readFileSync(
  new URL('../src/features/task/NewThreadComposer.tsx', import.meta.url),
  'utf8',
);
const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8',
);
const runtimeProviderHookSource = readFileSync(
  new URL('../src/features/settings/useWorkspaceRuntimeProvider.ts', import.meta.url),
  'utf8',
);
const workspaceAgentPolicyHookSource = readFileSync(
  new URL('../src/features/settings/useWorkspaceAgentPolicy.ts', import.meta.url),
  'utf8',
);
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');

const createThreadStart = appSource.indexOf('const createComposerThread');
const createThreadEnd = appSource.indexOf('const ensureAgentConversation', createThreadStart);
const createThreadSource =
  createThreadStart >= 0 && createThreadEnd > createThreadStart
    ? appSource.slice(createThreadStart, createThreadEnd)
    : '';
const unboundCreateStart = createThreadSource.indexOf('if (!workspaceId)');
const unboundCreateEnd = createThreadSource.indexOf('const policy =', unboundCreateStart);
const unboundCreateSource =
  unboundCreateStart >= 0 && unboundCreateEnd > unboundCreateStart
    ? createThreadSource.slice(unboundCreateStart, unboundCreateEnd)
    : '';
const sendMessageStart = appSource.indexOf('const sendMessageContent');
const sendMessageEnd = appSource.indexOf('const sendMessageContentRef', sendMessageStart);
const sendMessageSource =
  sendMessageStart >= 0 && sendMessageEnd > sendMessageStart
    ? appSource.slice(sendMessageStart, sendMessageEnd)
    : '';
const chatDisabledStart = appSource.indexOf('const chatDisabledReason');
const chatDisabledEnd = appSource.indexOf('\n\n  useEffect(', chatDisabledStart);
const chatDisabledSource =
  chatDisabledStart >= 0 && chatDisabledEnd > chatDisabledStart
    ? appSource.slice(chatDisabledStart, chatDisabledEnd)
    : '';
const unboundLoadStart = appSource.indexOf('const loadWorkspaceConversations');
const unboundLoadEnd = appSource.indexOf('\n\n  const login', unboundLoadStart);
const unboundLoadSource =
  unboundLoadStart >= 0 && unboundLoadEnd > unboundLoadStart
    ? appSource.slice(unboundLoadStart, unboundLoadEnd)
    : '';
const refreshRuntimeStart = appSource.indexOf('const refreshRuntime');
const refreshRuntimeEnd = appSource.indexOf('\n\n  const loadWorkspaceConversations', refreshRuntimeStart);
const refreshRuntimeSource =
  refreshRuntimeStart >= 0 && refreshRuntimeEnd > refreshRuntimeStart
    ? appSource.slice(refreshRuntimeStart, refreshRuntimeEnd)
    : '';
const renderNewThreadStart = appSource.indexOf('const renderNewThreadComposer');
const renderNewThreadEnd = appSource.indexOf('\n\n  const renderAuxiliaryView', renderNewThreadStart);
const renderNewThreadSource =
  renderNewThreadStart >= 0 && renderNewThreadEnd > renderNewThreadStart
    ? appSource.slice(renderNewThreadStart, renderNewThreadEnd)
    : '';
const canManageWorkspacePolicyStart = appSource.indexOf('const canManageWorkspacePolicy');
const canManageWorkspacePolicyEnd = appSource.indexOf(
  '\n\n  const syncLocalRuntimeConfig',
  canManageWorkspacePolicyStart,
);
const canManageWorkspacePolicySource =
  canManageWorkspacePolicyStart >= 0 &&
  canManageWorkspacePolicyEnd > canManageWorkspacePolicyStart
    ? appSource.slice(canManageWorkspacePolicyStart, canManageWorkspacePolicyEnd)
    : '';

test('new-thread composer exposes an explicit workspace or no-workspace choice', () => {
  assert.match(composerSource, /workspaceId: string;/);
  assert.match(composerSource, /workspaces: WorkspaceSummary\[\];/);
  assert.match(composerSource, /onWorkspaceChange: \(workspaceId: string\) => void;/);
  assert.match(composerSource, /const workspacePickerOptions =/);
  assert.match(composerSource, /value: ''[\s\S]*task\.noWorkspace/);
  assert.match(composerSource, /label=\{t\('task\.workspace'\)\}/);
  assert.equal((i18nSource.match(/'task\.noWorkspace'/g) ?? []).length, 2);
  assert.equal((i18nSource.match(/'task\.noWorkspaceDescription'/g) ?? []).length, 2);
});

test('new-thread model and local overrides are scoped by workspace without effects', () => {
  assert.doesNotMatch(composerSource, /useEffect/);
  assert.match(composerSource, /modelSelection\.workspaceId === workspaceId/);
  assert.match(composerSource, /reasoningSelection\.workspaceId === workspaceId/);
  assert.match(composerSource, /permissionSelection\.workspaceId === workspaceId/);
  assert.match(composerSource, /setContextItems\(\[\]\)[\s\S]*onWorkspaceChange/);
  assert.match(composerSource, /model: WorkspaceRuntimeModelOption \| null;/);
  assert.match(
    composerSource,
    /!workspaceId \|\| selectedModel[\s\S]*onCreate\(\{[\s\S]*workspaceId,[\s\S]*model: selectedModel/,
  );
  assert.match(composerSource, /!creating &&[\s\S]{0,80}!loadingPolicy/);
  assert.match(
    workspaceAgentPolicyHookSource,
    /setState\(\{[\s\S]*scopeKey,[\s\S]*policy: null,[\s\S]*providers: \[\],[\s\S]*members: \[\],[\s\S]*loading: true/,
  );
});

test('unbound new threads create an Agent conversation and preserve null workspace authority', () => {
  assert.notEqual(createThreadSource, '');
  assert.notEqual(unboundCreateSource, '');
  assert.match(unboundCreateSource, /createAgentConversation\(/);
  assert.match(unboundCreateSource, /actorId,[\s\S]*input\.mode/);
  assert.match(unboundCreateSource, /conversation\.workspace_id !== null/);
  assert.match(unboundCreateSource, /activateUnboundNewThread\(/);
  assert.match(unboundCreateSource, /runNewTaskAgentTurn\(/);
  assert.doesNotMatch(unboundCreateSource, /createTaskSession\(/);
  assert.match(appSource, /conversationsByWorkspace:[\s\S]*\[UNBOUND_CONVERSATIONS_KEY\]/);
});

test('unbound first-turn delivery failure remains visible after activating chat', () => {
  assert.match(unboundCreateSource, /upsertAgentTaskSignal\(\{[\s\S]*status: 'queued'/);
  assert.match(unboundCreateSource, /const outcome = await runNewTaskAgentTurn\(/);
  assert.doesNotMatch(
    appSource,
    /deferUntilNextConnection:\s*!isSameDesktopRequestScope\(config, input\.config\)/,
  );
  assert.match(
    appSource,
    /runNewTaskAgentTurn\(\s*\{[\s\S]*?conversationId: conversation\.id,[\s\S]*?\},\s*\{\s*deferUntilNextConnection:\s*!isSameDesktopRequestScope\(\s*requestConfig,\s*threadConfig/,
  );
  assert.match(
    unboundCreateSource,
    /catch \(caught\)[\s\S]*setNewThreadError\(detail\)[\s\S]*setError\(detail\)/,
  );
  assert.match(
    unboundCreateSource,
    /activatedConversation[\s\S]*upsertAgentTaskSignal\(\{[\s\S]*status: 'failed'/,
  );
});

test('workspace policy authority loads and checks the selected target workspace roster', () => {
  assert.match(workspaceAgentPolicyHookSource, /members: WorkspaceMemberSummary\[\]/);
  assert.match(workspaceAgentPolicyHookSource, /client\.listWorkspaceMembers\(controller\.signal\)/);
  assert.notEqual(canManageWorkspacePolicySource, '');
  assert.match(canManageWorkspacePolicySource, /workspaceAgentPolicy\.members\.find\(/);
  assert.doesNotMatch(canManageWorkspacePolicySource, /dataset\.workspaceMembers/);
});

test('bound new threads keep the atomic task-session behavior', () => {
  assert.match(createThreadSource, /const workspaceId = input\.workspaceId\.trim\(\)/);
  assert.match(createThreadSource, /buildRuntimeTaskSessionRequest\([\s\S]*workspaceId/);
  assert.match(createThreadSource, /createTaskSession\(request\)/);
  assert.match(createThreadSource, /config: \{ \.\.\.threadConfig, workspaceId: result\.workspace\.id \}/);
  assert.match(
    createThreadSource,
    /workspaceAgentPolicy\.loading[\s\S]*workspaceAgentPolicy\.scopeKey !== expectedPolicyScopeKey/,
  );
});

test('unbound conversation messages bypass workspace message persistence', () => {
  const unboundIndex = sendMessageSource.indexOf('if (!config.workspaceId.trim())');
  const workspaceMessageIndex = sendMessageSource.indexOf('api.sendMessage(');
  assert.notEqual(unboundIndex, -1);
  assert.notEqual(workspaceMessageIndex, -1);
  assert.ok(unboundIndex < workspaceMessageIndex);
  const unboundBranch = sendMessageSource.slice(unboundIndex, workspaceMessageIndex);
  assert.match(unboundBranch, /ensureAgentConversation\(content\)/);
  assert.match(unboundBranch, /dispatchAgentConversationMessage\(/);
  assert.doesNotMatch(unboundBranch, /api\.sendMessage\(/);
  assert.doesNotMatch(chatDisabledSource, /!config\.workspaceId/);
});

test('new-thread recent conversations and open actions follow the selected creation scope', () => {
  assert.match(
    appSource,
    /newThreadWorkspaceId \|\| UNBOUND_CONVERSATIONS_KEY/,
  );
  assert.match(
    appSource,
    /selectConversation\(config\.projectId, newThreadWorkspaceId, conversation, 'chat'\)/,
  );
  assert.match(appSource, /workspaceId=\{newThreadWorkspaceId\}/);
  assert.match(appSource, /onWorkspaceChange=\{changeNewThreadWorkspace\}/);
  assert.match(
    appSource,
    /if \(newThreadWorkspaceId\) return newThreadApi;[\s\S]*unboundComposerCatalogClient\(newThreadApi\)/,
  );
  assert.match(appSource, /api=\{newThreadComposerApi\}/);
});

test('desktop unbound group uses the authoritative server filter', () => {
  assert.match(unboundLoadSource, /unboundOnly: isUnboundGroup/);
  assert.doesNotMatch(unboundLoadSource, /filterUnboundConversations/);
});

test('composer catalogs remount when new-thread or chat scope changes', () => {
  assert.match(
    renderNewThreadSource,
    /const newThreadComposerScopeKey = \[[\s\S]*config\.mode,[\s\S]*config\.apiBaseUrl,[\s\S]*config\.tenantId,[\s\S]*config\.projectId,[\s\S]*auth\.user\?\.user_id/,
  );
  assert.match(renderNewThreadSource, /<NewThreadComposer[\s\S]{0,100}key=\{newThreadComposerScopeKey\}/);
  assert.match(
    composerSource,
    /<ComposerPlusMenu[\s\S]{0,160}key=\{workspaceId \|\| 'unbound'\}/,
  );
  assert.match(
    chatPanelSource,
    /<ChatComposer[\s\S]{0,240}key=\{composerResetKey\}/,
  );
});

test('runtime refresh preserves an active explicit unbound session without changing initial defaults', () => {
  assert.match(refreshRuntimeSource, /resolveRuntimeWorkspaceId\(/);
  assert.match(refreshRuntimeSource, /agentConversationSessionRef\.current/);
  assert.match(refreshRuntimeSource, /projectWorkspaces/);
});

test('cloud unbound creation fails preflight before creating a conversation', () => {
  const preflightIndex = unboundCreateSource.indexOf("connection !== 'ready'");
  const createIndex = unboundCreateSource.indexOf('createAgentConversation(');
  assert.ok(preflightIndex >= 0);
  assert.ok(createIndex > preflightIndex);
  assert.match(
    renderNewThreadSource,
    /!newThreadWorkspaceId[\s\S]{0,160}config\.mode === 'cloud'[\s\S]{0,160}connection !== 'ready'/,
  );
});

test('unbound chat uses project model options and a scope-aware catalog client', () => {
  assert.match(runtimeProviderHookSource, /projectRuntimeModelOptions/);
  assert.doesNotMatch(
    runtimeProviderHookSource,
    /!config\.projectId\.trim\(\) \|\|\s*!config\.workspaceId\.trim\(\)/,
  );
  assert.match(
    runtimeProviderHookSource,
    /config\.workspaceId\.trim\(\)[\s\S]*getLlmProviderRoutingPolicy[\s\S]*listLlmProviders/,
  );
  assert.match(appSource, /const chatComposerApi = useMemo/);
  assert.match(appSource, /api=\{chatComposerApi\}/);
  assert.match(appSource, /unboundComposerCatalogClient\(/);
  assert.match(appSource, /updateAgentConversationConfig\([\s\S]*llm_model_override/);
});

test('unbound creation sends the selected model atomically with conversation creation', () => {
  assert.match(
    unboundCreateSource,
    /createAgentConversation\([\s\S]*llm_model_override: input\.model\.modelId/,
  );
  assert.doesNotMatch(unboundCreateSource, /updateAgentConversationConfig\(/);
});

test('new-thread creation fails closed when its tenant or project scope becomes stale', () => {
  assert.match(createThreadSource, /const requestConfig = configRef\.current/);
  assert.match(createThreadSource, /const expectedContextRevision = contextRevisionRef\.current/);
  assert.match(createThreadSource, /const expectedScopeEpoch = configScopeEpochRef\.current/);
  assert.match(
    createThreadSource,
    /const requestScopeIsCurrent = \(\) =>[\s\S]*isCurrentContextRevision\([\s\S]*expectedScopeEpoch === configScopeEpochRef\.current[\s\S]*isSameDesktopRequestScope\(requestConfig, configRef\.current\)/,
  );
  assert.match(
    unboundCreateSource,
    /await client\.createAgentConversation\([\s\S]*if \(!requestScopeIsCurrent\(\)\) return;[\s\S]*activateUnboundNewThread/,
  );
  assert.match(
    createThreadSource,
    /await client\.createTaskSession\(request\);[\s\S]*if \(!requestScopeIsCurrent\(\)\) return;[\s\S]*activateNewTaskSession/,
  );
  assert.match(
    createThreadSource,
    /const activatedScopeIsCurrent = \(\) =>[\s\S]*activatedScopeEpoch === configScopeEpochRef\.current[\s\S]*isSameDesktopRequestScope\(activatedConfig, configRef\.current\)/,
  );
  assert.match(createThreadSource, /catch \(caught\) \{\s*if \(!creationScopeIsCurrent\(\)\) return;/);
});
