import { chmod, copyFile, cp, mkdtemp, mkdir, readFile, realpath, rename, rm, writeFile, stat } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { universalNode } from './cua-repl-node.mjs';

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageRoot = resolve(desktopRoot, '../../packages/cua-repl');
const marker = '.memstack-cua-repl';

export async function stageCuaRepl({ destination = join(desktopRoot, 'build/cua-repl'), nodePath = process.env.MEMSTACK_CUA_NODE ?? process.execPath, universal = false } = {}) {
  const sourceNode = await realpath(nodePath);
  const runtime = JSON.parse(execFileSync(sourceNode, ['-p', 'JSON.stringify({version:process.versions.node,electron:process.versions.electron??null,platform:process.platform,arch:process.arch})'],
    { encoding: 'utf8', timeout: 10_000, env: { PATH: process.env.PATH ?? '' } }));
  const [major, minor] = runtime.version.split('.').map(Number);
  if (runtime.electron || major < 22 || (major === 22 && minor < 15)) throw new Error('CUA REPL requires a real Node.js runtime version 22.15 or newer');
  if (runtime.platform !== process.platform || runtime.arch !== process.arch) throw new Error('CUA REPL runtime must match the staging host platform and architecture');
  const require = createRequire(join(packageRoot, 'package.json'));
  const typescriptRoot = dirname(require.resolve('typescript/package.json'));
  const dependency = JSON.parse(await readFile(join(typescriptRoot, 'package.json'), 'utf8'));
  const packageJson = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
  if (dependency.version !== packageJson.dependencies.typescript) throw new Error('installed TypeScript does not match the pinned CUA REPL dependency');
  await mkdir(dirname(destination), { recursive: true });
  const temporary = await mkdtemp(join(dirname(destination), '.cua-repl-stage-'));
  const backup = `${temporary}-previous`;
  let moved = false;
  try {
    await mkdir(join(temporary, 'bin'));
    await copyFile(sourceNode, join(temporary, 'bin', process.platform === 'win32' ? 'node.exe' : 'node'));
    if (universal && process.platform === 'darwin') {
      const license = await universalNode(runtime.version, join(desktopRoot, 'build/cua-node-downloads', runtime.version), join(temporary, 'bin/node'));
      await copyFile(license, join(temporary, 'NODE_LICENSE'));
    }
    if (process.platform !== 'win32') await chmod(join(temporary, 'bin/node'), 0o755);
    await cp(join(packageRoot, 'src'), join(temporary, 'src'), { recursive: true, dereference: true });
    await cp(typescriptRoot, join(temporary, 'node_modules/typescript'), { recursive: true, dereference: true });
    await copyFile(join(packageRoot, 'package.json'), join(temporary, 'package.json'));
    await writeFile(join(temporary, marker), 'MemStack managed CUA REPL runtime\n', { mode: 0o600 });
    try {
      await readFile(join(destination, marker));
      await rename(destination, backup); moved = true;
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      try { await stat(destination); throw new Error('refusing to replace an unmanaged CUA REPL directory'); }
      catch (missing) { if (missing.code !== 'ENOENT') throw missing; }
    }
    await rename(temporary, destination);
    if (moved) await rm(backup, { recursive: true, force: true });
    return { destination, version: runtime.version, architecture: runtime.arch };
  } catch (error) {
    await rm(temporary, { recursive: true, force: true });
    if (moved) await rename(backup, destination);
    throw error;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await stageCuaRepl({ universal: process.argv.includes('--universal') });
  console.log(`Staged CUA REPL with Node ${result.version} (${result.architecture})`);
}
