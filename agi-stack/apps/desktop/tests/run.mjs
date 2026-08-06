import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  assertTestInventoryComplete,
  discoverTestFiles,
} from './testDiscovery.mjs';

const testsDirectory = dirname(fileURLToPath(import.meta.url));
const desktopRoot = dirname(testsDirectory);
const compiledRoot = '/tmp/agistack-desktop-test-dist';
const tscEntrypoint = join(
  desktopRoot,
  'node_modules',
  'typescript',
  'bin',
  'tsc',
);

rmSync(compiledRoot, { recursive: true, force: true });

const compile = spawnSync(
  process.execPath,
  [tscEntrypoint, '-p', 'tsconfig.test.json'],
  {
    cwd: desktopRoot,
    stdio: 'inherit',
  },
);
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

const compiledNavigationDirectory = join(
  compiledRoot,
  'src',
  'features',
  'navigation',
);
mkdirSync(compiledNavigationDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'navigation', 'AuxiliaryView.css'),
  join(compiledNavigationDirectory, 'AuxiliaryView.css'),
);
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'navigation',
    'KeyboardShortcutsDialog.css',
  ),
  join(compiledNavigationDirectory, 'KeyboardShortcutsDialog.css'),
);
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'navigation',
    'NativeUnavailableRoute.css',
  ),
  join(compiledNavigationDirectory, 'NativeUnavailableRoute.css'),
);

const compiledMyWorkDirectory = join(
  compiledRoot,
  'src',
  'features',
  'my-work',
);
mkdirSync(compiledMyWorkDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'my-work', 'MyWorkQueue.css'),
  join(compiledMyWorkDirectory, 'MyWorkQueue.css'),
);

const compiledActivityDirectory = join(compiledRoot, 'src', 'features', 'activity');
mkdirSync(compiledActivityDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'activity', 'ActivityInbox.css'),
  join(compiledActivityDirectory, 'ActivityInbox.css'),
);

const compiledSearchDirectory = join(compiledRoot, 'src', 'features', 'search');
mkdirSync(compiledSearchDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'search', 'DesktopSearch.css'),
  join(compiledSearchDirectory, 'DesktopSearch.css'),
);

const compiledAutomationsDirectory = join(
  compiledRoot,
  'src',
  'features',
  'automations',
);
mkdirSync(compiledAutomationsDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'automations', 'AutomationsPage.css'),
  join(compiledAutomationsDirectory, 'AutomationsPage.css'),
);

const compiledFeedbackDirectory = join(
  compiledRoot,
  'src',
  'features',
  'feedback',
);
mkdirSync(compiledFeedbackDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'feedback', 'ToastCenter.css'),
  join(compiledFeedbackDirectory, 'ToastCenter.css'),
);

const compiledDeviceApprovalDirectory = join(
  compiledRoot,
  'src',
  'features',
  'device-approval',
);
mkdirSync(compiledDeviceApprovalDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'device-approval',
    'DeviceApprovalPage.css',
  ),
  join(compiledDeviceApprovalDirectory, 'DeviceApprovalPage.css'),
);

const compiledTenantCreationDirectory = join(
  compiledRoot,
  'src',
  'features',
  'tenant-creation',
);
mkdirSync(compiledTenantCreationDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'tenant-creation',
    'TenantCreationPage.css',
  ),
  join(compiledTenantCreationDirectory, 'TenantCreationPage.css'),
);

const compiledInvitationAcceptanceDirectory = join(
  compiledRoot,
  'src',
  'features',
  'invitation-acceptance',
);
mkdirSync(compiledInvitationAcceptanceDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'invitation-acceptance',
    'InvitationAcceptancePage.css',
  ),
  join(compiledInvitationAcceptanceDirectory, 'InvitationAcceptancePage.css'),
);

const compiledSettingsDirectory = join(
  compiledRoot,
  'src',
  'features',
  'settings',
);
mkdirSync(compiledSettingsDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'settings', 'SettingsCorePages.css'),
  join(compiledSettingsDirectory, 'SettingsCorePages.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'settings', 'ShortcutSettingsPage.css'),
  join(compiledSettingsDirectory, 'ShortcutSettingsPage.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'settings', 'ManagedResourceViews.css'),
  join(compiledSettingsDirectory, 'ManagedResourceViews.css'),
);

const compiledComponentsDirectory = join(compiledRoot, 'src', 'components');
mkdirSync(compiledComponentsDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'components', 'Skeleton.css'),
  join(compiledComponentsDirectory, 'Skeleton.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'components', 'ResizeHandle.css'),
  join(compiledComponentsDirectory, 'ResizeHandle.css'),
);

const compiledWorkspaceDirectory = join(
  compiledRoot,
  'src',
  'features',
  'workspace',
);
mkdirSync(compiledWorkspaceDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'workspace', 'WorkspaceDock.css'),
  join(compiledWorkspaceDirectory, 'WorkspaceDock.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'workspace', 'WorkspaceOverview.css'),
  join(compiledWorkspaceDirectory, 'WorkspaceOverview.css'),
);

const compiledSessionDirectory = join(compiledRoot, 'src', 'features', 'session');
mkdirSync(compiledSessionDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'session', 'SessionPlanReview.css'),
  join(compiledSessionDirectory, 'SessionPlanReview.css'),
);

