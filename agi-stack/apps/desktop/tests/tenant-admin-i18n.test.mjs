import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';

import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { tenantAdminEnUS, tenantAdminZhCN } = require(
  '/tmp/agistack-desktop-test-dist/src/features/tenant-admin/locales/tenantAdminMessages.js',
);
const featureDirectory = new URL('../src/features/tenant-admin/', import.meta.url);

test('Tenant native pages publish complete matching English and Chinese message catalogs', () => {
  const englishKeys = Object.keys(tenantAdminEnUS).sort();
  const chineseKeys = Object.keys(tenantAdminZhCN).sort();
  assert.deepEqual(chineseKeys, englishKeys);

  const pageKeys = new Set();
  for (const entry of readdirSync(featureDirectory, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.tsx')) continue;
    const source = readFileSync(new URL(entry.name, featureDirectory), 'utf8');
    for (const match of source.matchAll(/t\('(tenantAdmin\.[^']+)'/gu)) {
      pageKeys.add(match[1]);
    }
  }

  const missing = [...pageKeys].filter(
    (key) => !(key in tenantAdminEnUS) || !(key in tenantAdminZhCN),
  );
  assert.deepEqual(missing, []);
});

test('ACP native test action requires explicit cross-platform working-directory input', () => {
  const source = readFileSync(new URL('TenantAcpPage.tsx', featureDirectory), 'utf8');
  assert.doesNotMatch(source, /cwd:\s*['"]\/tmp['"]/u);
  assert.match(source, /tenantAdmin\.acp\.testCwd/u);
  assert.match(source, /tenantAdmin\.acp\.testPrompt/u);
});
