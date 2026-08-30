import { spawnSync } from 'node:child_process';
import { cpSync, rmSync, statSync, symlinkSync } from 'node:fs';
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

for (const project of ['project-agent', 'project-administration', 'project-knowledge']) {
  const projectDistRoot = `/tmp/agistack-${project}-test-dist`;
  rmSync(projectDistRoot, { recursive: true, force: true });
  const projectCompile = spawnSync(
    process.execPath,
    [tscEntrypoint, '-p', `tests/tsconfig.${project}.json`],
    {
      cwd: desktopRoot,
      stdio: 'inherit',
    },
  );
  if (projectCompile.status !== 0) process.exit(projectCompile.status ?? 1);
}

cpSync(join(desktopRoot, 'src'), join(compiledRoot, 'src'), {
  recursive: true,
  filter: (source) =>
    statSync(source).isDirectory() || source.endsWith('.css') || source.endsWith('.mjs'),
});
symlinkSync(join(desktopRoot, 'node_modules'), join(compiledRoot, 'node_modules'), 'dir');
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
