import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { desktopScreenshotFile, readDesktopScreenshotPreview } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/desktopScreenshotModel.js',
);
const menuSource = readFileSync(
  new URL('../src/features/chat/ComposerPlusMenu.tsx', import.meta.url),
  'utf8',
);

const onePixelPng =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

test('desktop screenshot preview validates the named PNG bridge result', () => {
  const preview = readDesktopScreenshotPreview({
    dataUrl: `data:image/png;base64,${onePixelPng}`,
    displayId: '42',
    height: 1,
    mimeType: 'image/png',
    pngBytes: 68,
    width: 1,
  });
  assert.equal(preview.displayId, '42');
  assert.equal(preview.width, 1);
  assert.equal(preview.height, 1);

  const file = desktopScreenshotFile(preview, new Date('2026-07-28T01:02:03.000Z'));
  assert.equal(file.name, 'memstack-screenshot-2026-07-28T01-02-03-000Z.png');
  assert.equal(file.type, 'image/png');
  assert.equal(file.size, 68);
});

test('desktop screenshot preview fails closed before an attachment can be created', () => {
  assert.throws(
    () =>
      readDesktopScreenshotPreview({
        dataUrl: 'data:text/plain;base64,SGVsbG8=',
        displayId: '42',
        height: 1,
        mimeType: 'image/png',
        pngBytes: 5,
        width: 1,
      }),
    /screenshot preview is invalid/u,
  );
});

test('Composer screenshot is user initiated, previewed, and confirmed before upload', () => {
  assert.match(menuSource, /window\.__MEMSTACK_DESKTOP__\?\.captureCurrentDisplay/u);
  assert.match(menuSource, /readDesktopScreenshotPreview/u);
  assert.match(menuSource, /desktop-screenshot-preview/u);
  assert.match(menuSource, /desktopScreenshotFile/u);
  assert.match(menuSource, /onUploadFiles\(\[file\]\)/u);
  assert.doesNotMatch(menuSource, /captureCurrentDisplay\(\)[\s\S]{0,300}onUploadFiles/u);
});
