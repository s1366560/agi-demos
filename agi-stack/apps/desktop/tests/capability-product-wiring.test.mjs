import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const searchSource = readFileSync(
  new URL('../src/features/search/DesktopSearch.tsx', import.meta.url),
  'utf8',
);
const automationsSource = readFileSync(
  new URL('../src/features/automations/AutomationsPage.tsx', import.meta.url),
  'utf8',
);

test('App composes the capability snapshot into Search and Automation product surfaces', () => {
  assert.match(appSource, /createDesktopWorkbenchCapabilityClient/u);
  assert.match(appSource, /useDesktopCapabilitySnapshot/u);
  assert.match(appSource, /capability=\{searchCapability\}/u);
  assert.match(appSource, /runCapability=\{automationRunCapability\}/u);
});

test('Search blocks requests until structured availability is declared', () => {
  assert.match(searchSource, /if \(!capability\.available\) return/u);
  assert.match(searchSource, /data-reason-code=\{capability\.reason_code/u);
});

test('Automation no longer classifies availability from HTTP status codes', () => {
  assert.doesNotMatch(automationsSource, /\[404,\s*405,\s*501\]/u);
  assert.doesNotMatch(automationsSource, /capabilityUnavailable/u);
  assert.match(automationsSource, /runCapability/u);
});
