import { spawnSync } from 'node:child_process';
import {
  cpSync,
  existsSync,
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

for (const folder of ['apps', 'packages']) {
  symlinkSync(join(compiledRoot, 'agi-stack', folder), join(compiledRoot, folder), 'dir');
}
const compiledDesktopRoot = join(compiledRoot, 'agi-stack', 'apps', 'desktop');
for (const entry of readdirSync(compiledDesktopRoot)) {
  if (entry === 'src') continue;
  // Preserve package-relative imports from Main and preload in the legacy test fixture paths.
  symlinkSync(join(compiledDesktopRoot, entry), join(compiledRoot, entry),
    statSync(join(compiledDesktopRoot, entry)).isDirectory() ? 'dir' : 'file');
}

const testNodeModules = join(compiledRoot, 'test-node-modules');
const compiledPluginSlotsRoot = join(
  testNodeModules,
  '@agistack',
  'plugin-slots',
);
mkdirSync(compiledPluginSlotsRoot, { recursive: true });
writeFileSync(
  join(compiledPluginSlotsRoot, 'package.json'),
  JSON.stringify({ main: '../../../packages/plugin-slots/src/index.js', type: 'commonjs' }),
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
  for (const folder of ['apps', 'packages']) {
    symlinkSync(join(projectDistRoot, 'agi-stack', folder), join(projectDistRoot, folder), 'dir');
  }
  const projectDesktopRoot = join(projectDistRoot, 'agi-stack', 'apps', 'desktop');
  const modules = join(projectDistRoot, 'node_modules');
  mkdirSync(modules);
  symlinkSync(join(projectDesktopRoot, 'src'), join(modules, '@desktop'), 'dir');
  symlinkSync(join(projectDistRoot, 'plugins/business'), join(modules, '@business'), 'dir');
  copyAssets(projectDesktopRoot);
  symlinkSync(join(desktopRoot, 'node_modules'), join(projectDesktopRoot, 'node_modules'), 'dir');
  symlinkSync(join(projectDesktopRoot, 'src'), join(projectDistRoot, 'src'), 'dir');
}

function copyAssets(destination) {
  const businessRoot = join(desktopRoot, '../../../plugins/business');
  const output = join(destination, '../../../plugins/business');
  for (const entry of readdirSync(businessRoot)) {
    const assets = join(businessRoot, entry, 'ui/desktop');
    if (!existsSync(assets)) continue;
    cpSync(assets, join(output, entry, 'ui/desktop'), {
      recursive: true,
      filter: (source) => statSync(source).isDirectory() || source.endsWith('.css'),
    });
  }
  cpSync(join(desktopRoot, 'src'), join(destination, 'src'), {
    recursive: true,
    filter: (source) =>
      statSync(source).isDirectory() || source.endsWith('.css') || source.endsWith('.mjs'),
  });
}
cpSync(
  join(desktopRoot, '../../packages/plugin-marketplace-ui/src'),
  join(compiledRoot, 'agi-stack/packages/plugin-marketplace-ui/src'),
  { recursive: true, filter: (source) => statSync(source).isDirectory() || source.endsWith('.css') },
);
copyAssets(compiledDesktopRoot);
// Vendor adapters use explicit relative node_modules paths from the real src directory.
symlinkSync(join(desktopRoot, 'node_modules'), join(compiledDesktopRoot, 'node_modules'), 'dir');
symlinkSync(join(compiledDesktopRoot, 'src'), join(compiledRoot, 'src'), 'dir');
symlinkSync(join(desktopRoot, 'node_modules'), join(compiledRoot, 'node_modules'), 'dir');
symlinkSync(join(compiledDesktopRoot, 'src'), join(testNodeModules, '@desktop'), 'dir');
symlinkSync(join(compiledRoot, 'plugins/business'), join(testNodeModules, '@business'), 'dir');
const testFiles = discoverTestFiles(testsDirectory);
assertTestInventoryComplete({ testsDirectory, testFiles });

const run = spawnSync(process.execPath, [
  '--import',
  join(testsDirectory, 'fullDesktopFlag.mjs'),
  '--import',
  join(testsDirectory, 'rawAssets.mjs'),
  '--test',
  '--test-force-exit',
  ...testFiles,
], {
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
