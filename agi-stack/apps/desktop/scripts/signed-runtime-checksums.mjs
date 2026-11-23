// The OS signature changes executable bytes. Record that digest before sealing the app.
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';

export async function recordRuntimeChecksums(resources, { platform, full }) {
  const suffix = platform === 'win32' ? '.exe' : '';
  const runtimes = [['sidecar', 'agistack-desktop-sidecar' + suffix]];
  if (full) runtimes.push(['workspace-core', 'memstack-workspace-core' + suffix]);
  for (const [directory, executable] of runtimes) {
    const root = join(resources, directory);
    const digest = createHash('sha256')
      .update(await readFile(join(root, executable)))
      .digest('hex');
    await writeFile(join(root, 'SHA256SUMS'), digest + '  ' + executable + '\n');
  }
}

export async function sealMacRuntimes(
  appPath,
  identity,
  { keychain, timestamp = true, full = false } = {},
) {
  await recordRuntimeChecksums(join(appPath, 'Contents/Resources'), { platform: 'darwin', full });
  const args = [
    '--force',
    '--sign',
    identity,
    '--preserve-metadata=identifier,entitlements,requirements,flags,runtime',
  ];
  if (keychain) args.push('--keychain', keychain);
  if (timestamp) args.push('--timestamp');
  args.push(appPath);
  execFileSync('/usr/bin/codesign', args);
  execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath]);
}

export async function sign(options) {
  const require = createRequire(import.meta.url);
  const builder = createRequire(require.resolve('electron-builder'));
  await builder('app-builder-lib/out/codeSign/macCodeSign.js').sign(options);
  await sealMacRuntimes(options.app, options.identity, { keychain: options.keychain });
}

export default async function afterSign(context) {
  if (context.electronPlatformName === 'win32') {
    await recordRuntimeChecksums(join(context.appOutDir, 'resources'), {
      platform: 'win32',
      full: false,
    });
  }
}
