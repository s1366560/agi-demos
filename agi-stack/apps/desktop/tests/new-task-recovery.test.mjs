import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const taskFlowSource = readFileSync(
  new URL('../src/features/task/NewTaskFlow.tsx', import.meta.url),
  'utf8',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const i18nSource = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');
const generatePlanSource =
  taskFlowSource.match(
    /const generatePlan = async \(\) => \{[\s\S]*?\n  \};\n\n  const requestRevision/,
  )?.[0] ?? '';
const runTurnStart = appSource.indexOf('const runNewTaskAgentTurn');
const runTurnEnd = appSource.indexOf('const ensureAgentConversation', runTurnStart);
const runTurnSource =
  runTurnStart >= 0 && runTurnEnd > runTurnStart
    ? appSource.slice(runTurnStart, runTurnEnd)
    : '';

test('new task planning proves Plan support before creating any workspace or conversation', () => {
  const probeIndex = generatePlanSource.indexOf('await baseClient.supportsAgentPlanWorkflow()');
  const workspaceCreateIndex = generatePlanSource.indexOf('createWorkspaceForProject(');
  const conversationCreateIndex = generatePlanSource.indexOf('createAgentConversation(');

  assert.notEqual(probeIndex, -1);
  assert.ok(probeIndex < workspaceCreateIndex);
  assert.ok(probeIndex < conversationCreateIndex);
  assert.match(generatePlanSource, /throw new Error\(t\('task\.planRuntimeUnsupported'\)\)/);
});

test('new task planning persists early but activates only after binding and Agent dispatch', () => {
  const sessionReuseIndex = generatePlanSource.indexOf('let readySession =');
  const sessionCreationGuardIndex = generatePlanSource.indexOf('if (!readySession) {');
  const persistIndex = generatePlanSource.indexOf('setSession(readySession);');
  const catalogIndex = generatePlanSource.indexOf('onSessionPersisted(readySession);');
  const workspaceLinkIndex = generatePlanSource.indexOf('updateAgentConversationMode(');
  const planModeIndex = generatePlanSource.indexOf('switchPlanMode(');
  const agentTurnIndex = generatePlanSource.indexOf('runAgentTurn(');
  const activateIndex = generatePlanSource.lastIndexOf('onSessionReady(readySession);');

  assert.notEqual(sessionReuseIndex, -1);
  assert.ok(sessionReuseIndex < sessionCreationGuardIndex);
  assert.ok(sessionCreationGuardIndex < persistIndex);
  assert.ok(persistIndex < workspaceLinkIndex);
  assert.ok(catalogIndex < workspaceLinkIndex);
  assert.ok(persistIndex < planModeIndex);
  assert.ok(agentTurnIndex < activateIndex);
  assert.ok(workspaceLinkIndex < activateIndex);
  assert.equal((generatePlanSource.match(/createAgentConversation\(/g) ?? []).length, 1);
});

test('a fresh planning attempt clears local and shell errors', () => {
  const localClearIndex = generatePlanSource.indexOf('setFlowError(null);');
  const shellClearIndex = generatePlanSource.indexOf('onError(null);');
  const planModeIndex = generatePlanSource.indexOf('switchPlanMode(');

  assert.notEqual(localClearIndex, -1);
  assert.notEqual(shellClearIndex, -1);
  assert.ok(localClearIndex < planModeIndex);
  assert.ok(shellClearIndex < planModeIndex);
});

test('unsupported Plan runtime guidance is localized and actionable', () => {
  assert.equal((i18nSource.match(/'task\.planRuntimeUnsupported'/g) ?? []).length, 2);
  assert.equal((i18nSource.match(/'task\.openRuntimeSettings'/g) ?? []).length, 2);
  assert.match(
    i18nSource,
    /'task\.planRuntimeUnsupported':[\s\S]*Open Settings > Connection recovery[\s\S]*Agent Plan API/,
  );
  assert.match(
    i18nSource,
    /'task\.planRuntimeUnsupported':[\s\S]*设置 > 连接恢复[\s\S]*Agent Plan API/,
  );
  assert.match(taskFlowSource, /onOpenRuntimeSettings: \(\) => void/);
  assert.match(
    taskFlowSource,
    /runtimeRecoveryAvailable \? \([\s\S]*onClick=\{openRuntimeSettings\}[\s\S]*task\.openRuntimeSettings/,
  );
  assert.match(
    taskFlowSource,
    /const openRuntimeSettings = \(\) => \{[\s\S]*previousFocusRef\.current = null;[\s\S]*onOpenRuntimeSettings\(\)/,
  );
});

test('Plan capability network failures expose connection recovery before any write', () => {
  const capabilityProbe =
    generatePlanSource.match(
      /try \{[\s\S]*?supportsAgentPlanWorkflow\(\)[\s\S]*?\} catch \(error\) \{[\s\S]*?setRuntimeRecoveryAvailable\(true\);[\s\S]*?throw error;[\s\S]*?\}/,
    )?.[0] ?? '';
  const workspaceCreateIndex = generatePlanSource.indexOf('createWorkspaceForProject(');

  assert.notEqual(capabilityProbe, '');
  assert.ok(generatePlanSource.indexOf(capabilityProbe) < workspaceCreateIndex);
});

test('catalog persistence does not switch transport while activation selects the bound session', () => {
  const persistSource =
    appSource.match(
      /const persistNewTaskSession = \(session: NewTaskSession\) => \{[\s\S]*?\n  \};\n\n  const activateNewTaskSession/,
    )?.[0] ?? '';
  const activateSource =
    appSource.match(
      /const activateNewTaskSession = \(session: NewTaskSession\) => \{[\s\S]*?\n  \};\n\n  const runNewTaskAgentTurn/,
    )?.[0] ?? '';

  assert.match(persistSource, /conversationsByWorkspace:/);
  assert.doesNotMatch(persistSource, /commitRuntimeConfig/);
  assert.doesNotMatch(persistSource, /setAgentConversationSession/);
  assert.match(activateSource, /persistNewTaskSession\(session\)/);
  assert.match(activateSource, /commitRuntimeConfig\(sessionConfig\)/);
  assert.match(activateSource, /setAgentConversationSession\(/);
  assert.doesNotMatch(activateSource, /refreshRuntime\(/);
});

test('cloud turn acknowledgment is registered before the socket can reply', () => {
  const registerIndex = runTurnSource.indexOf(
    'pendingNewTaskAgentTurnsRef.current.set(input.messageId',
  );
  const sendIndex = runTurnSource.indexOf('socket.sendAgentMessage({');
  const cleanupIndex = runTurnSource.indexOf('clearPendingAgentTurn();');

  assert.notEqual(registerIndex, -1);
  assert.notEqual(sendIndex, -1);
  assert.ok(registerIndex < sendIndex);
  assert.ok(cleanupIndex > sendIndex);
});

test('timeout and disconnect preserve an unknown outcome instead of forcing a duplicate turn', () => {
  assert.match(runTurnSource, /resolve\('unknown_outcome'\)/);
  assert.doesNotMatch(runTurnSource, /agentTurnAckTimeout/);
  assert.match(taskFlowSource, /planningTurnAttempt\(/);
  assert.match(taskFlowSource, /deliveryOutcomeUnknown=\{deliveryOutcomeUnknown\}/);
  assert.equal((i18nSource.match(/'task\.agentTurnOutcomeUnknown'/g) ?? []).length, 2);
});

test('runtime preset selection requires both matching origin and transport mode', () => {
  const runtimePanelSource = readFileSync(
    new URL('../src/features/runtime/RuntimeConfigPanel.tsx', import.meta.url),
    'utf8',
  );
  assert.match(
    runtimePanelSource,
    /aria-pressed=\{[\s\S]*?config\.apiBaseUrl === preset\.apiBaseUrl && config\.mode === preset\.mode[\s\S]*?\}/,
  );
});

test('runtime identity changes clear bearer, launch, and native trusted authority', () => {
  const start = appSource.indexOf('const handleConfigChange');
  const end = appSource.indexOf('const useApiKeyManually', start);
  const source = start >= 0 && end > start ? appSource.slice(start, end) : '';

  assert.match(source, /runtimeTransportIdentityChanged\(/);
  assert.match(source, /transportIdentityChanged[\s\S]*apiKey: ''[\s\S]*localApiToken: ''/);
  assert.match(source, /setAuth\(emptyAuthState\)/);
  assert.match(source, /clearNativeTrustedSession\(\)/);
});

test('cloud task-list sessions reopen the exact conversation through guarded legacy review', () => {
  const start = appSource.indexOf('const resumeSessionTaskListReview');
  const end = appSource.indexOf('const persistNewTaskSession', start);
  const source = start >= 0 && end > start ? appSource.slice(start, end) : '';

  assert.match(source, /planAuthority\.kind !== 'agent_task_list'/);
  assert.match(source, /sessionTaskListPlanRecovery\?\.canResume/);
  assert.match(source, /const tasks = sessionTaskListPlanRecovery\.tasks/);
  assert.match(appSource, /normalizeSessionTaskListPlan\(/);
  assert.match(source, /openNewTask\(workspaceId, resumeDraft\)/);
  assert.match(appSource, /<SessionTaskListReview[\s\S]*onResumeReview=\{onResumeTaskListReview\}/);
});

test('legacy approval persists the exact dispatch identity before entering Build mode', () => {
  const start = taskFlowSource.indexOf('const approveLegacyPlan');
  const end = taskFlowSource.indexOf('const approveVersionedPlan', start);
  const source = start >= 0 && end > start ? taskFlowSource.slice(start, end) : '';
  const persistIndex = source.indexOf('writeLegacyPlanApprovalRecovery(');
  const buildIndex = source.indexOf("switchPlanMode(activeSession.conversation.id, 'build')");
  const dispatchIndex = source.indexOf('runAgentTurn(');

  assert.notEqual(persistIndex, -1);
  assert.ok(persistIndex < buildIndex);
  assert.ok(buildIndex < dispatchIndex);
  assert.match(source, /legacyBuildRecoveryRef\.current/);
  assert.match(source, /outcome === 'unknown_outcome'[\s\S]*return false/);
  assert.doesNotMatch(
    source.match(/if \(outcome === 'unknown_outcome'\) \{[\s\S]*?\n      \}/)?.[0] ?? '',
    /clearLegacyPlanApprovalRecovery/,
  );
});

test('Build-without-attempt recovery is gated by the durable exact task-list identity', () => {
  assert.match(appSource, /canResumeLegacyPlanApproval\(/);
  assert.match(appSource, /executionAuthority\.currentAttempt !== null/);
  assert.match(appSource, /readLegacyPlanApprovalRecovery\(/);
  assert.match(appSource, /clearLegacyPlanApprovalRecovery\(/);
});

test('conversation plan canvas never substitutes the workspace envelope plan', () => {
  const start = appSource.indexOf('function WorkspaceReviewPanel(');
  const end = appSource.indexOf('\nfunction ', start + 1);
  const source = start >= 0 ? appSource.slice(start, end > start ? end : undefined) : '';

  assert.notEqual(source, '');
  assert.doesNotMatch(source, /dataset\.plan/);
  assert.doesNotMatch(source, /JSON\.stringify\(dataset\.plan/);
  assert.match(source, /currentPlan \|\| taskListPlanTasks\.length > 0/);
});
