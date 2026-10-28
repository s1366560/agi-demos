import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { access, lstat, readFile, writeFile } from 'node:fs/promises';
import { constants } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { cuaMacBundleName, cuaMacExecutable, cuaMacIdentifier, cuaMacLockedUse } from './cua-layout.mjs';

export const cuaMacIdentities = new Map([
  ['cua-repl/bin/node', 'ai.agistack.desktop.cua.repl-node'],
  [cuaMacBundleName, cuaMacIdentifier],
  [cuaMacExecutable, cuaMacIdentifier],
  ['memstack-cua-cloud-connectors', 'ai.agistack.desktop.cua.cloud-connectors'],
  [cuaMacLockedUse + '/memstack-cua-guardian', 'ai.agistack.desktop.cua.guardian'],
  [cuaMacLockedUse + '/memstack-cua-lock-installer', 'ai.agistack.desktop.cua.lock-installer'],
  [cuaMacLockedUse + '/MemStackComputerUseAuthorizationPlugin.bundle', 'ai.agistack.desktop.cua.authorization-plugin'],
  [cuaMacLockedUse + '/MemStackComputerUseAuthorizationPlugin.bundle/Contents/MacOS/MemStackComputerUseAuthorizationPlugin',
    'ai.agistack.desktop.cua.authorization-plugin'],
]);
function runtimes(platform) {
  const suffix = platform === 'win32' ? '.exe' : '';
  const helper = platform === 'darwin' ? [cuaMacExecutable,
    cuaMacBundleName + '/Contents/Info.plist',
    cuaMacBundleName + '/Contents/Resources/MemstackComputerUse.icns',
    cuaMacBundleName + '/Contents/_CodeSignature/CodeResources'] : ['cua-helper' + suffix];
  return [[helper, 'CUA_SHA256SUMS'],
    [['memstack-cua-cloud-connectors' + suffix], 'CUA_CONNECTORS_SHA256SUMS']];
}
export async function refreshCuaChecksums(directory, platform) {
  for (const [names, checksum] of runtimes(platform)) {
    const lines = [];
    for (const name of names) {
      const digest = createHash('sha256').update(await readFile(join(directory, name))).digest('hex');
      lines.push(digest + '  ' + name);
    }
    await writeFile(join(directory, checksum), lines.join('\n') + '\n', 'utf8');
  }
}
export async function verifyCuaRuntime(directory, { platform = process.platform, team, universal = false } = {}) {
  for (const [names, checksum] of runtimes(platform)) {
    const lines = [];
    for (const name of names) {
      const path = join(directory, name);
      const stat = await lstat(path);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size === 0) throw new Error('Invalid CUA runtime: ' + name);
      const executable = name === 'cua-helper' || name.endsWith('.exe') || name === cuaMacExecutable || name.startsWith('memstack-cua-cloud-connectors');
      await access(path, platform === 'win32' || !executable ? constants.R_OK : constants.X_OK);
      const digest = createHash('sha256').update(await readFile(path)).digest('hex');
      lines.push(digest + '  ' + name);
      if (platform === 'linux') {
        const dependencies = execFileSync('ldd', [path], { encoding: 'utf8' });
        if (dependencies.includes('=> not found')) throw new Error('CUA runtime unavailable: missing system library for ' + name);
      }
      if (platform === 'win32') {
        const literal = path.replaceAll("'", "''");
        const script = "$signature = Get-AuthenticodeSignature -LiteralPath '" + literal
          + "'; if ($signature.Status -ne 'Valid') { throw 'CUA runtime Authenticode is invalid' }";
        execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', '-'],
          { input: script, stdio: ['pipe', 'pipe', 'pipe'] });
      }
    }
    if ((await readFile(join(directory, checksum), 'utf8')).trim() !== lines.join('\n')) {
      throw new Error('Packaged CUA runtime checksum mismatch: ' + names[0]);
    }
  }
  await access(join(directory, 'cua-plugin/skills/computer-use/SKILL.md'), constants.R_OK);
  if (platform === 'darwin') {
    for (const [relative, expected] of cuaMacIdentities) {
      const path = join(directory, relative);
      execFileSync('/usr/bin/codesign', ['--verify', '--strict', path], { stdio: 'pipe' });
      // codesign emits metadata on stderr, even for a successful inspection.
      const detail = spawnInspection(path);
      if (!detail.split('\n').includes('Identifier=' + expected)) throw new Error('Unexpected CUA signing identifier: ' + relative);
      if (team && !detail.split('\n').includes('TeamIdentifier=' + team)) throw new Error('CUA signing team mismatch: ' + relative);
      if (universal && !relative.endsWith('.bundle') && !relative.endsWith('.app')) {
        const arches = execFileSync('/usr/bin/lipo', ['-archs', path], { encoding: 'utf8' }).trim().split(/\s+/);
        if (!arches.includes('arm64') || !arches.includes('x86_64')) throw new Error('CUA runtime must be universal: ' + relative);
      }
    }
  }
}
function spawnInspection(path) {
  const result = spawnSync('/usr/bin/codesign', ['--display', '--verbose=4', path], { encoding: 'utf8' });
  if (result.status !== 0) throw new Error('Cannot inspect CUA signature');
  return result.stdout + result.stderr;
}
export function cuaOptionsForFile(filePath, appPath, prior = {}) {
  const root = join(appPath, 'Contents/Resources/sidecar');
  const relative = filePath.startsWith(root + '/') ? filePath.slice(root.length + 1) : '';
  const identifier = cuaMacIdentities.get(relative);
  if (!identifier) return prior;
  return { ...prior,
    ...(relative === 'cua-repl/bin/node' ? { hardenedRuntime: true,
      entitlements: fileURLToPath(new URL('../electron/resources/entitlements.cua-node.plist', import.meta.url)) } : {}),
    additionalArguments: [...(prior.additionalArguments ?? []), '--identifier', identifier] };
}
export async function signCuaNodeRuntime(appPath, identity, { keychain, timestamp = true } = {}) {
  const nodePath = join(appPath, 'Contents/Resources/sidecar/cua-repl/bin/node');
  const metadata = await lstat(nodePath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size === 0) {
    throw new Error('Packaged CUA Node runtime must be a regular executable');
  }
  await access(nodePath, constants.X_OK);
  const args = ['--force', '--sign', identity, '--options', 'runtime', '--identifier',
    'ai.agistack.desktop.cua.repl-node', '--entitlements',
    fileURLToPath(new URL('../electron/resources/entitlements.cua-node.plist', import.meta.url))];
  if (keychain) args.push('--keychain', keychain);
  if (timestamp) args.push('--timestamp');
  args.push(nodePath);
  execFileSync('/usr/bin/codesign', args, { stdio: 'pipe' });
  execFileSync('/usr/bin/codesign', ['--verify', '--strict', nodePath], { stdio: 'pipe' });
}
export async function sealCuaMacApp(appPath, identity, { keychain, timestamp = true } = {}) {
  await refreshCuaChecksums(join(appPath, 'Contents/Resources/sidecar'), 'darwin');
  const args = ['--force', '--sign', identity,
    '--preserve-metadata=identifier,entitlements,requirements,flags,runtime'];
  if (keychain) args.push('--keychain', keychain);
  if (timestamp) args.push('--timestamp');
  args.push(appPath);
  execFileSync('/usr/bin/codesign', args, { stdio: 'pipe' });
  execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', appPath], { stdio: 'pipe' });
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const directory = process.argv[2];
  if (!directory) throw new Error('CUA resources directory is required');
  await verifyCuaRuntime(directory);
  process.stdout.write('CUA_PACKAGE_RUNTIME_OK\n');
}
