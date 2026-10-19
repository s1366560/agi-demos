import { execFileSync } from 'node:child_process';
import { cp, mkdir } from 'node:fs/promises';
import { join } from 'node:path';

export const cuaMacBundleName = 'Memstack Computer Use.app';
export const cuaMacExecutable = cuaMacBundleName + '/Contents/MacOS/cua-helper';
export const cuaMacLockedUse = cuaMacBundleName + '/Contents/Resources/locked-use';
export const cuaMacIdentifier = 'ai.agistack.desktop.cua-helper';

// Build only the requested bundle. Staging beside a live sidecar is a separate,
// explicit build step, so packaging tests cannot replace an executing helper.
export async function createCuaMacBundle({ executable, lockedUse, desktopRoot, destination,
  identity = '-', hardenedRuntime = false }) {
  const contents = join(destination, 'Contents');
  await mkdir(join(contents, 'MacOS'), { recursive: true });
  await mkdir(join(contents, 'Resources'), { recursive: true });
  await cp(executable, join(contents, 'MacOS/cua-helper'));
  await cp(join(desktopRoot, 'cua-helper/Info.plist'), join(contents, 'Info.plist'));
  await cp(join(desktopRoot, 'electron/resources/icon.icns'), join(contents, 'Resources/MemstackComputerUse.icns'));
  await cp(lockedUse, join(contents, 'Resources/locked-use'), { recursive: true });
  const args = ['--force', '--sign', identity, '--identifier', cuaMacIdentifier,
    '--entitlements', join(desktopRoot, 'cua-helper/LockedUse/entitlements.plist')];
  if (hardenedRuntime) args.push('--options', 'runtime');
  execFileSync('/usr/bin/codesign', [...args, destination], { stdio: 'pipe' });
  execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', destination], { stdio: 'pipe' });
}
