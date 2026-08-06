import assert from 'node:assert/strict';
import {
  lstat,
  mkdtemp,
  readFile,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, test } from 'node:test';

const {
  MAX_NATIVE_FILE_COUNT,
  MAX_NATIVE_FILE_IMPORT_BYTES,
  MAX_NATIVE_FILE_WRITE_BYTES,
  ingestNativeFiles,
  isTrustedNativeFileFrameUrl,
  nativeFileOpenDialogFilters,
  nativeFileSaveDialogFilters,
  openNativeFileWithDialog,
  readBoundedNativeFileHandle,
  readNativeFileNoFollow,
  saveNativeFileWithDialog,
  validateNativeFileSaveRequest,
  writeNativeFileAtomically,
} = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/nativeFileDialogPolicy.js'
);

const temporaryDirectories = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) =>
      rm(directory, { recursive: true, force: true }),
    ),
  );
});

function createAuthority(overrides = {}) {
  return {
    async chooseSaveTarget() {
      return null;
    },
    async chooseOpenTargets() {
      return null;
    },
    async readFileNoFollow() {
      return new Uint8Array();
    },
    async writeFileAtomically() {},
    ...overrides,
  };
}

async function createTemporaryDirectory() {
  const directory = await mkdtemp(join(tmpdir(), 'agistack-native-file-test-'));
  temporaryDirectories.push(directory);
  return directory;
}

test('native file limits are a single 16 MiB boundary', () => {
  assert.equal(MAX_NATIVE_FILE_COUNT, 10);
  assert.equal(MAX_NATIVE_FILE_WRITE_BYTES, 16 * 1_048_576);
  assert.equal(MAX_NATIVE_FILE_IMPORT_BYTES, 16 * 1_048_576);
});

test('attachment picker allowlist covers production source, config, data, and log evidence', () => {
  const [filter] = nativeFileOpenDialogFilters('attachment');
  for (const extension of [
    'log',
    'jsonl',
    'py',
    'rs',
    'sh',
    'sql',
    'toml',
    'ts',
    'tsx',
  ]) {
    assert.equal(filter.extensions.includes(extension), true, extension);
  }
});

test('native save accepts only a safe leaf filename, declared MIME, and bounded Uint8Array', () => {
  const bytes = Uint8Array.from([1, 2, 3]);
  assert.deepEqual(
    validateNativeFileSaveRequest({
      suggestedName: 'conversation.md',
      mimeType: 'text/markdown;charset=utf-8',
      bytes,
    }),
    {
      suggestedName: 'conversation.md',
      mimeType: 'text/markdown;charset=utf-8',
      bytes,
    },
  );
  for (const suggestedName of [
    '../conversation.md',
    '/tmp/conversation.md',
    'folder\\conversation.md',
    'conversation.md.',
    'CON.txt',
    'bad\u0000name.txt',
  ]) {
    assert.throws(
      () =>
        validateNativeFileSaveRequest({
          suggestedName,
          mimeType: 'text/plain',
          bytes,
        }),
      /native suggested filename is invalid/u,
    );
  }
  assert.throws(
    () =>
      validateNativeFileSaveRequest({
        suggestedName: 'conversation.md',
        mimeType: 'invalid mime',
        bytes,
      }),
    /native declared MIME type is invalid/u,
  );
  assert.throws(
    () =>
      validateNativeFileSaveRequest({
        suggestedName: 'conversation.md',
        mimeType: 'text/markdown',
        bytes: new Uint16Array([1]),
      }),
    /native file bytes are invalid/u,
  );
  assert.throws(
    () =>
      validateNativeFileSaveRequest(
        {
          suggestedName: 'conversation.md',
          mimeType: 'text/markdown',
          bytes,
        },
        2,
      ),
    /file exceeds the native write limit/u,
  );
});

