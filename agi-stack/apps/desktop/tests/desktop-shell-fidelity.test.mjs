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
const sidebarSource = readFileSync(
  new URL('../src/features/navigation/DesktopSidebar.tsx', import.meta.url),
  'utf8'
);

test('desktop shell mounts only the prototype sidebar and page-owned headers', () => {
  assert.doesNotMatch(appSource, /className="titlebar"/);
  assert.doesNotMatch(appSource, /className="copilot-sidebar"/);
  assert.equal((appSource.match(/<DesktopSidebar\b/g) ?? []).length, 1);
});

test('authenticated identities without a project remain inside the desktop shell', () => {
  const renderWorkbench =
    appSource.match(/const renderWorkbench = \(\) => \{[\s\S]*?\n  \};\n\n  if \(!identityAuthenticated\)/)?.[0] ?? '';

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

test('notifications never open a standalone workspace review route', () => {
  assert.doesNotMatch(appSource, /activeSection === 'review'/);
  assert.doesNotMatch(appSource, /switchSection\('review'\)/);
  assert.doesNotMatch(appSource, /WorkspaceReviewPanelVariant/);
  assert.doesNotMatch(appSource, /variant = 'workspace'/);
  assert.match(appSource, /className="workbench-layout"/);
  assert.doesNotMatch(appSource, /review-panel-collapsed/);
  assert.doesNotMatch(globalStyles, /review-panel-collapsed/);
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

test('Home clears an open conversation through the workspace-overview transition', () => {
  assert.match(
    appSource,
    /const openWorkspaceOverview = \(\) => \{[\s\S]*?selectWorkspace\(config\.workspaceId, config\.projectId\);/,
  );
  assert.match(appSource, /if \(section === 'home'\) openWorkspaceOverview\(\)/);
  assert.match(appSource, /onSelect: openWorkspaceOverview/);
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
