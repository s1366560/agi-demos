import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repositoryRoot = resolve(desktopRoot, '../../..');
const cargoWrapper = resolve(repositoryRoot, 'scripts/avernet-bcs/cargo.sh');
const profile = process.argv[2] ?? 'release';
if (profile !== 'debug' && profile !== 'release') {
  throw new Error('Workspace Core build profile must be debug or release');
}

const args = [
  'build',
  '-p',
  'memstack-workspace-core',
  '--bin',
  'memstack-workspace-core',
  '--locked',
];
if (profile === 'release') args.push('--release');
const command = process.platform === 'win32' ? 'bash' : cargoWrapper;
const commandArgs = process.platform === 'win32' ? [cargoWrapper, ...args] : args;
execFileSync(command, commandArgs, {
  cwd: repositoryRoot,
  stdio: 'inherit',
});
