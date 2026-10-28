import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

/** Obtain exact-version official Node binaries; validate every archive before extracting. */
export async function universalNode(version, directory, destination) {
  if (!/^\d+\.\d+\.\d+$/u.test(version)) throw new Error('invalid Node release version');
  await mkdir(directory, { recursive: true });
  const base = `https://nodejs.org/dist/v${version}`;
  const checksums = await fetch(`${base}/SHASUMS256.txt`, { signal: AbortSignal.timeout(30_000) });
  if (!checksums.ok) throw new Error('cannot obtain official Node release checksums');
  const sums = new Map((await checksums.text()).trim().split('\n').map(line => { const [hash, name] = line.trim().split(/\s+/u); return [name, hash]; }));
  const binaries = [];
  for (const architecture of ['arm64', 'x64']) {
    const name = `node-v${version}-darwin-${architecture}`;
    const archive = `${name}.tar.gz`;
    const expected = sums.get(archive);
    if (!expected || !/^[a-f0-9]{64}$/u.test(expected)) throw new Error('Node archive checksum is absent');
    const archivePath = join(directory, archive);
    let bytes;
    try { bytes = await readFile(archivePath); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (!bytes || createHash('sha256').update(bytes).digest('hex') !== expected) {
      const response = await fetch(`${base}/${archive}`, { signal: AbortSignal.timeout(120_000) });
      if (!response.ok) throw new Error(`cannot download Node ${architecture}`);
      bytes = Buffer.from(await response.arrayBuffer());
      if (bytes.length > 100_000_000 || createHash('sha256').update(bytes).digest('hex') !== expected) throw new Error('Node archive checksum mismatch');
      await writeFile(archivePath, bytes, { mode: 0o600 });
    }
    const output = join(directory, architecture);
    await mkdir(output, { recursive: true });
    // Extract only known members from the verified archive, never arbitrary paths.
    execFileSync('/usr/bin/tar', ['-xzf', archivePath, '-C', output, '--strip-components=1', `${name}/bin/node`, `${name}/LICENSE`], { timeout: 30_000 });
    binaries.push(join(output, 'bin/node'));
  }
  execFileSync('/usr/bin/lipo', ['-create', ...binaries, '-output', destination], { timeout: 30_000 });
  const architectures = execFileSync('/usr/bin/lipo', ['-archs', destination], { encoding: 'utf8' }).trim().split(/\s+/u);
  if (!architectures.includes('arm64') || !architectures.includes('x86_64')) throw new Error('Node universal binary is incomplete');
  await writeFile(join(directory, 'NODE_LICENSE'), await readFile(join(directory, 'arm64/LICENSE')));
  return join(directory, 'NODE_LICENSE');
}
