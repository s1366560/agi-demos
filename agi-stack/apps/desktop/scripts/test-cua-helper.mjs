import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const workspace = resolve(root, '../..');
const result = process.platform === 'darwin'
  ? spawnSync('/bin/zsh', [resolve(root, 'cua-helper/test.sh')], { cwd: workspace, stdio: 'inherit' })
  : spawnSync(process.env.MEMSTACK_CUA_CARGO ?? 'cargo', ['test', '-p', 'memstack-cua-native-helper'],
    { cwd: workspace, stdio: 'inherit' });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
