import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const readSource = (path) =>
  readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');

const mainSource = readSource('electron/main/index.ts');
const policySource = readSource('electron/main/nativeFileDialogPolicy.ts');
const preloadSource = readSource('electron/preload/index.ts');
const rendererTypes = readSource('src/vite-env.d.ts');
const bridgeSource = readSource('src/features/runtime/nativeFileBridge.ts');
const conversationSource = readSource('src/features/chat/ConversationExportMenu.tsx');
const canvasSource = readSource('src/features/chat/LiveArtifactCanvas.tsx');
const previewSource = readSource('src/features/chat/ArtifactPreviewSurface.tsx');
const sandboxSource = readSource('src/features/sandbox/SessionSandboxTools.tsx');
const sandboxBrowserSource = readSource('src/features/sandbox/SandboxFileBrowser.tsx');

function sliceBetween(source, start, end) {
  const startIndex = source.indexOf(start);
  assert.notEqual(startIndex, -1, `missing source marker: ${start}`);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.notEqual(endIndex, -1, `missing source marker: ${end}`);
  return source.slice(startIndex, endIndex);
}

test('Electron authorizes only the trusted main frame and uses bounded nofollow/atomic file IO', () => {
  assert.equal(mainSource.includes("const NATIVE_FILE_SAVE_CHANNEL = 'agistack:native-file-save';"), true);
  assert.equal(mainSource.includes("const NATIVE_FILE_OPEN_CHANNEL = 'agistack:native-file-open';"), true);
  assert.equal(mainSource.includes("const NATIVE_FILE_INGEST_CHANNEL = 'agistack:native-file-ingest';"), true);
  assert.equal(mainSource.includes('dialog.showSaveDialog(ownerWindow, {'), true);
  assert.equal(mainSource.includes('dialog.showOpenDialog(ownerWindow, {'), true);
  assert.equal(mainSource.includes('ipcMain.handle(NATIVE_FILE_SAVE_CHANNEL, handleNativeFileSave);'), true);
  assert.equal(mainSource.includes('ipcMain.handle(NATIVE_FILE_OPEN_CHANNEL, handleNativeFileOpen);'), true);
  assert.equal(mainSource.includes('ipcMain.handle(NATIVE_FILE_INGEST_CHANNEL, handleNativeFileIngest);'), true);
  const authoritySource = sliceBetween(
    mainSource,
    'function nativeFileDialogAuthority(',
    'async function handleNativeFileSave(',
  );
  assert.equal(
    authoritySource.includes('event.senderFrame !== ownerWindow.webContents.mainFrame'),
    true,
  );
  assert.equal(
    authoritySource.includes(
      '!isTrustedNativeFileFrameUrl(event.senderFrame.url, rendererDevelopmentUrl())',
    ),
    true,
  );
  assert.equal(authoritySource.includes('readFileNoFollow: readNativeFileNoFollow'), true);
  assert.equal(authoritySource.includes('writeFileAtomically: writeNativeFileAtomically'), true);

  assert.equal(policySource.includes('export const MAX_NATIVE_FILE_BYTES = 16 * 1_048_576;'), true);
  assert.equal(policySource.includes('new Uint8Array(maxBytes + 1)'), true);
  assert.equal(policySource.includes('await handle.stat()'), true);
  assert.equal(
    policySource.includes('constants.O_RDONLY | constants.O_NOFOLLOW'),
    true,
  );
  assert.equal(policySource.includes("await open(tempPath, 'wx', 0o600)"), true);
  assert.equal(policySource.includes('await handle.sync()'), true);
  assert.equal(policySource.includes('await rename(tempPath, path)'), true);
  assert.equal(policySource.includes('selected import file extension is not allowed'), true);
  assert.equal(policySource.includes('request.path'), false);
  assert.equal(policySource.includes('input.path'), false);
});

test('preload validates and compact-copies the named file bridge without arbitrary paths', () => {
  assert.equal(preloadSource.includes('const fileBridge = Object.freeze({'), true);
  assert.equal(preloadSource.includes('save: saveNativeFile'), true);
  assert.equal(preloadSource.includes('open: openNativeFile'), true);
  assert.equal(preloadSource.includes('ingest: ingestNativeFile'), true);
  assert.equal(preloadSource.includes('files: fileBridge'), true);
  const saveSource = sliceBetween(preloadSource, 'function saveNativeFile(', 'function openNativeFile(');
  assert.equal(saveSource.includes('compactNativeFileSaveRequest(request)'), true);
  assert.equal(saveSource.includes('validateNativeFileSaveResult(result)'), true);
  assert.equal(saveSource.includes('path'), false);
  const openSource = sliceBetween(preloadSource, 'function openNativeFile(', 'const fileBridge');
  assert.equal(openSource.includes('validateNativeFileOpenRequest(request)'), true);
  assert.equal(
    openSource.includes('compactNativeFileOpenResult(result, validatedRequest.purpose)'),
    true,
  );
  assert.equal(openSource.includes('path'), false);
  assert.equal(rendererTypes.includes('files?: Readonly<{'), true);
  assert.equal(
    rendererTypes.includes('save(request: DesktopFileSaveRequest): Promise<DesktopFileSaveResult>;'),
    true,
  );
  assert.equal(
    rendererTypes.includes('open(request: DesktopFileOpenRequest): Promise<DesktopFileOpenResult>;'),
    true,
  );
  assert.equal(
    rendererTypes.includes('ingest(request: DesktopFileIngestRequest): Promise<DesktopFileIngestResult>;'),
    true,
  );
});

