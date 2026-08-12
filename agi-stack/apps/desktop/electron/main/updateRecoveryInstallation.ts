import { isAbsolute, posix, relative, sep, win32 } from 'node:path';

export type UpdateRecoveryInstallation =
  | Readonly<{
      management: 'application';
      targetKind: 'file' | 'directory';
      targetPath: string;
      launchRelativePath: string;
    }>
  | Readonly<{
      management: 'externally_managed';
      reasonCode: 'updates_externally_managed';
    }>;

function macApplicationRoot(executablePath: string): string | null {
  if (!isAbsolute(executablePath)) return null;
  const marker = `${sep}Contents${sep}MacOS${sep}`;
  const markerIndex = executablePath.lastIndexOf(marker);
  if (markerIndex <= 0) return null;
  const root = executablePath.slice(0, markerIndex);
  return root.endsWith('.app') ? root : null;
}

export function resolveUpdateRecoveryInstallation(input: Readonly<{
  platform: NodeJS.Platform;
  executablePath: string;
  appImagePath?: string;
}>): UpdateRecoveryInstallation {
  if (input.platform === 'darwin') {
    const targetPath = macApplicationRoot(input.executablePath);
    if (!targetPath) throw new Error('macOS update recovery installation is invalid');
    return Object.freeze({
      management: 'application',
      targetKind: 'directory',
      targetPath,
      launchRelativePath: relative(targetPath, input.executablePath).split(sep).join('/'),
    });
  }
  if (input.platform === 'win32') {
    if (!win32.isAbsolute(input.executablePath)) {
      throw new Error('Windows update recovery installation is invalid');
    }
    const targetPath = win32.dirname(input.executablePath);
    const launchRelativePath = win32.relative(targetPath, input.executablePath).replaceAll('\\', '/');
    if (!launchRelativePath || launchRelativePath.startsWith('../')) {
      throw new Error('Windows update recovery executable is invalid');
    }
    return Object.freeze({
      management: 'application',
      targetKind: 'directory',
      targetPath,
      launchRelativePath,
    });
  }
  if (input.platform === 'linux') {
    const appImagePath = input.appImagePath;
    if (!appImagePath) {
      return Object.freeze({
        management: 'externally_managed',
        reasonCode: 'updates_externally_managed',
      });
    }
    if (!posix.isAbsolute(appImagePath)) {
      throw new Error('AppImage update recovery installation is invalid');
    }
    return Object.freeze({
      management: 'application',
      targetKind: 'file',
      targetPath: appImagePath,
      launchRelativePath: '.',
    });
  }
  throw new Error('update recovery platform is unsupported');
}
