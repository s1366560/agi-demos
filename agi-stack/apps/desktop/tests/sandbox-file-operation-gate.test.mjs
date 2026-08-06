import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createSandboxFileOperationGate } = await import(
  'file:///tmp/agistack-desktop-test-dist/src/features/sandbox/sandboxFileOperationGate.js'
);

test('sandbox file operation gate aborts and invalidates old-scope reads and downloads', () => {
  const gate = createSandboxFileOperationGate();
  const read = gate.begin();
  const download = gate.begin();

  assert.equal(read.isCurrent(), true);
  assert.equal(download.isCurrent(), true);
  assert.equal(read.signal.aborted, false);
  assert.equal(download.signal.aborted, false);

  gate.invalidate();

  assert.equal(read.signal.aborted, true);
  assert.equal(download.signal.aborted, true);
  assert.equal(read.isCurrent(), false);
  assert.equal(download.isCurrent(), false);

  const current = gate.begin();
  assert.equal(current.isCurrent(), true);
  current.finish();
  gate.invalidate();
  assert.equal(current.signal.aborted, false);
  assert.equal(current.isCurrent(), false);
});
