import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const mainSource = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
const globalStyles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const sessionStyles = readFileSync(
  new URL('../src/features/session/SessionWorkspace.css', import.meta.url),
  'utf8'
);
const sessionWorkspaceSource = readFileSync(
  new URL('../src/features/session/SessionWorkspace.tsx', import.meta.url),
  'utf8'
);
const sessionChangesSource = readFileSync(
  new URL('../src/features/session/SessionChangesCanvas.tsx', import.meta.url),
  'utf8'
);
const sessionTerminalSource = readFileSync(
  new URL('../src/features/session/SessionTerminalCanvas.tsx', import.meta.url),
  'utf8'
);
const sessionEvidenceSource = readFileSync(
  new URL('../src/features/session/SessionEvidenceCanvas.tsx', import.meta.url),
  'utf8'
);
const runtimeConfigSource = readFileSync(
  new URL('../src/features/runtime/RuntimeConfigPanel.tsx', import.meta.url),
  'utf8'
);
const sidebarSource = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.tsx', import.meta.url),
  'utf8'
);
const sidebarStyles = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.css', import.meta.url),
  'utf8'
);
const workspaceDockSource = readFileSync(
  new URL('../src/features/workspace/WorkspaceDock.tsx', import.meta.url),
  'utf8'
);
const workspaceDockStyles = readFileSync(
  new URL('../src/features/workspace/WorkspaceDock.css', import.meta.url),
  'utf8'
);
const chatPanelSource = readFileSync(
  new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
  'utf8'
);

test('desktop shell mounts only the prototype sidebar and page-owned headers', () => {
  assert.doesNotMatch(appSource, /className="titlebar"/);
  assert.doesNotMatch(appSource, /className="copilot-sidebar"/);
  assert.equal((appSource.match(/<DesktopSidebar\b/g) ?? []).length, 1);
});

