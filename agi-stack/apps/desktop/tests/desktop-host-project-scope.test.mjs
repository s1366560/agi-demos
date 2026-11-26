import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  explicitWorkbenchProject,
  resolveWorkbenchScope,
} = require('/tmp/agistack-desktop-test-dist/src/fullHost/workbenchModel.js');
const {
  fullMarketProjectId,
  projectCatalogPath,
  readProjectCatalogPage,
} = require('/tmp/agistack-desktop-test-dist/src/fullHost/projectCatalog.js');

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

const session = { tenantId: 'tenant-a', projectId: 'project-stuck' };

test('a project path and projectId query override the persisted workspace', () => {
  const fromPath = explicitWorkbenchProject(
    '/tenant/tenant-a/project/project-target/memories',
  );
  assert.deepEqual(fromPath, { tenantId: 'tenant-a', projectId: 'project-target' });
  assert.deepEqual(
    resolveWorkbenchScope('/tenant/tenant-a/project/project-target/memories', session),
    { tenantId: 'tenant-a', projectId: 'project-target' },
  );
  assert.deepEqual(
    resolveWorkbenchScope(
      '/tenant/tenant-a/agent-workspace?projectId=project-target',
      session,
    ),
    { tenantId: 'tenant-a', projectId: 'project-target' },
  );
});

test('host administration keeps the persisted project and ignores conflicting scope copies', () => {
  assert.equal(explicitWorkbenchProject('/tenant/tenant-a/projects'), null);
  assert.equal(explicitWorkbenchProject('/tenant/tenant-a/plugins?projectId=project-target'), null);
  assert.deepEqual(resolveWorkbenchScope('/tenant/tenant-a/projects', session), session);
  assert.equal(
    explicitWorkbenchProject(
      '/tenant/tenant-a/project/project-target/memories?projectId=other',
    ),
    null,
  );
  assert.equal(
    explicitWorkbenchProject('/tenant/tenant-a/tasks?projectId=one&projectId=two'),
    null,
  );
});

test('the full host project list uses the same projects collection as the web host', () => {
  assert.equal(
    projectCatalogPath('tenant a', 1),
    '/api/v1/projects/?tenant_id=tenant+a&page=1&page_size=100',
  );
  assert.deepEqual(
    readProjectCatalogPage({
      projects: [{ id: 'p', tenant_id: 'tenant a', name: 'Default' }],
      total: 1,
      page: 1,
      page_size: 100,
    }),
    { projects: [{ id: 'p', tenant_id: 'tenant a', name: 'Default' }], total: 1, page: 1 },
  );
  assert.throws(() => readProjectCatalogPage([]), /project_catalog_invalid/);
  const directory = read('../src/fullHost/ProjectDirectory.tsx');
  const settings = read('../src/fullHost/HostSettings.tsx');
  assert.doesNotMatch(directory, /project-packages\/projects/);
  assert.doesNotMatch(settings, /project-packages\/projects/);
  assert.match(directory, /loadTenantProjects/);
  assert.match(settings, /loadTenantProjects/);
});

test('marketplace scope and the missing-page state match the web host', () => {
  assert.equal(fullMarketProjectId(''), null);
  assert.equal(fullMarketProjectId('projectId=project-target'), 'project-target');
  assert.equal(fullMarketProjectId('projectId=one&projectId=two'), null);
  const workbench = read('../src/fullHost/FullWorkbench.tsx');
  const market = read('../src/packageHost/PackageManagement.tsx');
  assert.match(workbench, /fullHost\.unavailable/);
  assert.match(workbench, /fullHost\.backToMarket/);
  assert.doesNotMatch(
    workbench,
    /desktopProductionRouter\.unavailable\.description/,
  );
  assert.match(market, /full \? fullMarketProjectId/);
  assert.match(market, /t\.tenantScope/);
  const i18n = read('../src/i18n.tsx');
  assert.equal(
    (i18n.match(/'fullHost\.unavailable'/g) ?? []).length,
    2,
  );
  assert.match(i18n, /当前范围尚未安装此页面/);
  assert.match(i18n, /返回插件市场/);
});

test('light host theme wins over the operating-system dark marketplace palette', () => {
  const market = read('../../../packages/plugin-marketplace-ui/src/pluginMarket.css');
  const workbench = read('../src/packageHost/workbench.css');
  const shell = read('../src/fullHost/style.css');
  assert.match(market, /:root:not\(\[data-theme='light'\]\) \.pm-market/);
  assert.match(market, /:root\[data-theme='light'\] \.pm-market/);
  assert.doesNotMatch(market, /:where\(\.light/);
  const lightAt = market.lastIndexOf(":root[data-theme='light'] .pm-market");
  const darkMediaAt = market.indexOf(":root:not([data-theme='light']) .pm-market");
  assert.ok(lightAt > darkMediaAt);
  assert.match(workbench, /background:\s*var\(--desktop-bg,\s*Canvas\)/);
  assert.doesNotMatch(workbench, /--color-background/);
  assert.match(shell, /data-theme='light'.*color-scheme:\s*light/s);
});