test('native save writes only through the atomic authority selected by the dialog', async () => {
  const selectedPath = '/tmp/user-selected/conversation.md';
  const calls = [];
  const bytes = Uint8Array.from([4, 5, 6]);
  const authority = createAuthority({
    async chooseSaveTarget(input) {
      calls.push(['choose', input]);
      return selectedPath;
    },
    async writeFileAtomically(path, value) {
      calls.push(['write-atomic', path, [...value]]);
    },
  });

  const result = await saveNativeFileWithDialog(
    {
      suggestedName: 'conversation.md',
      mimeType: 'text/markdown;charset=utf-8',
      bytes,
    },
    authority,
  );

  assert.deepEqual(result, { status: 'saved', bytesWritten: 3 });
  assert.equal('path' in result, false);
  assert.deepEqual(calls, [
    [
      'choose',
      {
        suggestedName: 'conversation.md',
        mimeType: 'text/markdown;charset=utf-8',
        filters: nativeFileSaveDialogFilters(
          'conversation.md',
          'text/markdown;charset=utf-8',
        ),
      },
    ],
    ['write-atomic', selectedPath, [4, 5, 6]],
  ]);
});

test('native save cancellation does not write', async () => {
  let writes = 0;
  const result = await saveNativeFileWithDialog(
    {
      suggestedName: 'artifact.pdf',
      mimeType: 'application/pdf',
      bytes: Uint8Array.from([0x25, 0x50, 0x44, 0x46]),
    },
    createAuthority({
      async writeFileAtomically() {
        writes += 1;
      },
    }),
  );
  assert.deepEqual(result, { status: 'cancelled' });
  assert.equal(writes, 0);
});

test('atomic native save replaces a selected symlink without writing through it', async () => {
  const directory = await createTemporaryDirectory();
  const sentinelPath = join(directory, 'sentinel.txt');
  const selectedPath = join(directory, 'selected.txt');
  await writeFile(sentinelPath, 'sentinel', { mode: 0o600 });
  await symlink(sentinelPath, selectedPath);

  await writeNativeFileAtomically(selectedPath, Uint8Array.from([115, 97, 102, 101]));

  assert.equal(await readFile(sentinelPath, 'utf8'), 'sentinel');
  assert.equal(await readFile(selectedPath, 'utf8'), 'safe');
  const metadata = await lstat(selectedPath);
  assert.equal(metadata.isFile(), true);
  assert.equal(metadata.isSymbolicLink(), false);
  assert.equal(metadata.mode & 0o777, 0o600);
});

