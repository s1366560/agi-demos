import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { refreshCuaChecksums, verifyCuaRuntime } from './cua-packaging.mjs';

export default async function sealCuaAfterSign(context) {
  if (context.electronPlatformName === 'win32') {
    const directory = join(context.appOutDir, 'resources/sidecar');
    await refreshCuaChecksums(directory, 'win32');
    await verifyCuaRuntime(directory, { platform: 'win32' });
  } else if (context.electronPlatformName === 'darwin') {
    const app = join(context.appOutDir, context.packager.appInfo.productFilename + '.app');
    const inspected = spawnSync('/usr/bin/codesign', ['--display', '--verbose=4', app], { encoding: 'utf8' });
    if (inspected.status !== 0) throw new Error('Cannot inspect packaged application signature');
    const line = inspected.stderr.split('\n').find((value) => value.startsWith('TeamIdentifier='));
    const team = line?.slice('TeamIdentifier='.length);
    await verifyCuaRuntime(join(app, 'Contents/Resources/sidecar'), {
      platform: 'darwin', team: team && team !== 'not set' ? team : undefined, universal: true,
    });
  }
}
