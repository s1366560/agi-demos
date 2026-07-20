import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const tauriSource = readFileSync(
  new URL('../src-tauri/src/lib.rs', import.meta.url),
  'utf8',
);

test('the Tauri command surface contains only Mission Control shell capabilities', () => {
  assert.match(tauriSource, /local_runtime_status/);
  assert.match(tauriSource, /local_runtime_configure/);
  assert.match(tauriSource, /open_device_authorization_url/);
  assert.match(tauriSource, /trusted_session_(?:save|load|clear)/);

  assert.doesNotMatch(tauriSource, /pub struct DesktopCore/);
  assert.doesNotMatch(tauriSource, /async fn (?:ingest|search|semantic_search)\b/);
  assert.doesNotMatch(tauriSource, /agistack-desktop\.db/);
  assert.doesNotMatch(
    tauriSource,
    /generate_handler!\[[\s\S]*?\b(?:ingest|search|semantic_search)\s*,/,
  );
});