const compiledTenantDirectory = join(compiledRoot, 'src', 'features', 'tenant');
mkdirSync(compiledTenantDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'tenant', 'TenantOverviewPage.css'),
  join(compiledTenantDirectory, 'TenantOverviewPage.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'tenant', 'TenantProjectsPage.css'),
  join(compiledTenantDirectory, 'TenantProjectsPage.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'tenant', 'TenantWorkspacesPage.css'),
  join(compiledTenantDirectory, 'TenantWorkspacesPage.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'tenant', 'TenantTasksPage.css'),
  join(compiledTenantDirectory, 'TenantTasksPage.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'tenant', 'TenantAnalyticsPage.css'),
  join(compiledTenantDirectory, 'TenantAnalyticsPage.css'),
);
copyFileSync(
  join(desktopRoot, 'src', 'features', 'tenant', 'TenantAgentBindingsPage.css'),
  join(compiledTenantDirectory, 'TenantAgentBindingsPage.css'),
);
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'tenant',
    'TenantAgentDashboardPage.css',
  ),
  join(compiledTenantDirectory, 'TenantAgentDashboardPage.css'),
);
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'tenant',
    'TenantAgentDashboardHookEditor.css',
  ),
  join(compiledTenantDirectory, 'TenantAgentDashboardHookEditor.css'),
);

const compiledProjectSupportDirectory = join(
  compiledRoot,
  'src',
  'features',
  'project-support',
);
mkdirSync(compiledProjectSupportDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'project-support',
    'ProjectSupportPage.css',
  ),
  join(compiledProjectSupportDirectory, 'ProjectSupportPage.css'),
);

const compiledGovernanceDirectory = join(
  compiledRoot,
  'src',
  'features',
  'governance',
);
mkdirSync(compiledGovernanceDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'governance', 'DeadLetterQueuePage.css'),
  join(compiledGovernanceDirectory, 'DeadLetterQueuePage.css'),
);

const compiledRuntimePoolDirectory = join(
  compiledRoot,
  'src',
  'features',
  'runtime-pool',
);
mkdirSync(compiledRuntimePoolDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'runtime-pool', 'RuntimePoolPage.css'),
  join(compiledRuntimePoolDirectory, 'RuntimePoolPage.css'),
);

const compiledRuntimeInstancesDirectory = join(
  compiledRoot,
  'src',
  'features',
  'runtime-instances',
);

const compiledRuntimeClustersDirectory = join(
  compiledRoot,
  'src',
  'features',
  'runtime-clusters',
);
mkdirSync(compiledRuntimeClustersDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'runtime-clusters',
    'RuntimeClustersPage.css',
  ),
  join(compiledRuntimeClustersDirectory, 'RuntimeClustersPage.css'),
);

const compiledRuntimeDeploymentsDirectory = join(
  compiledRoot,
  'src',
  'features',
  'runtime-deployments',
);
mkdirSync(compiledRuntimeDeploymentsDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'runtime-deployments',
    'RuntimeDeploymentsPage.css',
  ),
  join(compiledRuntimeDeploymentsDirectory, 'RuntimeDeploymentsPage.css'),
);
const compiledInstanceTemplatesDirectory = join(
  compiledRoot,
  'src',
  'features',
  'instance-templates',
);
mkdirSync(compiledInstanceTemplatesDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'instance-templates',
    'InstanceTemplatesPage.css',
  ),
  join(compiledInstanceTemplatesDirectory, 'InstanceTemplatesPage.css'),
);
mkdirSync(compiledRuntimeInstancesDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'runtime-instances',
    'RuntimeInstancesPage.css',
  ),
  join(compiledRuntimeInstancesDirectory, 'RuntimeInstancesPage.css'),
);

const compiledUnifiedRuntimesDirectory = join(
  compiledRoot,
  'src',
  'features',
  'unified-runtimes',
);
mkdirSync(compiledUnifiedRuntimesDirectory, { recursive: true });
copyFileSync(
  join(
    desktopRoot,
    'src',
    'features',
    'unified-runtimes',
    'UnifiedRuntimesPage.css',
  ),
  join(compiledUnifiedRuntimesDirectory, 'UnifiedRuntimesPage.css'),
);

const testFiles = discoverTestFiles(testsDirectory);
assertTestInventoryComplete({ testsDirectory, testFiles });

const run = spawnSync(process.execPath, ['--test', ...testFiles], {
  cwd: desktopRoot,
  env: {
    ...process.env,
    // Pin the ambient locale so render tests are host-locale independent:
    // Node's navigator.language derives from these variables and
    // I18nProvider falls back to it when no stored locale exists.
    LANG: 'en_US.UTF-8',
    LC_ALL: 'en_US.UTF-8',
    NODE_PATH: join(desktopRoot, 'node_modules'),
  },
  stdio: 'inherit',
});
process.exit(run.status ?? 1);
