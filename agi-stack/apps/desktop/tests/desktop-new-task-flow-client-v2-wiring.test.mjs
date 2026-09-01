import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const flow = source('src/features/task/NewTaskFlow.tsx');
const provider = source('src/features/task/desktopNewTaskFlowClientProviderV2.ts');
const standaloneQa = source('src/qa/NewTaskFlowQa.tsx');
const noProjectQa = source('src/qa/NoProjectEntryQa.tsx');

test('new-task flow resolves its transport authority from one V2 publication', () => {
  assert.match(app, /createDesktopNewTaskFlowClientProviderV2/u);
  assert.match(app, /desktopNewTaskFlowClientProviderV2\.publish\(\{ config \}\)/u);
  assert.match(app, /newTaskFlowClientV2:\s*desktopNewTaskFlowClientV2/u);
  assert.match(flow, /DesktopNewTaskFlowClientBindingV2/u);
  assert.match(flow, /newTaskFlowClientV2:\s*DesktopNewTaskFlowClientBindingV2/u);
  assert.doesNotMatch(flow, /DesktopApiClient/u);
  assert.doesNotMatch(flow, /new DesktopApiClient\(/u);
});

test('new-task flow Provider exposes only its eight owned transport methods', () => {
  for (const method of [
    'approvePlanAndStart',
    'createTaskSession',
    'getConversationMessages',
    'listAgentPlanTasks',
    'listWorkspaces',
    'sendMessage',
    'supportsAgentPlanWorkflow',
    'switchPlanMode',
  ]) {
    assert.match(provider, new RegExp(`${method}:`));
  }
  assert.match(provider, /bindOperation/u);
  assert.doesNotMatch(
    provider,
    /createAgentConversation:|runAgentMessage:|updateAgentConversationMode:/u,
  );
});

test('new-task flow binds every operation config without selecting an implementation class', () => {
  assert.match(flow, /newTaskFlowClientV2\.bindOperation\(config\)/u);
  assert.match(flow, /newTaskFlowClientV2\.bindOperation\(session\.config\)/u);
  assert.match(flow, /newTaskFlowClientV2\.bindOperation\(activeSession\.config\)/u);
  assert.match(flow, /\.supportsAgentPlanWorkflow\(\)/u);
  assert.match(flow, /\.createTaskSession\(/u);
  assert.match(flow, /\.listAgentPlanTasks\(/u);
  assert.match(flow, /\.approvePlanAndStart\(/u);
});

test('session plan approval receives one submitted-scope V2 transport method', () => {
  const callback = callbackSource(app, 'approveSessionPlan', 'handleSessionRunAction');

  assert.match(callback, /const requestConfig = configRef\.current/u);
  assert.match(
    callback,
    /const \{ approvePlanAndStart \} =\s*desktopNewTaskFlowClientV2\.bindOperation\(requestConfig\)/u,
  );
  assert.match(
    callback,
    /const client: Pick<DesktopNewTaskFlowClient, 'approvePlanAndStart'> =\s*Object\.freeze\(\{[\s\S]*?approvePlanAndStart,[\s\S]*?\}\)/u,
  );
  assert.match(callback, /client\.approvePlanAndStart\(\s*sessionPlanApprovalRequest\(/u);
  assert.doesNotMatch(callback, /api\.approvePlanAndStart/u);

  for (const policyAnchor of [
    /planAuthority\.kind !== 'desktop_plan_version'/u,
    /authoritativePlan\.id !== plan\.id/u,
    /authoritativePlan\.version !== plan\.version/u,
    /authoritativePlan\.status !== plan\.status/u,
    /canApproveSessionPlan\(authoritativePlan, capabilities\)/u,
    /sessionPlanApprovalIdentity/u,
    /requestId: globalThis\.crypto\.randomUUID\(\)/u,
    /projectId: conversation\.project_id/u,
    /conversationWithAuthoritativeRun/u,
    /requestConfig\.workspaceId\.trim\(\)/u,
    /loadConversationTimeline/u,
    /applyAuthoritativeRun/u,
    /invalidateSessionAuthority/u,
    /setSessionPlanApprovalPending\(false\)/u,
  ]) {
    assert.match(callback, policyAnchor);
  }
  assert.match(callback, /desktopNewTaskFlowClientV2,/u);
  assert.doesNotMatch(callback, /\[\s*api,/u);
});

test('standalone QA composition roots supply the same explicit V2 client binding', () => {
  assert.match(standaloneQa, /createDesktopNewTaskFlowClientProviderV2/u);
  assert.match(standaloneQa, /newTaskFlowClientV2=\{newTaskFlowClientV2\}/u);
  assert.match(noProjectQa, /createDesktopNewTaskFlowClientProviderV2/u);
  assert.match(noProjectQa, /newTaskFlowClientV2=\{desktopNewTaskFlowClientV2\}/u);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
