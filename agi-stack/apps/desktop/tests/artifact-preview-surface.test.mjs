import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const source = readFileSync(
  new URL('../src/features/chat/ArtifactPreviewSurface.tsx', import.meta.url),
  'utf8',
);

test('preview surface uses authenticated bytes and cleans up requests and Blob URLs', () => {
  assert.match(source, /client[\s\S]*\.download\(artifactId, controller\.signal\)/);
  assert.match(source, /controller\.abort\(\)/);
  assert.match(source, /URL\.revokeObjectURL\(objectUrl\)/);
  assert.doesNotMatch(source, /https?:\/\//);
});

test('HTML and SVG previews are isolated without arbitrary navigation or script execution', () => {
  assert.match(source, /sandbox=""/);
  assert.match(source, /referrerPolicy="no-referrer"/);
  assert.match(source, /default-src 'none'/);
  assert.match(source, /script, form, iframe/);
  assert.match(source, /foreignObject/);
  assert.doesNotMatch(source, /dangerouslySetInnerHTML/);
});

test('Office previews lazy-load pinned renderers and XLSX cells stay React text', () => {
  assert.match(source, /import\('docx-preview'\)/);
  assert.match(source, /import\('xlsx'\)/);
  assert.match(source, /sheet_to_json/);
  assert.doesNotMatch(source, /sheet_to_html/);
  assert.match(source, /MAX_WORKBOOK_ROWS = 2_000/);
  assert.match(source, /MAX_WORKBOOK_COLUMNS = 100/);
});
