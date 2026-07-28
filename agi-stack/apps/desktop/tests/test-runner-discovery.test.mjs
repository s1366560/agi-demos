import assert from 'node:assert/strict';
import { basename } from 'node:path';
import { test } from 'node:test';

import {
  assertTestInventoryComplete,
  discoverTestFiles,
} from './testDiscovery.mjs';

const REQUIRED_PREVIOUSLY_OMITTED_TESTS = [
  'agent-definition-events.test.mjs',
  'sandbox-upload-client.test.mjs',
];

test('desktop runner discovers every test module in stable order', () => {
  const discovered = discoverTestFiles(new URL('.', import.meta.url));
  const filenames = discovered.map((path) => basename(path));

  assert.deepEqual(filenames, [...filenames].sort());
  assert.equal(new Set(filenames).size, filenames.length);
  for (const required of REQUIRED_PREVIOUSLY_OMITTED_TESTS) {
    assert.equal(filenames.includes(required), true, `${required} must be executed by the runner`);
  }
  assert.doesNotThrow(() =>
    assertTestInventoryComplete({
      testsDirectory: new URL('.', import.meta.url),
      testFiles: discovered,
    }),
  );
});

test('desktop runner inventory check fails closed when a test is omitted', () => {
  const discovered = discoverTestFiles(new URL('.', import.meta.url));
  const intentionallyIncomplete = discovered.filter(
    (path) => basename(path) !== 'sandbox-upload-client.test.mjs',
  );

  assert.throws(
    () =>
      assertTestInventoryComplete({
        testsDirectory: new URL('.', import.meta.url),
        testFiles: intentionallyIncomplete,
      }),
    /sandbox-upload-client\.test\.mjs/,
  );
});
