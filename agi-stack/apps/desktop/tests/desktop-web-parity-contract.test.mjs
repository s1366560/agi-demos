import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import {
  normalizeDesktopParityFixture,
} from '../contracts/desktop-web-parity/desktop-normalizer.mjs';
import { validateJsonSchema } from '../contracts/desktop-web-parity/schema-validator.mjs';
import { normalizeWebParityFixture } from '../contracts/desktop-web-parity/web-normalizer.mjs';

const contractRoot = new URL('../contracts/desktop-web-parity/', import.meta.url);

function readJson(relativePath) {
  return JSON.parse(readFileSync(new URL(relativePath, contractRoot), 'utf8'));
}

test('versioned parity manifest pins the audited reference revisions and case state', () => {
  const schema = readJson('parity-manifest.schema.json');
  const manifest = readJson('parity-manifest.v1.json');
  const validation = validateJsonSchema(schema, manifest);

  assert.deepEqual(validation, []);
  assert.equal(manifest.schema_version, '1.0.0');
  assert.equal(
    manifest.references.prototype_revision,
    '61454b2ead1cedda584e95afee9f471aac7851fb',
  );
  assert.equal(
    manifest.references.audited_desktop_revision,
    'fe425f5ce75f8722249033bf5571c7e7466d05e1',
  );
  assert.equal(
    manifest.references.web_revision,
    '9af2afe9d6ad2dacc7f6261a74c8936bc99e5a47',
  );
  assert.equal(
    manifest.references.desktop_revision,
    '9af2afe9d6ad2dacc7f6261a74c8936bc99e5a47',
  );
  assert.deepEqual(
    manifest.cases.map((parityCase) => parityCase.fixture).sort(),
    [
      'fixtures/capability-snapshot.v1.json',
      'fixtures/history-replay.v1.json',
      'fixtures/live-events.v1.json',
    ],
  );
});

test('shared fixtures drive both normalizers to the same observable model', () => {
  const schema = readJson('parity-fixture.schema.json');
  const fixturePaths = [
    'fixtures/live-events.v1.json',
    'fixtures/history-replay.v1.json',
    'fixtures/capability-snapshot.v1.json',
  ];

  for (const fixturePath of fixturePaths) {
    const fixture = readJson(fixturePath);
    assert.deepEqual(validateJsonSchema(schema, fixture), [], fixturePath);
    const normalizerInput = { kind: fixture.kind, input: fixture.input };
    const webViewModel = normalizeWebParityFixture(normalizerInput);
    const desktopViewModel = normalizeDesktopParityFixture(normalizerInput);

    assert.deepEqual(webViewModel, fixture.web_expected_view_model, `${fixturePath} Web`);
    assert.deepEqual(
      desktopViewModel,
      fixture.desktop_expected_view_model,
      `${fixturePath} Desktop`,
    );
    assert.deepEqual(desktopViewModel, webViewModel, `${fixturePath} parity`);
  }
});

test('parity schema rejects malformed fixture payloads instead of inferring capability', () => {
  const schema = readJson('parity-fixture.schema.json');
  const valid = readJson('fixtures/capability-snapshot.v1.json');
  const malformed = structuredClone(valid);
  delete malformed.input.snapshot.capabilities.automation_run;

  const validation = validateJsonSchema(schema, malformed);
  assert.equal(validation.length > 0, true);
  assert.equal(
    validation.some((error) => error.includes('automation_run')),
    true,
    validation.join('\n'),
  );
});
