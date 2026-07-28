import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { isSafeTerminalLink } = require(
  '/tmp/agistack-desktop-test-dist/src/features/sandbox/terminalLinkPolicy.js'
);

test('terminal hyperlinks follow the Electron external-navigation allow-list', () => {
  assert.equal(isSafeTerminalLink('https://docs.memstack.test/run/1'), true);
  assert.equal(isSafeTerminalLink('http://localhost:3000/preview'), true);
  assert.equal(isSafeTerminalLink('http://127.0.0.1:8080/preview'), true);
  assert.equal(isSafeTerminalLink('http://insecure.example/path'), false);
  assert.equal(isSafeTerminalLink('https://user:password@example.com/path'), false);
  assert.equal(isSafeTerminalLink('file:///etc/passwd'), false);
  assert.equal(isSafeTerminalLink('javascript:alert(1)'), false);
});