test('hierarchy pages remove the legacy pane inset around prototype-owned canvases', () => {
  assert.match(
    sidebarStyles,
    /\.app-shell\.hierarchy-shell \.pane-stage\.single-stage\s*\{[\s\S]*?padding:\s*0\s*;/,
  );
});

test('authenticated identities without a project remain inside the desktop shell', () => {
  const renderWorkbench =
    appSource.match(
      /const renderWorkbench = [\s\S]*?\n  \};\n\n  if \(!identityAuthenticated\)/
    )?.[0] ?? '';

  assert.match(appSource, /const identityAuthenticated = isIdentityAuthenticated\(auth\)/);
  assert.match(appSource, /const showRuntimeConfig = isWorkspaceReady\(auth, config\)/);
  assert.match(appSource, /useAgentSocket\([\s\S]*showRuntimeConfig && connection === 'ready'/);
  assert.match(
    appSource,
    /setSettingsInitialSection\('workspace'\);[\s\S]*setSettingsWindowOpen\(true\);/,
  );
  assert.match(appSource, /if \(!identityAuthenticated\) \{[\s\S]*<LoginScreen/);
  assert.match(renderWorkbench, /if \(!showRuntimeConfig\) return renderWorkspaceOverview\(\)/);
  assert.doesNotMatch(renderWorkbench, /<SignedOutPanel/);
});

test('login is the only signed-out surface retained by the desktop shell', () => {
  assert.doesNotMatch(appSource, /function SignedOutPanel\b/);
  assert.doesNotMatch(appSource, /function SignedOutSessionTree\b/);
  assert.doesNotMatch(appSource, /function WorkflowStrip\b/);
  assert.doesNotMatch(appSource, /signedOutTargetForSection|signedOutWorkflowContext/);
  assert.doesNotMatch(appSource, /mobileSectionMenuOpen|mobileTitlebarItems/);
  assert.doesNotMatch(appSource, /signed-out-mode/);
  assert.doesNotMatch(mainSource, /\.signed-out-workflows/);
});

test('workspace hydration and refresh fail closed across tenant boundaries', () => {
  assert.match(
    appSource,
    /const scopedProjects = projects\.filter\(\s*\(project\) => project\.tenant_id === tenantId\s*\)/,
  );
  assert.match(
    appSource,
    /if \(!workspaceContextMatchesSelection\(nextContext, tenantId, projectId\)\) \{[\s\S]*?throw new Error/,
  );
  assert.match(
    appSource,
    /const resolvedProject = findWorkspaceProject\([\s\S]*?if \(!resolvedProject\) \{[\s\S]*?throw new Error/,
  );
  assert.match(appSource, /if \(auth\.status === 'signed_in'\) return auth\.projects/);
  assert.doesNotMatch(appSource, /availableProjects\[0\]/);
});

test('an authoritative context switch closes settings even when workspace hydration degrades', () => {
  const applySettingsContext =
    appSource.match(
      /const applySettingsContext = async \(tenantId: string, projectId: string\) => \{[\s\S]*?\n  \};/
    )?.[0] ?? '';

  assert.match(applySettingsContext, /await refreshRuntime\(nextConfig, \[selectedProject\]\)/);
  assert.doesNotMatch(applySettingsContext, /contextSwitchLoadFailed/);
  assert.match(appSource, /connection === 'error'[\s\S]*runtime\.retryWorkspace/);
  assert.match(
    appSource,
    /workbenchRef\.current\?\.focus\(\);[\s\S]*void refreshRuntime\(\)/
  );
});

test('runtime refresh hydrates conversations only for selected or expanded workspaces', () => {
  const refreshRuntime =
    appSource.match(
      /const refreshRuntime = useCallback\([\s\S]*?\n  const refreshMyWork = useCallback/
    )?.[0] ?? '';

  assert.match(refreshRuntime, /workspaceConversationLoadTargets\(/);
  assert.doesNotMatch(refreshRuntime, /workspaces\.map\(async \(workspace\) => \{/);
  assert.match(appSource, /loadWorkspaceConversations/);
  assert.match(appSource, /if \(!wasExpanded\) void loadWorkspaceConversations\(workspaceId\)/);
});

test('runtime refresh preserves workspace expansion changes made while hydration is pending', () => {
  const refreshRuntime =
    appSource.match(
      /const refreshRuntime = useCallback\([\s\S]*?\n  const refreshMyWork = useCallback/
    )?.[0] ?? '';

  assert.match(
    refreshRuntime,
    /const committedExpandedWorkspaceIds = reconcileExpandedWorkspaceIds\(\s*expandedWorkspaceIdsRef\.current,/
  );
  assert.match(
    refreshRuntime,
    /expandedWorkspaceIdsRef\.current = committedExpandedWorkspaceIds;[\s\S]*setExpandedWorkspaceIds\(committedExpandedWorkspaceIds\)/
  );
  assert.doesNotMatch(refreshRuntime, /expandedWorkspaceIdsRef\.current = nextExpandedWorkspaceIds/);
});

test('workspace tree loading and error states announce changes and expose explicit retries', () => {
  assert.match(workspaceDockSource, /role="status"/);
  assert.match(workspaceDockSource, /aria-live="polite"/);
  assert.match(workspaceDockSource, /onRetryProject/);
  assert.match(workspaceDockSource, /onRetryWorkspace/);
  assert.match(workspaceDockSource, /actionLabel=\{t\('workspaceTree\.retry'\)\}/);
  assert.match(sidebarSource, /onRetryProject=\{onRetryProject\}/);
  assert.match(sidebarSource, /onRetryWorkspace=\{onRetryWorkspace\}/);
  assert.match(appSource, /onRetryProject=\{\(\) => void refreshRuntime\(\)\}/);
  assert.match(appSource, /onRetryWorkspace=\{\(workspaceId\) => void loadWorkspaceConversations\(workspaceId\)\}/);
  assert.match(workspaceDockStyles, /\.workspace-tree-state > button/);
  assert.match(
    workspaceDockSource,
    /navigationRef\.current\?\.focus\(\);[\s\S]*onRetryProject\(\)/
  );
  assert.match(
    workspaceDockSource,
    /workspaceToggleRefs\.current\.get\(workspace\.id\)\?\.focus\(\);[\s\S]*onRetryWorkspace\(workspace\.id\)/
  );
});

test('workspace hierarchy uses native navigation controls instead of an incomplete ARIA tree', () => {
  assert.match(workspaceDockSource, /<nav[\s\S]*aria-label=\{t\('workspaceTree\.navigation'\)\}/);
  assert.match(workspaceDockSource, /className="workspace-tree-toggle"[\s\S]*aria-expanded=\{workspaceExpanded\}/);
  assert.doesNotMatch(workspaceDockSource, /role="(?:tree|treeitem|group)"/);
});

test('workspace tree keeps status out of subtitles while preserving an accessible status dot', () => {
  assert.match(workspaceDockSource, /<small>\{sessionSummary\}<\/small>/);
  assert.doesNotMatch(
    workspaceDockSource,
    /\{sessionSummary\}\s*·\s*\{rootStatusLabel\}/
  );
  assert.match(
    workspaceDockSource,
    /data-status=\{rootStatus\.tone\}[\s\S]*role="img"[\s\S]*aria-label=\{rootStatusLabel\}[\s\S]*title=\{rootStatusLabel\}/
  );
  assert.match(
    workspaceDockSource,
    /conversationTreeMetadataSummary\(conversation\) \?\? statusLabel/
  );
});

test('workspace conversation loads remain project scoped while the selected workspace changes', () => {
  const loader =
    appSource.match(
      /const loadWorkspaceConversations = useCallback\([\s\S]*?\n  const refreshMyWork = useCallback/
    )?.[0] ?? '';

  assert.match(loader, /isSameDesktopProjectRequestScope\(requestConfig, configRef\.current\)/);
  assert.match(loader, /beginWorkspaceConversationRequest\(/);
  assert.match(loader, /isCurrentWorkspaceConversationRequest\(/);
  assert.doesNotMatch(loader, /expectedScopeEpoch/);
  assert.doesNotMatch(loader, /isSameDesktopRequestScope\(requestConfig, configRef\.current\)/);
  assert.match(loader, /updateDataset\(\(current\) => \{[\s\S]*return nextDataset/);
  assert.doesNotMatch(loader, /setDataset\(loadingDataset\)/);
  assert.match(
    appSource,
    /conversationRequestGenerations[\s\S]*beginWorkspaceConversationRequest\([\s\S]*isCurrentWorkspaceConversationRequest\(/
  );
  assert.match(appSource, /activeRuntimeConversationRequestsRef/);
  assert.match(appSource, /supersedeWorkspaceConversationRequests\(/);
  assert.match(loader, /mergeConversationListWithCurrentRunAuthority\(/);
  assert.match(
    appSource,
    /currentConversationResults[\s\S]*mergeConversationListWithCurrentRunAuthority\(/
  );
});

test('workspace roster hydration isolates authority failures from the runtime connection', () => {
  const refreshRuntime =
    appSource.match(
      /const refreshRuntime = useCallback\([\s\S]*?\n  const refreshMyWork = useCallback/,
    )?.[0] ?? '';

  assert.match(refreshRuntime, /loadingWorkspaceAuthority\(\)/);
  assert.match(
    refreshRuntime,
    /resolveWorkspaceAuthority\(scopedClient\.listWorkspaceMembers\(\)\)/,
  );
  assert.match(
    refreshRuntime,
    /resolveWorkspaceAuthority\(scopedClient\.listWorkspaceAgents\(\)\)/,
  );
  assert.match(refreshRuntime, /const nextDataset = \{[\s\S]*workspaceMembers,[\s\S]*workspaceAgents,/);
  assert.match(refreshRuntime, /failLoadingWorkspaceAuthority\(/);
});

test('notifications never open a standalone workspace review route', () => {
  assert.doesNotMatch(appSource, /activeSection === 'review'/);
  assert.doesNotMatch(appSource, /switchSection\('review'\)/);
  assert.doesNotMatch(appSource, /WorkspaceReviewPanelVariant/);
  assert.doesNotMatch(appSource, /variant = 'workspace'/);
  assert.match(appSource, /className="workbench-layout"/);
  assert.doesNotMatch(appSource, /review-panel-collapsed/);
  assert.doesNotMatch(globalStyles, /review-panel-collapsed/);
});

test('sidebar notifications open the governed notifications settings section', () => {
  assert.match(sidebarSource, /onNavigate\('notifications'\)/);
  assert.match(
    appSource,
    /if \(section === 'notifications'\) openSettingsEntry\('sidebar_notifications'\)/,
  );
});

test('command palette cannot bypass the workspace and conversation hierarchy', () => {
  const commandItems =
    appSource.match(/const commandItems: CommandPaletteItem\[\] = \[[\s\S]*?\n  \];/)?.[0] ?? '';

  assert.doesNotMatch(commandItems, /id: '(?:search-memory|chats|run-selected-session|open-project)'/);
  assert.doesNotMatch(commandItems, /switchSection\('(?:chat|memory)'\)/);
  assert.doesNotMatch(commandItems, /Open in VS Code|Run selected session|Search local memory/);
});

test('connection recovery cannot bypass governed model or workspace settings', () => {
  assert.match(runtimeConfigSource, /update\('apiBaseUrl'/);
  assert.match(runtimeConfigSource, /update\('apiKey'/);
  assert.match(runtimeConfigSource, /update\('mode'/);
  assert.match(runtimeConfigSource, /onClick=\{onRefresh\}/);
  assert.doesNotMatch(
    runtimeConfigSource,
    /update\('(llmProvider|llmBaseUrl|llmModel|llmApiKey|workspaceRoot|tenantId|projectId|workspaceId)'/,
  );
  assert.doesNotMatch(
    runtimeConfigSource,
    /runtime\.(llmProvider|llmBaseUrl|llmModel|llmApiKey|workspaceRoot|tenantId|projectId|workspaceId)/,
  );
  assert.match(runtimeConfigSource, /t\(`runtime\.status\.\$\{connection\}`\)/);
  assert.match(runtimeConfigSource, /aria-label=\{t\('runtime\.connectionMode'\)\}/);
  assert.equal((runtimeConfigSource.match(/role="status"/g) ?? []).length, 2);
  assert.equal((runtimeConfigSource.match(/aria-live="polite"/g) ?? []).length, 2);
  assert.doesNotMatch(
    runtimeConfigSource,
    /aria-label="(Server URL|API key|Connection mode|Connect runtime)"/,
  );
  assert.match(
    globalStyles,
    /\.settings-window-content \.runtime-panel\s*\{[\s\S]*?max-height:\s*none;[\s\S]*?overflow:\s*visible;/,
  );
  assert.doesNotMatch(globalStyles, /\.settings-content \.runtime-panel/);
});

test('conversation detail restores the mission-control context rail without duplicating authority', () => {
  assert.match(sessionWorkspaceSource, /className="session-context-rail"/);
  assert.match(sessionWorkspaceSource, /panes\.contextRail/);
  assert.match(sessionWorkspaceSource, /session\.runSnapshot/);
  assert.match(sessionWorkspaceSource, /session\.workSurfaces/);
  assert.match(sessionWorkspaceSource, /session\.latestEvidence/);
  assert.match(sessionStyles, /grid-template-columns:\s*minmax\(0, 1fr\) 248px/);
  assert.match(sessionWorkspaceSource, /surface !== 'conversation'/);
});

test('conversation header and thread chrome follow the prototype hierarchy', () => {
  assert.match(sessionStyles, /grid-template-rows:\s*76px minmax\(0, 1fr\)/);
  assert.match(sessionWorkspaceSource, /session\.sessionLog/);
  assert.match(sessionWorkspaceSource, /session\.openTask/);
  assert.match(sessionWorkspaceSource, /session\.openCanvas/);
  assert.match(sessionWorkspaceSource, /viewModel\.participantCount/);
});

test('conversation task navigation opens the exact linked task', () => {
  assert.match(
    appSource,
    /onOpenTask=\{[\s\S]*?setSelectedTaskId\(sessionDetailViewModel\.linkedTaskId!\);[\s\S]*?switchSection\('board'\)/,
  );
});

test('session status chrome localizes every workspace-attempt state', () => {
  for (const status of ['pending', 'awaiting_leader_adjudication', 'accepted', 'rejected']) {
    assert.match(sessionWorkspaceSource, new RegExp(`${status}: 'session\\.status`));
  }
  assert.doesNotMatch(sessionWorkspaceSource, /return labels\[normalized\] \? t\(labels\[normalized\]\) : status/);
  assert.match(sessionWorkspaceSource, /status === 'accepted'[\s\S]*return 'green'/);
  assert.match(sessionWorkspaceSource, /status === 'awaiting_leader_adjudication'[\s\S]*return 'amber'/);
  assert.match(sessionWorkspaceSource, /status === 'rejected'[\s\S]*return 'red'/);
});

test('primary work canvases keep governance identifiers out of the user narrative', () => {
  assert.doesNotMatch(sessionChangesSource, /run_id\.slice|patch_digest\.slice/);
  assert.doesNotMatch(sessionTerminalSource, /terminal\.run_id|terminal\.environment_id/);
  assert.doesNotMatch(sessionEvidenceSource, /· r\{(?:row|missing)\.revision\}/);
  assert.doesNotMatch(appSource, /<code>\{selectedVersion\.source_artifact_id\}<\/code>/);
});

test('session activity separates authoritative live state from recorded agent reports', () => {
  assert.match(chatPanelSource, /activityPresence === 'live'/);
  assert.match(chatPanelSource, /session\.agentReportedEvidence/);
  assert.match(chatPanelSource, /session\.structuredEvidenceCount/);
  assert.doesNotMatch(chatPanelSource, /activitySummary\.evidence \|\| activityEvidence/);
  assert.match(
    sessionWorkspaceSource,
    /liveConnected \? t\('session\.liveConnected'\) : t\('session\.liveReconnecting'\)/,
  );
});

test('timeline loaders reject deferred responses after request or scope authority changes', () => {
  const timelineLoader =
    appSource.match(
      /const loadConversationTimeline = useCallback\([\s\S]*?const respondToHitl = useCallback/,
    )?.[0] ?? '';

  assert.match(timelineLoader, /sessionTimelineRequestIsCurrent/);
  assert.match(timelineLoader, /scopeEpoch: configScopeEpochRef\.current/);
  assert.match(appSource, /timelineRequestRef\.current \+= 1;[\s\S]*setConversationTimeline\(emptyConversationTimeline\)/);
});

test('desktop styles remove standalone workspace drawer and pull-request chrome', () => {
  assert.doesNotMatch(globalStyles, /\.review-panel-stage\b/);
  assert.doesNotMatch(globalStyles, /\.review-panel\.(?:maximized|full-screen)\b/);
  assert.doesNotMatch(globalStyles, /\.review-tab-menu\b/);
  assert.doesNotMatch(globalStyles, /\.review-pr\b/);
  assert.doesNotMatch(globalStyles, /\.pr-summary-panel\b/);
  assert.doesNotMatch(sessionStyles, /\.review-head\b/);
});

test('desktop styles contain no retired signed-out or mobile menu chrome', () => {
  assert.doesNotMatch(
    globalStyles,
    /\.(?:signed-out(?:-[\w-]+)?|mobile-section-[\w-]+|session-group-[\w-]+|welcome-(?:shell|timeline)|usage-warning(?:-[\w-]+)?|workflow-(?:strip|chip)|session-scope-[\w-]+|composer-(?:reference-menu|draft-input|toolbar))\b/,
  );
});

test('profile menu keeps account and workspace switching as distinct settings entries', () => {
  assert.match(sidebarSource, /onOpenAccountSettings/);
  assert.match(sidebarSource, /onSwitchWorkspace/);
  assert.match(sidebarSource, /settings\.switchWorkspace/);
  assert.match(appSource, /openSettingsEntry\('profile_workspace_switch'\)/);
});

test('selected conversations are declarative socket state across workspace reconnects', () => {
  assert.match(
    appSource,
    /useAgentSocket\([\s\S]*?scopedConversation\?\.id \?\? null[\s\S]*?\)/,
  );
  assert.doesNotMatch(appSource, /socket\.subscribeConversation\(/);
});

test('every runtime config transition invalidates stale data before the visible scope changes', () => {
  const commit =
    appSource.match(/const commitRuntimeConfig = useCallback\([\s\S]*?\n  \}, \[\]\);/)?.[0] ?? '';

  assert.match(commit, /const previousConfig = configRef\.current/);
  assert.match(commit, /beginDesktopRuntimeScopeTransition\(current, previousConfig, nextConfig\)/);
  assert.ok(commit.indexOf('beginDesktopRuntimeScopeTransition') < commit.indexOf('setConfig'));
});

test('project scope reset clears state refs before replacement hydration can begin', () => {
  const reset =
    appSource.match(/const resetProjectScopedState = \(\) => \{[\s\S]*?\n  \};/)?.[0] ?? '';

  assert.match(reset, /datasetRef\.current = emptyDataset[\s\S]*setDataset\(emptyDataset\)/);
  assert.match(
    reset,
    /expandedWorkspaceIdsRef\.current = clearedExpandedWorkspaceIds[\s\S]*setExpandedWorkspaceIds\(clearedExpandedWorkspaceIds\)/,
  );
});
