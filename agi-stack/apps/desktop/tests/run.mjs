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

const testFiles = [
  'a2ui-action.test.mjs',
  'api-client.test.mjs',
  'automation-model.test.mjs',
  'auth-context-model.test.mjs',
  'chat-composer-model.test.mjs',
  'login-screen-model.test.mjs',
  'trusted-local-session-reference.test.mjs',
  'local-runtime-status.test.mjs',
  'my-work-model.test.mjs',
  'new-task-plan-model.test.mjs',
  'new-task-plan-approval.test.mjs',
  'session-projection-model.test.mjs',
  'session-view-model.test.mjs',
  'session-scope.test.mjs',
  'session-layout-model.test.mjs',
  'workspace-review-panel-model.test.mjs',
  'session-canvas-model.test.mjs',
  'session-changes-model.test.mjs',
  'session-run-input-model.test.mjs',
  'session-terminal-model.test.mjs',
  'session-invocation-ledger-model.test.mjs',
  'session-narrative-model.test.mjs',
  'session-decision-model.test.mjs',
  'session-evidence-model.test.mjs',
  'session-artifact-model.test.mjs',
  'settings-navigation-model.test.mjs',
  'settings-entry-routing.test.mjs',
  'managed-resource-model.test.mjs',
  'provider-management.test.mjs',
  'use-agent-socket.test.mjs',
  'use-terminal-proxy.test.mjs',
  'workspace-tree-model.test.mjs',
  'workspace-overview-model.test.mjs',
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
