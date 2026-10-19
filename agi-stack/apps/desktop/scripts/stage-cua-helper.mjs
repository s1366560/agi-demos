import { chmod, copyFile, cp, mkdir, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { cuaMacBundleName } from './cua-layout.mjs';
import { refreshCuaChecksums } from './cua-packaging.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const suffix = process.platform === 'win32' ? '.exe' : '';
const targetRoot = process.env.CARGO_TARGET_DIR
  ? resolve(root, '../..', process.env.CARGO_TARGET_DIR)
  : resolve(root, '../../target');
const directory = resolve(root, 'build/sidecar');
const name = 'cua-helper' + suffix;
await mkdir(directory, { recursive: true });
const destination = resolve(directory, name);
if (process.platform === 'darwin') {
  await rm(resolve(directory, cuaMacBundleName), { recursive: true, force: true });
  await cp(resolve(root, 'cua-helper/bin', cuaMacBundleName), resolve(directory, cuaMacBundleName), { recursive: true });
  // Remove only obsolete products owned by this staging step, not user files.
  await rm(destination, { force: true });
  await rm(resolve(directory, 'locked-use'), { recursive: true, force: true });
} else {
  await copyFile(resolve(targetRoot, 'release', 'memstack-cua-native-helper' + suffix), destination);
  if (process.platform !== 'win32') await chmod(destination, 0o755);
}

const connectorName = 'memstack-cua-cloud-connectors' + suffix;
const connectorDestination = resolve(directory, connectorName);
await copyFile(resolve(targetRoot, 'release', connectorName), connectorDestination);
if (process.platform !== 'win32') await chmod(connectorDestination, 0o755);
await cp(resolve(root, 'cua-plugin/skills'), resolve(directory, 'cua-plugin/skills'), { recursive: true });
await refreshCuaChecksums(directory, process.platform);
