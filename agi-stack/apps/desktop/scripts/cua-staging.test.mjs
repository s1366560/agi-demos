import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, openSync, closeSync, readFileSync, readdirSync, rmSync,
  statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { stageCuaMacBundle } from './cua-staging.mjs';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'memstack-cua-staging-'));
  const source = join(root, 'source.app');
  const destination = join(root, 'target', 'Memstack Computer Use.app');
  const executable = 'Contents/MacOS/cua-helper';
  mkdirSync(join(source, 'Contents/MacOS'), { recursive: true });
  writeFileSync(join(source, executable), 'new signed executable');
  return { root, source, destination, executable };
}

test('staging replaces executable inodes without changing an already opened helper', () => {
  const { root, source, destination, executable } = fixture();
  let descriptor;
  try {
    mkdirSync(join(destination, 'Contents/MacOS'), { recursive: true });
    writeFileSync(join(destination, executable), 'previous signed executable');
    writeFileSync(join(destination, 'obsolete-resource'), 'old resource');
    descriptor = openSync(join(destination, executable), 'r');
    const previous = statSync(join(destination, executable));
    stageCuaMacBundle({ source, destination });
    assert.equal(readFileSync(join(destination, executable), 'utf8'), 'new signed executable');
    assert.equal(readFileSync(descriptor, 'utf8'), 'previous signed executable');
    assert.notEqual(statSync(join(destination, executable)).ino, previous.ino);
    assert.deepEqual(readdirSync(destination), ['Contents']);
    assert.deepEqual(readdirSync(join(root, 'target')), ['Memstack Computer Use.app']);
    const first = statSync(join(destination, executable)).ino;
    stageCuaMacBundle({ source, destination });
    assert.notEqual(statSync(join(destination, executable)).ino, first);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(root, { recursive: true, force: true });
  }
});

test('an incomplete source cannot replace the existing helper bundle', () => {
  const { root, source, destination, executable } = fixture();
  try {
    stageCuaMacBundle({ source, destination });
    const previous = statSync(join(destination, executable)).ino;
    assert.throws(() => stageCuaMacBundle({ source: join(root, 'missing.app'), destination }));
    assert.equal(statSync(join(destination, executable)).ino, previous);
    assert.equal(readFileSync(join(destination, executable), 'utf8'), 'new signed executable');
    assert.deepEqual(readdirSync(join(root, 'target')), ['Memstack Computer Use.app']);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
