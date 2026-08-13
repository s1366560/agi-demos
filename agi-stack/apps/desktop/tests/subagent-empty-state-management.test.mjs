import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const managedResourceViewsSource = readFileSync(
  new URL('../src/features/settings/ManagedResourceViews.tsx', import.meta.url),
  'utf8',
);

test('an authorized empty SubAgent catalog still exposes its management actions', () => {
  assert.match(
    managedResourceViewsSource,
    /section === 'subagents' && canCreate/u,
  );
  assert.doesNotMatch(
    managedResourceViewsSource,
    /section === 'subagents' && canManage/u,
  );
});
