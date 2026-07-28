import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { assertTestInventoryComplete, discoverTestFiles } from './testDiscovery.mjs';

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
copyFileSync(
  join(desktopRoot, 'src', 'features', 'navigation', 'KeyboardShortcutsDialog.css'),
  join(compiledNavigationDirectory, 'KeyboardShortcutsDialog.css'),
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

const compiledFeedbackDirectory = join(compiledRoot, 'src', 'features', 'feedback');
mkdirSync(compiledFeedbackDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'feedback', 'ToastCenter.css'),
  join(compiledFeedbackDirectory, 'ToastCenter.css'),
);

const compiledSettingsDirectory = join(compiledRoot, 'src', 'features', 'settings');
mkdirSync(compiledSettingsDirectory, { recursive: true });
copyFileSync(
  join(desktopRoot, 'src', 'features', 'settings', 'SettingsCorePages.css'),
  join(compiledSettingsDirectory, 'SettingsCorePages.css'),
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