test('native attachment import is purpose-derived, multi-select, bounded as one batch, and path-free', async () => {
  const selectedPaths = [
    '/tmp/user-selected/report.md',
    '/tmp/user-selected/photo.png',
  ];
  const bytesByPath = new Map([
    [selectedPaths[0], Uint8Array.from([7, 8, 9])],
    [selectedPaths[1], Uint8Array.from([10, 11])],
  ]);
  const calls = [];
  const result = await openNativeFileWithDialog(
    { purpose: 'attachment' },
    createAuthority({
      async chooseOpenTargets(input) {
        calls.push(['choose', input]);
        return selectedPaths;
      },
      async readFileNoFollow(path, maxBytes) {
        calls.push(['read-nofollow', path, maxBytes]);
        return bytesByPath.get(path);
      },
    }),
  );

  assert.deepEqual(result, {
    status: 'selected',
    files: [
      {
        filename: 'report.md',
        mimeType: 'text/markdown',
        bytes: Uint8Array.from([7, 8, 9]),
      },
      {
        filename: 'photo.png',
        mimeType: 'image/png',
        bytes: Uint8Array.from([10, 11]),
      },
    ],
  });
  assert.equal('path' in result, false);
  assert.equal(result.files.some((file) => 'path' in file), false);
  assert.deepEqual(calls, [
    [
      'choose',
      {
        purpose: 'attachment',
        allowMultiple: true,
        filters: nativeFileOpenDialogFilters('attachment'),
      },
    ],
    ['read-nofollow', selectedPaths[0], MAX_NATIVE_FILE_IMPORT_BYTES],
    ['read-nofollow', selectedPaths[1], MAX_NATIVE_FILE_IMPORT_BYTES - 3],
  ]);

  let forbiddenReads = 0;
  await assert.rejects(
    openNativeFileWithDialog(
      { purpose: 'attachment' },
      createAuthority({
        async chooseOpenTargets() {
          return ['/tmp/user-selected/program.exe'];
        },
        async readFileNoFollow() {
          forbiddenReads += 1;
          return new Uint8Array();
        },
      }),
    ),
    /selected import file extension is not allowed/u,
  );
  assert.equal(forbiddenReads, 0);

  await assert.rejects(
    openNativeFileWithDialog(
      { purpose: 'attachment', path: '/tmp/renderer-selected' },
      createAuthority(),
    ),
    /native file open request is invalid/u,
  );
  await assert.rejects(
    openNativeFileWithDialog(
      { purpose: 'unsupported' },
      createAuthority(),
    ),
    /native file open request is invalid/u,
  );

  await assert.rejects(
    openNativeFileWithDialog(
      { purpose: 'attachment' },
      createAuthority({
        async chooseOpenTargets() {
          return Array.from(
            { length: MAX_NATIVE_FILE_COUNT + 1 },
            (_, index) => `/tmp/user-selected/file-${index}.txt`,
          );
        },
      }),
    ),
    /native file selection count is invalid/u,
  );

  let aggregateReads = 0;
  await assert.rejects(
    openNativeFileWithDialog(
      { purpose: 'attachment' },
      createAuthority({
        async chooseOpenTargets() {
          return ['/tmp/user-selected/one.txt', '/tmp/user-selected/two.txt'];
        },
        async readFileNoFollow(_path, maxBytes) {
          aggregateReads += 1;
          return new Uint8Array(maxBytes + 1);
        },
      }),
    ),
    /native import limit/u,
  );
  assert.equal(aggregateReads, 1);
});

test('native skill package import permits exactly one ZIP and never returns a selected path', async () => {
  const calls = [];
  const result = await openNativeFileWithDialog(
    { purpose: 'skill_package' },
    createAuthority({
      async chooseOpenTargets(input) {
        calls.push(input);
        return ['/tmp/user-selected/release-readiness.zip'];
      },
      async readFileNoFollow() {
        return Uint8Array.from([0x50, 0x4b, 0x03, 0x04]);
      },
    }),
  );
  assert.deepEqual(result, {
    status: 'selected',
    files: [
      {
        filename: 'release-readiness.zip',
        mimeType: 'application/zip',
        bytes: Uint8Array.from([0x50, 0x4b, 0x03, 0x04]),
      },
    ],
  });
  assert.deepEqual(calls, [
    {
      purpose: 'skill_package',
      allowMultiple: false,
      filters: nativeFileOpenDialogFilters('skill_package'),
    },
  ]);

  for (const selectedTargets of [
    [
      '/tmp/user-selected/one.zip',
      '/tmp/user-selected/two.zip',
    ],
    ['/tmp/user-selected/not-a-package.json'],
  ]) {
    await assert.rejects(
      openNativeFileWithDialog(
        { purpose: 'skill_package' },
        createAuthority({
          async chooseOpenTargets() {
            return selectedTargets;
          },
        }),
      ),
      /selection count is invalid|extension is not allowed/u,
    );
  }

  await assert.rejects(
    openNativeFileWithDialog(
      { purpose: 'skill_package' },
      createAuthority({
        async chooseOpenTargets() {
          return ['/tmp/user-selected/fake.zip'];
        },
        async readFileNoFollow() {
          return Uint8Array.from([0x7b, 0x7d]);
        },
      }),
    ),
    /selected Skill package is not a ZIP archive/u,
  );
});

