import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const testsDirectory = dirname(fileURLToPath(import.meta.url));
const desktopRoot = dirname(testsDirectory);
const compiledRoot = '/tmp/agistack-desktop-test-dist';
const tscEntrypoint = join(desktopRoot, 'node_modules', 'typescript', 'bin', 'tsc');

const compile = spawnSync(process.execPath, [tscEntrypoint, '-p', 'tsconfig.test.json'], {
  cwd: desktopRoot,
  stdio: 'inherit',
});
if (compile.status !== 0) process.exit(compile.status ?? 1);

const compiledTaskDirectory = join(compiledRoot, 'src', 'features', 'task');
mkdirSync(compiledTaskDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'task', 'NewTaskFlow.css'),
  join(compiledTaskDirectory, 'NewTaskFlow.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'task', 'NewTaskPlanReview.css'),
  join(compiledTaskDirectory, 'NewTaskPlanReview.css'),
);

const compiledNavigationDirectory = join(compiledRoot, 'src', 'features', 'navigation');
mkdirSync(compiledNavigationDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'navigation', 'AuxiliaryView.css'),
  join(compiledNavigationDirectory, 'AuxiliaryView.css'),
);

const compiledMyWorkDirectory = join(compiledRoot, 'src', 'features', 'my-work');
mkdirSync(compiledMyWorkDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'my-work', 'MyWorkQueue.css'),
  join(compiledMyWorkDirectory, 'MyWorkQueue.css'),
);

const compiledSearchDirectory = join(compiledRoot, 'src', 'features', 'search');
mkdirSync(compiledSearchDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'search', 'DesktopSearch.css'),
  join(compiledSearchDirectory, 'DesktopSearch.css'),
);

const compiledWorkspaceDirectory = join(compiledRoot, 'src', 'features', 'workspace');
mkdirSync(compiledWorkspaceDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'workspace', 'WorkspaceDock.css'),
  join(compiledWorkspaceDirectory, 'WorkspaceDock.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'workspace', 'WorkspaceOverview.css'),
  join(compiledWorkspaceDirectory, 'WorkspaceOverview.css'),
);

