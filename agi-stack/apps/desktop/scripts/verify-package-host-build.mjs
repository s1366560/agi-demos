import { cp, mkdir, mkdtemp, rm, symlink } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const staging = await mkdtemp(join(tmpdir(), 'memstack-desktop-host-build-'));
const dest = join(staging, 'agi-stack/apps/desktop');
try {
  await mkdir(dest, { recursive: true });
  for (const item of [
    'src',
    'electron',
    'public',
    'scripts',
    'package.json',
    'electron.vite.config.ts',
    'tsconfig.json',
    'tsconfig.package-host.json',
    'tsconfig.electron.json',
    'index.html',
  ])
    await cp(join(desktop, item), join(dest, item), { recursive: true });
  for (const item of ['plugin-marketplace-ui', 'plugin-runtime', 'plugin-slots']) {
    await cp(resolve(desktop, '../../packages', item), join(staging, 'agi-stack/packages', item), {
      recursive: true,
    });
  }
  await symlink(join(desktop, 'node_modules'), join(dest, 'node_modules'), 'dir');
  const build = spawnSync('npm', ['run', 'build:electron'], {
    cwd: dest,
    stdio: 'inherit',
    env: { ...process.env, AGISTACK_DESKTOP_PROFILE: 'packages' },
  });
  if (build.error) throw build.error;
  if (build.status !== 0) process.exitCode = 1;
} finally {
  await rm(staging, { recursive: true, force: true });
}