test('native dropped-file ingest accepts only exact bounded attachment batches and compact-copies bytes', () => {
  const backing = Uint8Array.from([99, 1, 2, 98]);
  const result = ingestNativeFiles({
    purpose: 'attachment',
    files: [
      {
        filename: 'worker.log',
        mimeType: 'text/plain',
        bytes: new Uint8Array(backing.buffer, 1, 2),
      },
    ],
  });
  assert.deepEqual(result, {
    status: 'ingested',
    files: [
      {
        filename: 'worker.log',
        mimeType: 'text/plain',
        bytes: Uint8Array.from([1, 2]),
      },
    ],
  });
  assert.notEqual(result.files[0].bytes.buffer, backing.buffer);
  assert.equal(result.files.some((file) => 'path' in file), false);

  for (const invalid of [
    { purpose: 'skill_package', files: [] },
    { purpose: 'attachment', files: [] },
    {
      purpose: 'attachment',
      files: [{ filename: '../secret.txt', mimeType: 'text/plain', bytes: new Uint8Array() }],
    },
    {
      purpose: 'attachment',
      files: [{ filename: 'program.exe', mimeType: 'application/octet-stream', bytes: new Uint8Array() }],
    },
    {
      purpose: 'attachment',
      files: [{ filename: 'secret.txt', mimeType: 'text/plain', bytes: new Uint8Array(), path: '/tmp/secret.txt' }],
    },
    {
      purpose: 'attachment',
      files: Array.from({ length: MAX_NATIVE_FILE_COUNT + 1 }, (_, index) => ({
        filename: `file-${index}.txt`,
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
          bytes: new Uint8Array(MAX_NATIVE_FILE_IMPORT_BYTES),
        },
        {
          filename: 'two.bin',
          mimeType: 'application/octet-stream',
          bytes: Uint8Array.from([1]),
        },
      ],
    },
  ]) {
    assert.throws(() => ingestNativeFiles(invalid), /native file ingest/u);
  }
});

test('native nofollow reader rejects symlinks and never performs an unbounded read', async () => {
  const directory = await createTemporaryDirectory();
  const targetPath = join(directory, 'target.txt');
  const symlinkPath = join(directory, 'target-link.txt');
  await writeFile(targetPath, 'secret', { mode: 0o600 });
  await symlink(targetPath, symlinkPath);
  await assert.rejects(readNativeFileNoFollow(symlinkPath), {
    code: 'ELOOP',
  });

  let observedBufferSize = 0;
  let closed = false;
  const overflowingHandle = {
    async stat() {
      return { isFile: true, size: 2 };
    },
    async read(buffer, offset, length) {
      observedBufferSize = buffer.byteLength;
      buffer.fill(1, offset, offset + length);
      return length;
    },
    async close() {
      closed = true;
    },
  };
  await assert.rejects(
    readBoundedNativeFileHandle(overflowingHandle, 2),
    /file exceeds the native import limit/u,
  );
  assert.equal(observedBufferSize, 3);
  assert.equal(closed, true);
});

test('native file frame URL trust is exact for the configured dev origin and production app origin', () => {
  const developmentUrl = new URL('http://127.0.0.1:5173/index.html');
  assert.equal(
    isTrustedNativeFileFrameUrl(
      'http://127.0.0.1:5173/#/tenant/demo',
      developmentUrl,
    ),
    true,
  );
  assert.equal(
    isTrustedNativeFileFrameUrl('http://127.0.0.1:5174/', developmentUrl),
    false,
  );
  assert.equal(
    isTrustedNativeFileFrameUrl('agistack://app/index.html#/workspace/demo', null),
    true,
  );
  for (const frameUrl of [
    'agistack://evil/index.html',
    'https://app/index.html',
    'agistack://user@app/index.html',
    'not a URL',
  ]) {
    assert.equal(isTrustedNativeFileFrameUrl(frameUrl, null), false);
  }
});