const testFiles = [
  'a2ui-action.test.mjs',
  'agent-event-identity-model.test.mjs',
  'agent-stop-response-model.test.mjs',
  'agent-task-signal-model.test.mjs',
  'agent-event-parity.test.mjs',
  'api-client.test.mjs',
  'application-vault.test.mjs',
  'automation-model.test.mjs',
  'auxiliary-view.test.mjs',
  'auth-context-model.test.mjs',
  'force-password-change.test.mjs',
  'chat-composer-model.test.mjs',
  'voice-transcription.test.mjs',
  'voice-call.test.mjs',
  'compose-ahead-model.test.mjs',
  'composer-catalog-model.test.mjs',
  'composer-mentions.test.mjs',
  'composer-context.test.mjs',
  'chat-narrative-presentation.test.mjs',
  'mermaid-rendering.test.mjs',
  'markdown-math-rendering.test.mjs',
  'assistant-artifact-references.test.mjs',
  'artifact-timeline-card.test.mjs',
  'markdown-artifact-image.test.mjs',
  'forced-skill-message-badge.test.mjs',
  'timeline-turn-collapse-model.test.mjs',
  'conversation-search-model.test.mjs',
  'pinned-message-model.test.mjs',
  'conversation-export-model.test.mjs',
  'conversation-comparison-model.test.mjs',
  'chat-timeline-model.test.mjs',
  'artifact-canvas-events.test.mjs',
  'mcp-app-canvas-events.test.mjs',
  'mcp-app-timeline-model.test.mjs',
  'mcp-app-host-bridge.test.mjs',
  'memory-timeline-model.test.mjs',
  'skill-timeline-group-model.test.mjs',
  'cloud-session-queue-qa.test.mjs',
  'conversation-title-events.test.mjs',
  'desktop-shell-fidelity.test.mjs',
  'desktop-search-model.test.mjs',
  'desktop-search.test.mjs',
  'desktop-a11y-i18n.test.mjs',
  'electron-vite-integration.test.mjs',
  'electron-media-permission.test.mjs',
  'hitl-response-events.test.mjs',
  'workspace-message-event-model.test.mjs',
  'workspace-task-event-model.test.mjs',
  'workspace-roster-event-model.test.mjs',
  'workspace-lifecycle-event-model.test.mjs',
  'workspace-activity-event-model.test.mjs',
  'login-screen-fidelity.test.mjs',
  'login-screen-model.test.mjs',
  'electron-signing.test.mjs',
  'automatic-update-loop.test.mjs',
  'updater-policy.test.mjs',
  'release-artifact-verifier.test.mjs',
  'runtime-config-model.test.mjs',
  'search-contract.test.mjs',
  'real-sidecar-integration.test.mjs',
  'sidecar-supervisor.test.mjs',
  'trusted-session-broker.test.mjs',
  'local-runtime-status.test.mjs',
  'my-work-mission-control.test.mjs',
  'my-work-model.test.mjs',
  'navigation-contract.test.mjs',
  'new-thread-workspace-selection.test.mjs',
  'new-task-plan-model.test.mjs',
  'new-task-plan-approval.test.mjs',
  'new-task-flow-fidelity.test.mjs',
  'new-task-recovery.test.mjs',
  'new-task-session-model.test.mjs',
  'session-projection-model.test.mjs',
  'session-plan-approval-model.test.mjs',
  'session-plan-review.test.mjs',
  'session-view-model.test.mjs',
  'session-scope.test.mjs',
  'session-selection-model.test.mjs',
  'session-timeline-pagination-model.test.mjs',
  'session-timeline-scroll-model.test.mjs',
  'session-layout-model.test.mjs',
  'workspace-review-panel-model.test.mjs',
  'session-canvas-model.test.mjs',
  'session-changes-model.test.mjs',
  'session-run-input-model.test.mjs',
  'session-terminal-model.test.mjs',
  'session-invocation-ledger-model.test.mjs',
  'session-agent-tree-model.test.mjs',
  'session-execution-graph-model.test.mjs',
  'session-execution-insights-model.test.mjs',
  'session-context-window-model.test.mjs',
  'session-runtime-infrastructure-model.test.mjs',
  'session-narrative-model.test.mjs',
  'session-decision-model.test.mjs',
  'session-evidence-model.test.mjs',
  'session-artifact-model.test.mjs',
  'settings-navigation-model.test.mjs',
  'settings-entry-routing.test.mjs',
  'settings-modal-behavior.test.mjs',
  'agent-definition-form-model.test.mjs',
  'skill-editor-model.test.mjs',
  'skill-package-management.test.mjs',
  'subagent-library-management.test.mjs',
  'plugin-management-model.test.mjs',
  'plugin-runtime-activity.test.mjs',
  'prompt-template-model.test.mjs',
  'channel-connection-management.test.mjs',
  'sidecar-command-surface.test.mjs',
  'managed-resource-model.test.mjs',
  'provider-management.test.mjs',
  'use-agent-socket.test.mjs',
  'use-terminal-proxy.test.mjs',
  'workspace-tree-model.test.mjs',
  'workspace-create-model.test.mjs',
  'workspace-create-dialog.test.mjs',
  'workspace-settings-model.test.mjs',
  'workspace-settings-dialog.test.mjs',
  'workspace-members-model.test.mjs',
  'workspace-members-panel.test.mjs',
  'workspace-agent-bindings-model.test.mjs',
  'workspace-agent-bindings-panel.test.mjs',
  'workspace-overview-model.test.mjs',
  'workspace-overview-style.test.mjs',
  'workspace-execution-model.test.mjs',
].map((filename) => join(testsDirectory, filename));
const run = spawnSync(process.execPath, ['--test', ...testFiles], {
  cwd: desktopRoot,
  env: {
    ...process.env,
    NODE_PATH: join(desktopRoot, 'node_modules'),
  },
  stdio: 'inherit',
});
process.exit(run.status ?? 1);
