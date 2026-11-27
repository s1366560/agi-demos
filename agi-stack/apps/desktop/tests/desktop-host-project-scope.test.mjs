import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  explicitWorkbenchProject,
  FULL_HOST_SIDEBAR_CONSTRAINTS,
  pageInstallationMatches,
  pendingWorkspaceSelection,
  resolveWorkbenchScope,
  selectInstalledPage,
} = require('/tmp/agistack-desktop-test-dist/src/fullHost/workbenchModel.js');
const {
  PACKAGE_PROJECT_CATALOG_PATH,
  fullMarketProjectId,
  projectCatalogPath,
  readPackageProjectCatalog,
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

test('the project page uses the web catalog and the switcher uses the cross-tenant catalog', () => {
  assert.equal(
    projectCatalogPath('tenant a', 1),
    '/api/v1/projects/?tenant_id=tenant+a&page=1&page_size=100',
  );
  assert.equal(PACKAGE_PROJECT_CATALOG_PATH, '/api/v1/project-packages/projects/');
  assert.deepEqual(
    readProjectCatalogPage({
      projects: [{ id: 'p', tenant_id: 'tenant a', name: 'Default' }],
      total: 1,
      page: 1,
      page_size: 100,
    }),
    { projects: [{ id: 'p', tenant_id: 'tenant a', name: 'Default' }], total: 1, page: 1 },
  );
  assert.deepEqual(
    readPackageProjectCatalog([
      {
        project_id: 'p',
        tenant_id: 'other-tenant',
        project_name: 'Other',
        tenant_name: 'Other tenant',
      },
    ]),
    [{ id: 'p', tenant_id: 'other-tenant', name: 'Other', tenant_name: 'Other tenant' }],
  );
  assert.throws(() => readProjectCatalogPage([]), /project_catalog_invalid/);
  const directory = read('../src/fullHost/ProjectDirectory.tsx');
  const settings = read('../src/fullHost/HostSettings.tsx');
  assert.doesNotMatch(directory, /project-packages\/projects/);
  assert.match(directory, /loadTenantProjects/);
  assert.match(settings, /PACKAGE_PROJECT_CATALOG_PATH/);
  assert.doesNotMatch(settings, /loadTenantProjects/);
});

test('a later saved workspace still persists the same deep-linked project', () => {
  const explicit = { tenantId: 'tenant-a', projectId: 'project-b' };
  assert.equal(
    pendingWorkspaceSelection(
      { tenantId: 'tenant-a', projectId: 'project-b' },
      explicit,
    ),
    null,
  );
  assert.deepEqual(
    pendingWorkspaceSelection({ tenantId: 'tenant-a', projectId: 'project-a' }, explicit),
    explicit,
  );
  const workbench = read('../src/fullHost/FullWorkbench.tsx');
  assert.match(workbench, /pendingWorkspaceSelection/);
  assert.match(workbench, /workspaceContext\.revision/);
  assert.doesNotMatch(workbench, /persistedScope/);
});

test('the full-host sidebar defaults to the web width and can be dragged within it', () => {
  assert.deepEqual(FULL_HOST_SIDEBAR_CONSTRAINTS, { min: 200, max: 400, default: 256 });
  const workbench = read('../src/fullHost/FullWorkbench.tsx');
  assert.match(workbench, /SIDEBAR_WIDTH_STORAGE_KEY/);
  assert.match(workbench, /onResize=\{sidebarWidth\.resize\}/);
});

test('a project installation does not satisfy a tenant workspace route', () => {
  const projectPage = {
    projectId: 'project-saved',
    page: { routes: ['/tenant/:tenantId/workspaces', '/tenant/:tenantId/workspaces/new'] },
  };
  const projectDetail = {
    projectId: 'project-saved',
    page: { routes: ['/tenant/:tenantId/project/:projectId/workspaces'] },
  };
  const tenantPage = {
    projectId: null,
    page: { routes: ['/tenant/:tenantId/workspaces'] },
  };
  assert.equal(pageInstallationMatches('/tenant/tenant-a/workspaces', 'project-saved'), false);
  assert.equal(pageInstallationMatches('/tenant/tenant-a/workspaces/new', 'project-saved'), false);
  assert.equal(pageInstallationMatches('/tenant/tenant-a/workspaces', null), true);
  assert.equal(
    selectInstalledPage([projectPage, projectDetail], 'tenant-a', '/tenant/tenant-a/workspaces'),
    null,
  );
  assert.equal(
    selectInstalledPage([projectPage, tenantPage], 'tenant-a', '/tenant/tenant-a/workspaces'),
    tenantPage,
  );
  assert.equal(
    selectInstalledPage(
      [projectPage, projectDetail],
      'tenant-a',
      '/tenant/tenant-a/project/project-saved/workspaces',
    ),
    projectDetail,
  );
  assert.equal(
    selectInstalledPage(
      [tenantPage],
      'tenant-a',
      '/tenant/tenant-a/project/project-saved/workspaces',
    ),
    null,
  );
});

test('the project catalog keeps usage fields for the card layout', () => {
  assert.deepEqual(
    readProjectCatalogPage({
      projects: [
        {
          id: 'p',
          tenant_id: 'tenant a',
          name: 'Default',
          is_public: false,
          stats: {
            memory_count: 2,
            storage_used: 2048,
            storage_limit: 4096,
            node_count: 3,
            member_count: 4,
            last_active: '2026-11-01T00:00:00Z',
          },
        },
      ],
      total: 1,
      page: 1,
    }),
    {
      projects: [
        {
          id: 'p',
          tenant_id: 'tenant a',
          name: 'Default',
          is_public: false,
          stats: {
            memory_count: 2,
            storage_used: 2048,
            storage_limit: 4096,
            node_count: 3,
            member_count: 4,
            last_active: '2026-11-01T00:00:00Z',
          },
        },
      ],
      total: 1,
      page: 1,
    },
  );
  const directory = read('../src/fullHost/ProjectDirectory.tsx');
  assert.match(directory, /desktop-project-card/);
  assert.match(directory, /fullHost\.project\.usage/);
  const settings = read('../src/fullHost/HostSettings.tsx');
  assert.match(settings, /role="alert"/);
  assert.match(settings, /setProjects\(\[\]\)/);
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
  assert.match(market, /fullMarketProjectId/);
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
