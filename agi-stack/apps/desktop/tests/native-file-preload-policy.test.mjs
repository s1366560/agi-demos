import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  MAX_PRELOAD_NATIVE_FILE_COUNT,
  MAX_PRELOAD_NATIVE_FILE_BYTES,
  compactNativeFileIngestRequest,
  compactNativeFileIngestResult,
  compactNativeFileOpenResult,
  compactNativeFileSaveRequest,
  validateNativeFileOpenRequest,
  validateNativeFileSaveResult,
} = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/preload/nativeFilePreloadPolicy.js'
);

test('preload save validation enforces 16 MiB and copies only the addressed byte range', () => {
  assert.equal(MAX_PRELOAD_NATIVE_FILE_COUNT, 10);
  assert.equal(MAX_PRELOAD_NATIVE_FILE_BYTES, 16 * 1_048_576);
  const backing = Uint8Array.from([99, 1, 2, 98]);
  const view = new Uint8Array(backing.buffer, 1, 2);
  const compact = compactNativeFileSaveRequest({
    suggestedName: 'report.json',
    mimeType: 'application/json',
    bytes: view,
  });

  assert.deepEqual([...compact.bytes], [1, 2]);
  assert.notEqual(compact.bytes.buffer, backing.buffer);
  assert.equal(compact.bytes.byteOffset, 0);
  assert.equal(compact.bytes.buffer.byteLength, 2);
  assert.equal(Object.isFrozen(compact), true);

  assert.throws(
    () =>
      compactNativeFileSaveRequest({
        suggestedName: 'report.json',
        mimeType: 'application/json',
        bytes: new Uint8Array(MAX_PRELOAD_NATIVE_FILE_BYTES + 1),
      }),
    /native file request exceeds the preload limit/u,
  );
  assert.throws(
    () =>
      compactNativeFileSaveRequest({
        suggestedName: 'report.json',
        mimeType: 'application/json',
        bytes: view,
        path: '/tmp/renderer-controlled',
      }),
    /native file save request is invalid/u,
  );
  for (const invalid of [
    {
      suggestedName: 'x'.repeat(181),
      mimeType: 'application/json',
      bytes: view,
    },
    {
      suggestedName: ' report.json',
      mimeType: 'application/json',
      bytes: view,
    },
    {
      suggestedName: 'report.json',
      mimeType: 'x'.repeat(273),
      bytes: view,
    },
    {
      suggestedName: 'report.json',
      mimeType: ' application/json',
      bytes: view,
    },
  ]) {
    assert.throws(
      () => compactNativeFileSaveRequest(invalid),
      /native file save request is invalid/u,
    );
  }
});

test('preload open validation permits only purpose-derived requests and compact-copies path-free batches', () => {
  assert.deepEqual(validateNativeFileOpenRequest({ purpose: 'skill_package' }), {
    purpose: 'skill_package',
  });
  assert.throws(
    () => validateNativeFileOpenRequest({ purpose: 'attachment', path: '/tmp/file' }),
    /native file open request is invalid/u,
  );
  assert.deepEqual(validateNativeFileSaveResult({ status: 'cancelled' }), {
    status: 'cancelled',
  });
  assert.deepEqual(
    validateNativeFileSaveResult({ status: 'saved', bytesWritten: 12 }),
    { status: 'saved', bytesWritten: 12 },
  );
  assert.throws(
    () => validateNativeFileSaveResult({ status: 'saved', bytesWritten: -1 }),
    /native file save result is invalid/u,
  );

  const backing = Uint8Array.from([0, 3, 4, 0]);
  const result = compactNativeFileOpenResult(
    {
      status: 'selected',
      files: [
        {
          filename: 'report.json',
          mimeType: 'application/json',
          bytes: new Uint8Array(backing.buffer, 1, 2),
        },
      ],
    },
    'attachment',
  );
  assert.deepEqual(result, {
    status: 'selected',
    files: [
      {
        filename: 'report.json',
        mimeType: 'application/json',
        bytes: Uint8Array.from([3, 4]),
      },
    ],
  });
  assert.notEqual(result.files[0].bytes.buffer, backing.buffer);
  assert.equal(result.files[0].bytes.buffer.byteLength, 2);
  assert.deepEqual(compactNativeFileOpenResult({ status: 'cancelled' }, 'attachment'), {
    status: 'cancelled',
  });

  assert.throws(
    () =>
      compactNativeFileOpenResult(
        {
          status: 'selected',
          files: [
            {
              filename: 'one.zip',
              mimeType: 'application/zip',
              bytes: new Uint8Array(),
            },
            {
              filename: 'two.zip',
              mimeType: 'application/zip',
              bytes: new Uint8Array(),
            },
          ],
        },
        'skill_package',
      ),
    /native file open result is invalid/u,
  );
});

test('preload ingest accepts only exact attachment batches and compact-copies request and result bytes', () => {
  const backing = Uint8Array.from([9, 4, 5, 8]);
  const request = compactNativeFileIngestRequest({
    purpose: 'attachment',
    files: [
      {
        filename: 'drop.txt',
        mimeType: 'text/plain',
        bytes: new Uint8Array(backing.buffer, 1, 2),
      },
    ],
  });
  assert.deepEqual(request, {
    purpose: 'attachment',
    files: [
      {
        filename: 'drop.txt',
        mimeType: 'text/plain',
        bytes: Uint8Array.from([4, 5]),
      },
    ],
  });
  assert.notEqual(request.files[0].bytes.buffer, backing.buffer);

  const result = compactNativeFileIngestResult({
    status: 'ingested',
    files: request.files,
  });
  assert.deepEqual(result, { status: 'ingested', files: request.files });
  assert.notEqual(result.files[0].bytes.buffer, request.files[0].bytes.buffer);

  for (const invalid of [
    { purpose: 'skill_package', files: [] },
    { purpose: 'attachment', files: [] },
    {
      purpose: 'attachment',
      files: [{ filename: 'drop.txt', mimeType: 'text/plain', bytes: new Uint8Array(), extra: true }],
    },
    {
      purpose: 'attachment',
      files: Array.from({ length: MAX_PRELOAD_NATIVE_FILE_COUNT + 1 }, (_, index) => ({
        filename: `drop-${index}.txt`,
        mimeType: 'text/plain',
        bytes: new Uint8Array(),
      })),
    },
    {
      purpose: 'attachment',
      files: [
        {
          filename: 'one.bin',
          mimeType: 'application/octet-stream',
          bytes: new Uint8Array(MAX_PRELOAD_NATIVE_FILE_BYTES),
        },
        {
          filename: 'two.bin',
          mimeType: 'application/octet-stream',
          bytes: Uint8Array.from([1]),
        },
      ],
    },
  ]) {
    assert.throws(
      () => compactNativeFileIngestRequest(invalid),
      /native file ingest request (?:is invalid|exceeds the preload limit)/u,
    );
  }
});