test('production file helper fails closed without a native bridge and has no DOM fallback', () => {
  assert.match(bridgeSource, /native_file_bridge_unavailable/u);
  assert.match(bridgeSource, /window\.__MEMSTACK_DESKTOP__\?\.files\?\.save/u);
  assert.match(bridgeSource, /window\.__MEMSTACK_DESKTOP__\?\.files\?\.open/u);
  assert.doesNotMatch(bridgeSource, /createObjectURL|document\.createElement|anchor|download\s*=/u);
});

test('conversation, artifact, preview fallback, and sandbox downloads use the native bridge', () => {
  assert.match(conversationSource, /saveBlobWithDesktopDialog/u);
  assert.match(conversationSource, /outputPdf\('blob'\)/u);
  assert.doesNotMatch(conversationSource, /createObjectURL|createElement\('a'\)|\.save\(\)/u);

  assert.match(canvasSource, /saveBlobWithDesktopDialog/u);
  assert.doesNotMatch(canvasSource, /createObjectURL|createElement\('a'\)|anchor\.download/u);

  assert.match(previewSource, /saveBlobWithDesktopDialog/u);
  assert.doesNotMatch(previewSource, /anchor\.download|createElement\('a'\)/u);

  assert.match(sandboxSource, /saveBlobWithDesktopDialog/u);
  assert.doesNotMatch(sandboxSource, /createObjectURL|createElement\('a'\)|anchor\.download/u);
  assert.match(sandboxBrowserSource, /await onDownloadFile\?\.\(result\.value\)/u);
});

test('all success-reporting download journeys branch explicitly on native cancellation', () => {
  const conversationExport = sliceBetween(
    conversationSource,
    'const exportConversation = async',
    'return (',
  );
  assert.equal(conversationExport.includes("if (result.status === 'cancelled') return;"), true);

  const activeDownload = sliceBetween(
    canvasSource,
    'const downloadActiveContent = async',
    'const reloadConflictAuthority',
  );
  assert.equal(activeDownload.match(/result\.status === 'cancelled'/gu)?.length, 2);
  const conflictDownload = sliceBetween(
    canvasSource,
    'const saveConflictCopy = async',
    'const copyConflictDraft',
  );
  assert.equal(conflictDownload.includes("if (result.status === 'cancelled') return;"), true);

  const previewDownload = sliceBetween(
    previewSource,
    'const download = async',
    'return (',
  );
  assert.equal(previewDownload.includes("if (result.status === 'cancelled') return;"), true);

  const sandboxDownload = sliceBetween(
    sandboxSource,
    'async function downloadSandboxFile(',
    '\n}',
  );
  assert.equal(sandboxDownload.includes("if (result.status === 'cancelled') return;"), true);
});

test('Live Artifact clears a prior success notice before a later native dialog is cancelled', () => {
  const activeDownload = sliceBetween(
    canvasSource,
    'const downloadActiveContent = async',
    'const reloadConflictAuthority',
  );
  assert.equal(
    activeDownload.indexOf('setNotice(null);') < activeDownload.indexOf('try {'),
    true,
  );
  const conflictDownload = sliceBetween(
    canvasSource,
    'const saveConflictCopy = async',
    'const copyConflictDraft',
  );
  assert.equal(
    conflictDownload.indexOf('setNotice(null);') < conflictDownload.indexOf('try {'),
    true,
  );
});

test('sandbox file scope changes clear previews and gate read/download callbacks before dialogs', () => {
  assert.equal(
    sandboxSource.includes(
      'useLayoutEffect(() => {\n    setPreviewFile(null);\n  }, [runtime.fileClient]);',
    ),
    true,
  );
  const openSource = sliceBetween(sandboxBrowserSource, 'const open = async', 'const download = async');
  assert.equal(openSource.includes('const operation = operationGateRef.current.begin();'), true);
  assert.equal(openSource.includes('operation.signal'), true);
  assert.equal(openSource.includes('if (!operation.isCurrent()) return;'), true);
  const downloadSource = sliceBetween(sandboxBrowserSource, 'const download = async', 'return (');
  assert.equal(downloadSource.includes('const operation = operationGateRef.current.begin();'), true);
  assert.equal(downloadSource.includes('operation.signal'), true);
  assert.equal(downloadSource.includes('if (!operation.isCurrent()) return;'), true);
  assert.equal(
    downloadSource.indexOf('if (!operation.isCurrent()) return;') <
      downloadSource.indexOf('await onDownloadFile?.(result.value)'),
    true,
  );
});
