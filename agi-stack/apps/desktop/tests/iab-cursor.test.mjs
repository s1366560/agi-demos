import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { parseIabCursorConsoleMessage } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/iab/iabCursor.js',
);

test('cursor console bridge parses arrivals and ignores page logs', () => {
  assert.deepEqual(
    parseIabCursorConsoleMessage('__memstack_cursor__:{"type":"AGENT_CURSOR_ARRIVED","moveSequence":3}'),
    { moveSequence: 3 },
  );
  assert.equal(parseIabCursorConsoleMessage('ordinary page log'), null);
  assert.equal(parseIabCursorConsoleMessage('__memstack_cursor__:not json'), null);
  assert.equal(
    parseIabCursorConsoleMessage('__memstack_cursor__:{"type":"AGENT_CURSOR_STATE"}'),
    null,
  );
});
