import { spawnSync } from 'node:child_process';
import {
  cpSync,
  mkdirSync,
  readdirSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { delimiter, dirname, join } from 'node:path';
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

const compiledDesktopRoot = join(compiledRoot, 'apps', 'desktop');
for (const entry of readdirSync(compiledDesktopRoot)) {
  if (entry === 'src') continue;
  cpSync(join(compiledDesktopRoot, entry), join(compiledRoot, entry), {
    recursive: true,
  });
}

const testNodeModules = join(compiledRoot, 'test-node-modules');
const compiledPluginSlotsRoot = join(
  testNodeModules,
  '@agistack',
  'plugin-slots',
);
mkdirSync(compiledPluginSlotsRoot, { recursive: true });
cpSync(
  join(compiledRoot, 'packages', 'plugin-slots', 'src'),
  compiledPluginSlotsRoot,
  { recursive: true },
);
writeFileSync(
  join(compiledPluginSlotsRoot, 'package.json'),
  JSON.stringify({ main: 'index.js', type: 'commonjs' }),
);

const compiledPluginRuntimeRoot = join(
  testNodeModules,
  '@agistack',
  'plugin-runtime',
);
mkdirSync(compiledPluginRuntimeRoot, { recursive: true });
writeFileSync(
  join(compiledPluginRuntimeRoot, 'package.json'),
  JSON.stringify({
    main: '../../../packages/plugin-runtime/src/index.js',
    type: 'commonjs',
  }),
);

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
  // Keep package-relative imports intact while retaining the public test fixture path.
  const projectDesktopRoot = join(projectDistRoot, 'apps', 'desktop');
  copyAssets(projectDesktopRoot);
  symlinkSync(join(desktopRoot, 'node_modules'), join(projectDesktopRoot, 'node_modules'), 'dir');
  symlinkSync(join(projectDesktopRoot, 'src'), join(projectDistRoot, 'src'), 'dir');
}

function copyAssets(destination) {
  cpSync(join(desktopRoot, 'src'), join(destination, 'src'), {
    recursive: true,
    filter: (source) =>
      statSync(source).isDirectory() || source.endsWith('.css') || source.endsWith('.mjs'),
  });
}
copyAssets(compiledDesktopRoot);
// Vendor adapters use explicit relative node_modules paths from the real src directory.
symlinkSync(join(desktopRoot, 'node_modules'), join(compiledDesktopRoot, 'node_modules'), 'dir');
symlinkSync(join(compiledDesktopRoot, 'src'), join(compiledRoot, 'src'), 'dir');
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
    NODE_PATH: [testNodeModules, join(desktopRoot, 'node_modules')].join(delimiter),
  },
  stdio: 'inherit',
});
process.exit(run.status ?? 1);
