import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';

const {
  MAX_RENDERER_NATIVE_FILE_COUNT,
  MAX_RENDERER_NATIVE_FILE_BYTES,
  ingestFilesWithDesktopBridge,
  openFilesWithDesktopDialog,
  saveBlobWithDesktopDialog,
} = await import(
  'file:///tmp/agistack-desktop-test-dist/src/features/runtime/nativeFileBridge.js'
);

const originalWindow = globalThis.window;
afterEach(() => {
  globalThis.window = originalWindow;
});

test('renderer save bridge sends only suggested filename, declared MIME, and bounded bytes', async () => {
  let request = null;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      files: {
        async save(input) {
          request = input;
          return { status: 'saved', bytesWritten: input.bytes.byteLength };
        },
      },
    },
  };

  const result = await saveBlobWithDesktopDialog({
    suggestedName: 'conversation.md',
    mimeType: 'text/markdown;charset=utf-8',
    blob: new Blob(['hello'], { type: 'text/markdown' }),
  });

  assert.deepEqual(result, { status: 'saved', bytesWritten: 5 });
  assert.deepEqual(Object.keys(request).sort(), ['bytes', 'mimeType', 'suggestedName']);
  assert.equal(request.suggestedName, 'conversation.md');
  assert.equal(request.mimeType, 'text/markdown;charset=utf-8');
  assert.deepEqual([...request.bytes], [104, 101, 108, 108, 111]);
  assert.equal('path' in request, false);
  assert.equal(MAX_RENDERER_NATIVE_FILE_BYTES, 16 * 1_048_576);
  assert.equal(MAX_RENDERER_NATIVE_FILE_COUNT, 10);
});

test('renderer save bridge preserves cancellation and rejects oversized blobs before IPC', async () => {
  let saveCalls = 0;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      files: {
        async save() {
          saveCalls += 1;
          return { status: 'cancelled' };
        },
      },
    },
  };

  assert.deepEqual(
    await saveBlobWithDesktopDialog({
      suggestedName: 'cancelled.json',
      mimeType: 'application/json',
      blob: new Blob(['{}'], { type: 'application/json' }),
    }),
    { status: 'cancelled' },
  );
  await assert.rejects(
    saveBlobWithDesktopDialog({
      suggestedName: 'oversized.bin',
      mimeType: 'application/octet-stream',
      blob: new Blob([new Uint8Array(MAX_RENDERER_NATIVE_FILE_BYTES + 1)]),
    }),
    /native_file_write_limit_exceeded/u,
  );
  assert.equal(saveCalls, 1);
});

test('renderer file helpers fail closed when the named native bridge is unavailable', async () => {
  globalThis.window = { __MEMSTACK_DESKTOP__: { runtime: 'electron' } };
  await assert.rejects(
    saveBlobWithDesktopDialog({
      suggestedName: 'artifact.txt',
      mimeType: 'text/plain',
      blob: new Blob(['artifact']),
    }),
    /native_file_bridge_unavailable/u,
  );
  await assert.rejects(
    openFilesWithDesktopDialog('attachment'),
    /native_file_bridge_unavailable/u,
  );
  await assert.rejects(
    ingestFilesWithDesktopBridge([new File(['x'], 'x.txt', { type: 'text/plain' })]),
    /native_file_bridge_unavailable/u,
  );
});

test('renderer import bridge submits only an allowlisted purpose and returns browser Files', async () => {
  let request = null;
  const bytes = Uint8Array.from([1, 2]);
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      files: {
        async open(input) {
          request = input;
          return {
            status: 'selected',
            files: [
              {
                filename: 'attachment.txt',
                mimeType: 'text/plain',
                bytes,
              },
            ],
          };
        },
      },
    },
  };

  const result = await openFilesWithDesktopDialog('attachment');
  assert.deepEqual(request, { purpose: 'attachment' });
  assert.equal('path' in request, false);
  assert.equal(result.status, 'selected');
  assert.equal(result.files.length, 1);
  assert.equal(result.files[0] instanceof File, true);
  assert.equal(result.files[0].name, 'attachment.txt');
  assert.equal(result.files[0].type, 'text/plain');
  assert.deepEqual([...new Uint8Array(await result.files[0].arrayBuffer())], [1, 2]);
});

test('renderer import bridge preserves picker cancellation without manufacturing files', async () => {
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      files: {
        async open() {
          return { status: 'cancelled' };
        },
      },
    },
  };
  assert.deepEqual(await openFilesWithDesktopDialog('skill_package'), {
    status: 'cancelled',
  });
});

test('renderer dropped-file ingest sends an exact bounded byte contract and recreates trusted Files', async () => {
  let request = null;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      files: {
        async ingest(input) {
          request = input;
          return { status: 'ingested', files: input.files };
        },
      },
    },
  };
  const files = [
    new File(['hello'], 'drop.txt', { type: 'text/plain', lastModified: 123 }),
    new File([Uint8Array.from([1, 2])], 'photo.png'),
  ];
  const ingested = await ingestFilesWithDesktopBridge(files);

  assert.deepEqual(Object.keys(request).sort(), ['files', 'purpose']);
  assert.equal(request.purpose, 'attachment');
  assert.equal(request.files.length, 2);
  assert.deepEqual(Object.keys(request.files[0]).sort(), ['bytes', 'filename', 'mimeType']);
  assert.equal(request.files[0].filename, 'drop.txt');
  assert.equal(request.files[0].mimeType, 'text/plain');
  assert.deepEqual([...request.files[0].bytes], [104, 101, 108, 108, 111]);
  assert.equal(request.files[1].mimeType, 'application/octet-stream');
  assert.equal(request.files.some((file) => 'path' in file), false);
  assert.equal(ingested.every((file) => file instanceof File), true);
  assert.deepEqual(ingested.map((file) => file.name), ['drop.txt', 'photo.png']);
});

test('renderer dropped-file ingest rejects oversized or over-count batches before IPC', async () => {
  let calls = 0;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      files: {
        async ingest() {
          calls += 1;
          return { status: 'ingested', files: [] };
        },
      },
    },
  };
  await assert.rejects(
    ingestFilesWithDesktopBridge(
      Array.from(
        { length: MAX_RENDERER_NATIVE_FILE_COUNT + 1 },
        (_, index) => new File([], `file-${index}.txt`, { type: 'text/plain' }),
      ),
    ),
    /native_file_ingest_count_exceeded/u,
  );
  await assert.rejects(
    ingestFilesWithDesktopBridge([
      new File(
        [new Uint8Array(MAX_RENDERER_NATIVE_FILE_BYTES)],
        'one.bin',
        { type: 'application/octet-stream' },
      ),
      new File([Uint8Array.from([1])], 'two.bin', {
        type: 'application/octet-stream',
      }),
    ]),
    /native_file_ingest_limit_exceeded/u,
  );
  assert.equal(calls, 0);
});
