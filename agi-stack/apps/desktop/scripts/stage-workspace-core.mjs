import { createHash } from 'node:crypto';
import { chmod, copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const executable =
  process.platform === 'win32' ? 'memstack-workspace-core.exe' : 'memstack-workspace-core';
const source = resolve(
  desktopRoot,
  '../../../.cache/avernet-bcs/target/release',
  executable,
);
const destinationDirectory = resolve(desktopRoot, 'build/workspace-core');
const destination = resolve(destinationDirectory, executable);

await mkdir(destinationDirectory, { recursive: true });
await copyFile(source, destination);
if (process.platform !== 'win32') await chmod(destination, 0o755);
const digest = createHash('sha256').update(await readFile(destination)).digest('hex');
await writeFile(
  resolve(destinationDirectory, 'SHA256SUMS'),
  `${digest}  ${executable}\n`,
  'utf8',
);
