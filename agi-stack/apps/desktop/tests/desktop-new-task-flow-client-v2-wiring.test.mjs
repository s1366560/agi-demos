import { desktopProductionRuntimeSource } from './support/desktop-production-runtime-source.mjs';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { test } from 'node:test';

function source(relativePath) {
  const url = new URL(`../${relativePath}`, import.meta.url);
  return existsSync(url) ? readFileSync(url, 'utf8') : '';
}

const app = source('src/App.tsx');
const flow = source('src/features/task/NewTaskFlow.tsx');
const authority = source('src/plugins/desktopNewTaskFlowAuthorityModuleV2.ts');
const generation = desktopProductionRuntimeSource();
const standaloneQa = source('src/qa/NewTaskFlowQa.tsx');
const noProjectQa = source('src/qa/NoProjectEntryQa.tsx');
const qaAuthority = source('src/qa/desktopNewTaskFlowAuthorityQaV2.ts');
const testTypeScriptConfig = source('tsconfig.test.json');
const legacyProviderUrl = new URL(
  '../src/features/task/desktopNewTaskFlowClientProviderV2.ts',
  import.meta.url,
);

test('production Loader registers the explicit new-task-flow V2 authority', () => {
  assert.match(generation, /desktopNewTaskFlowAuthorityDefinitionV2/u);
  assert.match(authority, /builtin:\/\/memstack\/desktop\/new-task-flow-authority/u);
  assert.match(authority, /service:desktop-renderer\.new-task-flow-authority/u);
  assert.match(authority, /applyDesktopNewTaskFlowAuthorityV2/u);
  assert.match(authority, /context\.provide\(DESKTOP_NEW_TASK_FLOW_AUTHORITY_SERVICE_V2/u);
  assert.doesNotMatch(authority, /optional|fallback|legacy-client/iu);
});

test('App owns one stable generation-backed facade and no private publication', () => {
  assert.match(app, /createDesktopNewTaskFlowOperationsV2/u);
  assert.match(
    app,
    /createDesktopNewTaskFlowOperationsV2\(\s*\(\) =>\s*desktopPluginMarketplaceGenerationActionsRefV2\.current,?\s*\)/u,
  );
  assert.match(app, /newTaskFlowClientV2:\s*desktopNewTaskFlowClientV2/u);
  assert.doesNotMatch(app, /createDesktopNewTaskFlowClientProviderV2/u);
  assert.doesNotMatch(app, /desktopNewTaskFlowClientProviderV2\.publish/u);
});

test('new-task flow consumes only the declared V2 operations facade', () => {
  assert.match(flow, /DesktopNewTaskFlowOperationsV2/u);
  assert.match(flow, /newTaskFlowClientV2:\s*DesktopNewTaskFlowOperationsV2/u);
  assert.match(flow, /newTaskFlowClientV2\.bindOperation\(config\)/u);
  assert.match(flow, /newTaskFlowClientV2\.bindOperation\(session\.config\)/u);
  assert.match(flow, /newTaskFlowClientV2\.bindOperation\(activeSession\.config\)/u);
  assert.match(flow, /\.supportsAgentPlanWorkflow\(\)/u);
  assert.match(flow, /\.createTaskSession\(/u);
  assert.match(flow, /\.listAgentPlanTasks\(/u);
  assert.match(flow, /\.approvePlanAndStart\(/u);
  assert.doesNotMatch(flow, /DesktopApiClient|new DesktopApiClient\(/u);
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
    /const client: Pick<DesktopNewTaskFlowClientV2, 'approvePlanAndStart'> =\s*Object\.freeze\(\{[\s\S]*?approvePlanAndStart,[\s\S]*?\}\)/u,
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

test('standalone QA roots activate the same module behind a QA-only service admission', () => {
  assert.match(standaloneQa, /createDesktopNewTaskFlowQaOperationsV2/u);
  assert.match(standaloneQa, /newTaskFlowClientV2=\{newTaskFlowClientV2\}/u);
  assert.match(noProjectQa, /useMemo\(createDesktopNewTaskFlowQaOperationsV2, \[\]\)/u);
  assert.match(noProjectQa, /newTaskFlowClientV2=\{desktopNewTaskFlowClientV2\}/u);
  assert.match(qaAuthority, /applyDesktopNewTaskFlowAuthorityV2/u);
  assert.match(qaAuthority, /acquireServiceOperationLease/u);
  assert.doesNotMatch(qaAuthority, /new DesktopApiClient\(/u);
});

test('the private provider implementation and compile inventory entry are retired', () => {
  assert.equal(existsSync(legacyProviderUrl), false);
  assert.doesNotMatch(testTypeScriptConfig, /desktopNewTaskFlowClientProviderV2/u);
});

function callbackSource(sourceText, name, nextName) {
  const start = sourceText.indexOf(`const ${name} = useCallback(`);
  assert.notEqual(start, -1);
  const end = sourceText.indexOf(`\n  const ${nextName}`, start + 1);
  assert.notEqual(end, -1);
  return sourceText.slice(start, end);
}
