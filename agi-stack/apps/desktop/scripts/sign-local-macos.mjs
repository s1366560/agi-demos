import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { join } from 'node:path';

const executeFile = promisify(execFile);

export default async function signLocalMacos(context) {
  if (context.electronPlatformName !== 'darwin') return;

  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = join(context.appOutDir, appName);
  const entitlementsPath = join(
    context.packager.projectDir,
    'electron',
    'resources',
    'entitlements.mac.local.plist',
  );

  await executeFile('/usr/bin/codesign', [
    '--force',
    '--deep',
    '--sign',
    '-',
    '--options',
    'runtime',
    '--entitlements',
    entitlementsPath,
    appPath,
  ]);
  await executeFile('/usr/bin/codesign', [
    '--verify',
    '--deep',
    '--strict',
    appPath,
  ]);
}
