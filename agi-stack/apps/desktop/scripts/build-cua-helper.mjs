import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { copyFileSync, cpSync, mkdirSync, renameSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { cuaMacBundleName } from './cua-layout.mjs';
import { stageCuaMacBundle } from './cua-staging.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const workspace = resolve(root, '../..');
const debug = process.argv.includes('--debug');
const profile = debug ? 'debug' : 'release';
const releaseArgs = debug ? [] : ['--release'];
const cargo = process.env.MEMSTACK_CUA_CARGO ?? 'cargo';
const targets = process.env.CARGO_TARGET_DIR ? resolve(workspace, process.env.CARGO_TARGET_DIR) : resolve(workspace, 'target');
function run(command, args, env = process.env) {
  const result = spawnSync(command, args, { cwd: workspace, stdio: 'inherit', env });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
if (process.platform === 'darwin') {
  run('/bin/zsh', [resolve(root, 'cua-helper/build.sh')], {
    ...process.env, MEMSTACK_CUA_UNIVERSAL: debug ? '0' : '1',
  });
} else {
  run(cargo, ['build', '-p', 'memstack-cua-native-helper', ...releaseArgs]);
}
if (process.platform === 'darwin' && !debug) {
  run(process.env.MEMSTACK_CUA_RUSTUP ?? 'rustup', ['target', 'add', 'aarch64-apple-darwin', 'x86_64-apple-darwin']);
  for (const target of ['aarch64-apple-darwin', 'x86_64-apple-darwin']) {
    run(cargo, ['build', '-p', 'memstack-cua-cloud-connectors', '--release', '--target', target]);
  }
  mkdirSync(resolve(targets, 'release'), { recursive: true });
  run('/usr/bin/lipo', ['-create',
    resolve(targets, 'aarch64-apple-darwin/release/memstack-cua-cloud-connectors'),
    resolve(targets, 'x86_64-apple-darwin/release/memstack-cua-cloud-connectors'),
    '-output', resolve(targets, 'release/memstack-cua-cloud-connectors')]);
} else {
  run(cargo, ['build', '-p', 'memstack-cua-cloud-connectors', ...releaseArgs]);
}
if (process.platform === 'darwin') {
  const cloud = resolve(targets, profile, 'memstack-cua-cloud-connectors');
  const signed = resolve(targets, profile, '.cua-cloud-stage-' + randomUUID());
  copyFileSync(cloud, signed);
  run('/usr/bin/codesign', ['--force', '--sign', process.env.MEMSTACK_CUA_CODESIGN_IDENTITY ?? '-',
    '--identifier', 'ai.agistack.desktop.cua.cloud-connectors', signed]);
  renameSync(signed, cloud);
}
if (debug) {
  const suffix = process.platform === 'win32' ? '.exe' : '';
  const destination = resolve(targets, profile);
  mkdirSync(destination, { recursive: true });
  if (process.platform === 'darwin') {
    stageCuaMacBundle({ source: resolve(root, 'cua-helper/bin', cuaMacBundleName),
      destination: resolve(destination, cuaMacBundleName) });
  } else {
    const temporary = resolve(destination, '.cua-helper-stage-' + randomUUID() + suffix);
    copyFileSync(resolve(destination, 'memstack-cua-native-helper' + suffix), temporary);
    renameSync(temporary, resolve(destination, 'cua-helper' + suffix));
  }
  cpSync(resolve(root, 'cua-plugin/skills'), resolve(destination, 'cua-plugin/skills'), { recursive: true });
}
