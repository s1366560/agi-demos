import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { resolveRouteSourceEntry, resolveWebSourceEntry } from './web-route-source-resolver.mjs';
import {
  assertWebRouteInventoryMatchesSources,
  buildWebRouteInventoryFromSources,
  checkWebRouteInventory,
} from './web-route-inventory.mjs';

const repositoryRoot = fileURLToPath(new URL('../..', import.meta.url));

const navigationSource = `
const CANONICAL_NAVIGATION_DESTINATIONS = [
  {
    id: 'overview',
    label: 'nav.overview',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/overview',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/overview'),
  },
] as const;
`;

const routerSource = `
import { lazy } from 'react';
import { Route, Routes } from 'react-router-dom';
import {
  EagerPage as RoutedEagerPage,
  UnusedPage,
} from './pages/EagerPage';

const TenantOverview = lazy(() =>
  import('./pages/tenant/TenantOverview').then((module) => ({
    default: module.TenantOverview,
  }))
);
const DefaultPage = lazy(() => import('./pages/DefaultPage'));

export function App() {
  return (
    <Routes>
      <Route path="/tenant">
        <Route
          path=":tenantId"
          element={
            <RoutedEagerPage>
              <TenantOverview />
            </RoutedEagerPage>
          }
        />
        <Route index element={<DefaultPage />} />
      </Route>
    </Routes>
  );
}
`;

test('extracts canonical targets, route registrations, and routed source entries structurally', () => {
  const inventory = buildWebRouteInventoryFromSources({
    navigationSource,
    routerSource,
  });

  assert.deepEqual(inventory.counts, {
    audited_sources: 2,
    canonical_navigation_targets: 1,
    eager_route_entries: 1,
    lazy_page_entries: 2,
    production_dependency_edges: 0,
    production_dependency_sources: 0,
    production_routes: 3,
    route_registration_sources: 1,
  });
  assert.deepEqual(inventory.route_registration_sources, ['web/src/App.tsx']);
  assert.deepEqual(inventory.audited_sources, [
    {
      roles: ['production_router'],
      sha256: `sha256:${createHash('sha256').update(routerSource).digest('hex')}`,
      source_entry: 'web/src/App.tsx',
    },
    {
      roles: ['canonical_navigation_registry'],
      sha256: `sha256:${createHash('sha256').update(navigationSource).digest('hex')}`,
      source_entry: 'web/src/config/navigation.ts',
    },
  ]);
  assert.deepEqual(inventory.canonical_navigation_targets, [
    {
      build_path: "(context) => getCanonicalTenantDestinationPath(context.tenantId, '/overview')",
      contexts: ['tenant'],
      display_role: 'top-nav',
      group_id: 'tenant-core-operations',
      id: 'overview',
      label: 'nav.overview',
      relative_path: '/overview',
      route_family: 'tenant',
      route_key: 'tenant-tenant-overview',
    },
  ]);
  assert.equal(
    new Set(inventory.canonical_navigation_targets.map((target) => target.route_key)).size,
    inventory.canonical_navigation_targets.length
  );
  assert.deepEqual(inventory.eager_route_entries, [
    {
      export_name: 'EagerPage',
      module: './pages/EagerPage',
      source_entry: 'web/src/pages/EagerPage.tsx',
      symbol: 'RoutedEagerPage',
    },
  ]);
  assert.deepEqual(inventory.lazy_page_entries, [
    {
      export_name: 'default',
      module: './pages/DefaultPage',
      source_entry: 'web/src/pages/DefaultPage.tsx',
      symbol: 'DefaultPage',
    },
    {
      export_name: 'TenantOverview',
      module: './pages/tenant/TenantOverview',
      source_entry: 'web/src/pages/tenant/TenantOverview.tsx',
      symbol: 'TenantOverview',
    },
  ]);
  assert.deepEqual(inventory.production_routes, [
    {
      element_components: [],
      index: false,
      path_pattern: '/tenant',
      registration_source: 'web/src/App.tsx',
      route_key: 'production-route-path-tenant',
      source_entries: [],
    },
    {
      element_components: ['RoutedEagerPage', 'TenantOverview'],
      index: false,
      path_pattern: '/tenant/:tenantId',
      registration_source: 'web/src/App.tsx',
      route_key: 'production-route-path-tenant-tenantid',
      source_entries: [
        {
          export_name: 'EagerPage',
          module: './pages/EagerPage',
          source_entry: 'web/src/pages/EagerPage.tsx',
          symbol: 'RoutedEagerPage',
        },
        {
          export_name: 'TenantOverview',
          module: './pages/tenant/TenantOverview',
          source_entry: 'web/src/pages/tenant/TenantOverview.tsx',
          symbol: 'TenantOverview',
        },
      ],
    },
    {
      element_components: ['DefaultPage'],
      index: true,
      path_pattern: '/tenant',
      registration_source: 'web/src/App.tsx',
      route_key: 'production-route-index-tenant',
      source_entries: [
        {
          export_name: 'default',
          module: './pages/DefaultPage',
          source_entry: 'web/src/pages/DefaultPage.tsx',
          symbol: 'DefaultPage',
        },
      ],
    },
  ]);
  assert.equal(
    new Set(inventory.production_routes.map((route) => route.route_key)).size,
    inventory.production_routes.length
  );

  const collidingNavigationSource = navigationSource.replace(
    '] as const;',
    `  {
    id: 'overview',
    label: 'nav.summary',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/summary',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/summary'),
  },
] as const;`
  );
  const collisionInventory = buildWebRouteInventoryFromSources({
    navigationSource: collidingNavigationSource,
    routerSource,
  });
  assert.deepEqual(
    collisionInventory.canonical_navigation_targets.map((target) => target.route_key),
    [
      'tenant-tenant-overview-top-nav-tenant-core-operations-overview',
      'tenant-tenant-overview-top-nav-tenant-core-operations-summary',
    ]
  );
  assert.equal(
    new Set(collisionInventory.canonical_navigation_targets.map((target) => target.route_key)).size,
    collisionInventory.canonical_navigation_targets.length
  );
});

test('stale guard rejects added, removed, or modified production route/source structure', () => {
  const inventory = buildWebRouteInventoryFromSources({
    navigationSource,
    routerSource,
  });

  const changedSources = [
    {
      label: 'added canonical target',
      navigationSource: navigationSource.replace(
        '] as const;',
        `  {
    id: 'projects',
    label: 'nav.projects',
    routeFamily: 'tenant',
    contexts: ['tenant'],
    displayRole: 'top-nav',
    groupId: 'tenant-core-operations',
    relativePath: '/projects',
    buildPath: (context) => getCanonicalTenantDestinationPath(context.tenantId, '/projects'),
  },
] as const;`
      ),
      routerSource,
    },
    {
      label: 'removed route',
      navigationSource,
      routerSource: routerSource.replace('        <Route index element={<DefaultPage />} />\n', ''),
    },
    {
      label: 'modified route',
      navigationSource,
      routerSource: routerSource.replace('path=":tenantId"', 'path=":organizationId"'),
    },
    {
      label: 'modified source entry',
      navigationSource,
      routerSource: routerSource.replace(
        "import('./pages/DefaultPage')",
        "import('./pages/RenamedDefaultPage')"
      ),
    },
  ];

  for (const changedSource of changedSources) {
    assert.throws(
      () =>
        assertWebRouteInventoryMatchesSources({
          inventory,
          navigationSource: changedSource.navigationSource,
          routerSource: changedSource.routerSource,
        }),
      /Web route inventory is stale/,
      changedSource.label
    );
  }
});

test('checked-in inventory matches the current production Web router and navigation registry', () => {
  const result = checkWebRouteInventory({ repositoryRoot });

  assert.deepEqual(result.errors, []);
  assert.equal(result.inventory.schema_version, '2.0.0');
  assert.equal(result.inventory.counts.audited_sources, 634);
  assert.equal(result.inventory.counts.canonical_navigation_targets, 51);
  assert.equal(result.inventory.counts.eager_route_entries, 4);
  assert.equal(result.inventory.counts.lazy_page_entries, 89);
  assert.equal(result.inventory.counts.production_dependency_edges, 1613);
  assert.equal(result.inventory.counts.production_dependency_sources, 540);
  assert.equal(result.inventory.counts.production_routes, 174);
  assert.equal(result.inventory.counts.route_registration_sources, 1);
  assert.equal(
    new Set(result.inventory.canonical_navigation_targets.map((target) => target.route_key)).size,
    result.inventory.canonical_navigation_targets.length
  );
  assert.equal(
    new Set(result.inventory.production_routes.map((route) => route.route_key)).size,
    result.inventory.production_routes.length
  );
  assert.equal(
    result.inventory.production_routes.every(
      (route) =>
        route.route_key.length <= 128 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(route.route_key)
    ),
    true
  );
  for (const page of result.inventory.lazy_page_entries) {
    assert.equal(
      existsSync(resolve(repositoryRoot, page.source_entry)),
      true,
      `${page.symbol}: ${page.source_entry}`
    );
  }
  for (const page of result.inventory.eager_route_entries) {
    assert.equal(
      existsSync(resolve(repositoryRoot, page.source_entry)),
      true,
      `${page.symbol}: ${page.source_entry}`
    );
  }

  const inventoryPath = new URL(
    '../../agi-stack/apps/desktop/contracts/desktop-web-parity/web-route-inventory.v2.json',
    import.meta.url
  );
  const serializedInventory = readFileSync(inventoryPath, 'utf8');
  assert.equal(serializedInventory.endsWith('\n'), true);
});

test('stale guard tracks routed entries and the audited production router source', () => {
  const navigation = readFileSync(resolve(repositoryRoot, 'web/src/config/navigation.ts'), 'utf8');
  const router = readFileSync(resolve(repositoryRoot, 'web/src/App.tsx'), 'utf8');
  const inventory = buildWebRouteInventoryFromSources({
    navigationSource: navigation,
    routerSource: router,
    repositoryRoot,
  });
  const changedRouter = router.replace(
    "import { Login } from './pages/Login';",
    "import { Login } from './pages/RenamedLogin';"
  );
  const changedUnroutedImport = router.replace(
    "import { useProjectStore } from './stores/project';",
    "import { useProjectStore } from './stores/RenamedProject';"
  );

  assert.throws(
    () =>
      assertWebRouteInventoryMatchesSources({
        inventory,
        navigationSource: navigation,
        routerSource: changedRouter,
        repositoryRoot,
      }),
    /Web route inventory is stale/
  );
  assert.throws(
    () =>
      assertWebRouteInventoryMatchesSources({
        inventory,
        navigationSource: navigation,
        routerSource: changedUnroutedImport,
        repositoryRoot,
      }),
    /Web route inventory is stale/
  );
});

test('inventory follows imported route registration modules and hashes routed page sources', () => {
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-route-inventory-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const isolatedNavigationSource = navigationSource;
  const isolatedRouterSource = `
import { Route, Routes } from 'react-router-dom';
import { ProjectRoutes } from './routes/ProjectRoutes';

export function App() {
  return (
    <Routes>
      <Route path="/tenant">
        <ProjectRoutes />
      </Route>
    </Routes>
  );
}
`;
  const projectRoutesSource = `
import { Route } from 'react-router-dom';
import { ProjectSettings } from '../pages/ProjectSettings';

export function ProjectRoutes() {
  return <Route path="settings" element={<ProjectSettings />} />;
}
`;
  const projectSettingsSource =
    'export function ProjectSettings() { return <main>Project settings</main>; }\n';

  const sources = new Map([
    ['web/src/App.tsx', isolatedRouterSource],
    ['web/src/config/navigation.ts', isolatedNavigationSource],
    ['web/src/routes/ProjectRoutes.tsx', projectRoutesSource],
    ['web/src/pages/ProjectSettings.tsx', projectSettingsSource],
  ]);
  for (const [sourceEntry, source] of sources) {
    const absolutePath = resolve(isolatedRepository, sourceEntry);
    mkdirSync(resolve(absolutePath, '..'), { recursive: true });
    writeFileSync(absolutePath, source);
  }

  try {
    const inventory = buildWebRouteInventoryFromSources({
      navigationSource: isolatedNavigationSource,
      routerSource: isolatedRouterSource,
      repositoryRoot: isolatedRepository,
    });

    assert.deepEqual(inventory.route_registration_sources, [
      'web/src/App.tsx',
      'web/src/routes/ProjectRoutes.tsx',
    ]);
    assert.deepEqual(
      inventory.production_routes.map((route) => [route.path_pattern, route.registration_source]),
      [
        ['/tenant', 'web/src/App.tsx'],
        ['/tenant/settings', 'web/src/routes/ProjectRoutes.tsx'],
      ]
    );
    assert.equal(
      inventory.audited_sources.some(
        (source) =>
          source.source_entry === 'web/src/pages/ProjectSettings.tsx' &&
          source.roles.includes('routed_page') &&
          source.sha256 ===
            `sha256:${createHash('sha256').update(projectSettingsSource).digest('hex')}`
      ),
      true
    );

    writeFileSync(
      resolve(isolatedRepository, 'web/src/pages/ProjectSettings.tsx'),
      projectSettingsSource.replace('Project settings', 'Changed behavior')
    );
    assert.throws(
      () =>
        assertWebRouteInventoryMatchesSources({
          inventory,
          navigationSource: isolatedNavigationSource,
          routerSource: isolatedRouterSource,
          repositoryRoot: isolatedRepository,
        }),
      /Web route inventory is stale/
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});

test('inventory revision-binds transitive runtime dependencies of routed source wrappers', () => {
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-route-runtime-dependencies-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const isolatedRouterSource = `
import { lazy } from 'react';
import { Route, Routes } from 'react-router-dom';

const CommunitiesList = lazy(() =>
  import('./pages/project/CommunitiesList').then((module) => ({
    default: module.CommunitiesList,
  }))
);

export function App() {
  return (
    <Routes>
      <Route path="/communities" element={<CommunitiesList />} />
    </Routes>
  );
}
`;
  const wrapperSource = "export { CommunitiesList } from './communities';\n";
  const implementationSource = `
import type { Community } from './types';
import './communities.css';
import { TaskList } from '../../components/TaskList';
import { runtimeValue } from '@scope/runtime';

export function CommunitiesList() {
  const community = {} as Community;
  return <TaskList entityId={community.id} runtimeValue={runtimeValue} />;
}
`;
  const taskListSource =
    'export function TaskList({ entityId }) { return <div>{entityId}</div>; }\n';
  const typeSource = 'export interface Community { id: string }\n';
  const sources = new Map([
    ['web/src/App.tsx', isolatedRouterSource],
    ['web/src/config/navigation.ts', navigationSource],
    ['web/src/pages/project/CommunitiesList.tsx', wrapperSource],
    ['web/src/pages/project/communities/index.tsx', implementationSource],
    ['web/src/pages/project/communities/types.ts', typeSource],
    ['web/src/pages/components/TaskList.tsx', taskListSource],
  ]);
  for (const [sourceEntry, source] of sources) {
    const absolutePath = resolve(isolatedRepository, sourceEntry);
    mkdirSync(resolve(absolutePath, '..'), { recursive: true });
    writeFileSync(absolutePath, source);
  }

  try {
    const inventory = buildWebRouteInventoryFromSources({
      navigationSource,
      routerSource: isolatedRouterSource,
      repositoryRoot: isolatedRepository,
    });

    assert.deepEqual(inventory.production_dependency_edges, [
      {
        from_source_entry: 'web/src/pages/project/CommunitiesList.tsx',
        relationship: 're_export',
        to_source_entry: 'web/src/pages/project/communities/index.tsx',
      },
      {
        from_source_entry: 'web/src/pages/project/communities/index.tsx',
        relationship: 'static_import',
        to_source_entry: 'web/src/pages/components/TaskList.tsx',
      },
    ]);
    assert.equal(
      inventory.production_dependency_edges.some(
        (edge) => edge.to_source_entry === 'web/src/pages/project/communities/types.ts'
      ),
      false,
      'type-only imports are not runtime production dependencies'
    );
    assert.equal(
      inventory.production_dependency_edges.some(
        (edge) =>
          edge.to_source_entry.includes('node_modules') ||
          edge.to_source_entry.endsWith('.css')
      ),
      false,
      'package and CSS imports are not local runtime source dependencies'
    );
    for (const [sourceEntry, source] of [
      ['web/src/pages/project/communities/index.tsx', implementationSource],
      ['web/src/pages/components/TaskList.tsx', taskListSource],
    ]) {
      assert.deepEqual(
        inventory.audited_sources.find((candidate) => candidate.source_entry === sourceEntry),
        {
          roles: ['production_dependency'],
          sha256: `sha256:${createHash('sha256').update(source).digest('hex')}`,
          source_entry: sourceEntry,
        }
      );
    }
    assert.equal(inventory.counts.production_dependency_edges, 2);
    assert.equal(inventory.counts.production_dependency_sources, 2);

    writeFileSync(
      resolve(isolatedRepository, 'web/src/pages/components/TaskList.tsx'),
      taskListSource.replace('entityId', 'taskId')
    );
    assert.throws(
      () =>
        assertWebRouteInventoryMatchesSources({
          inventory,
          navigationSource,
          routerSource: isolatedRouterSource,
          repositoryRoot: isolatedRepository,
        }),
      /Web route inventory is stale/
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});

test('full production dependency inventory regenerates deterministically', (t) => {
  const inventoryPath = resolve(
    repositoryRoot,
    'agi-stack/apps/desktop/contracts/desktop-web-parity/web-route-inventory.v2.json'
  );
  const checkedInInventory = JSON.parse(readFileSync(inventoryPath, 'utf8'));
  const productionNavigationSource = readFileSync(
    resolve(repositoryRoot, 'web/src/config/navigation.ts'),
    'utf8'
  );
  const productionRouterSource = readFileSync(
    resolve(repositoryRoot, 'web/src/App.tsx'),
    'utf8'
  );
  const startedAt = process.hrtime.bigint();
  const first = buildWebRouteInventoryFromSources({
    navigationSource: productionNavigationSource,
    repositoryRoot,
    routerSource: productionRouterSource,
    sourceRevision: checkedInInventory.source_revision,
  });
  const second = buildWebRouteInventoryFromSources({
    navigationSource: productionNavigationSource,
    repositoryRoot,
    routerSource: productionRouterSource,
    sourceRevision: checkedInInventory.source_revision,
  });
  const elapsedMilliseconds = Number(process.hrtime.bigint() - startedAt) / 1_000_000;

  assert.deepEqual(first, second);
  assert.deepEqual(first, checkedInInventory);
  t.diagnostic(
    `two full dependency inventory projections completed in ${elapsedMilliseconds.toFixed(1)}ms`
  );
});

test('propagates the complete parent mount through two imported route registration modules', () => {
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-nested-route-mount-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const isolatedRouterSource = `
import { Route, Routes } from 'react-router-dom';
import { TenantRoutes } from './routes/TenantRoutes';

export function App() {
  return (
    <Routes>
      <Route path="/tenant">
        <TenantRoutes />
      </Route>
    </Routes>
  );
}
`;
  const tenantRoutesSource = `
import { Route } from 'react-router-dom';
import { ProjectRoutes } from './ProjectRoutes';

export function TenantRoutes() {
  return (
    <Route path=":tenantId">
      <ProjectRoutes />
    </Route>
  );
}
`;
  const projectRoutesSource = `
import { Route } from 'react-router-dom';
import { ProjectSettings } from '../pages/ProjectSettings';

export function ProjectRoutes() {
  return (
    <Route path="project/:projectId">
      <Route path="settings" element={<ProjectSettings />} />
    </Route>
  );
}
`;
  const sources = new Map([
    ['web/src/App.tsx', isolatedRouterSource],
    ['web/src/config/navigation.ts', navigationSource],
    ['web/src/routes/TenantRoutes.tsx', tenantRoutesSource],
    ['web/src/routes/ProjectRoutes.tsx', projectRoutesSource],
    [
      'web/src/pages/ProjectSettings.tsx',
      'export function ProjectSettings() { return <main>Project settings</main>; }\n',
    ],
  ]);
  for (const [sourceEntry, source] of sources) {
    const absolutePath = resolve(isolatedRepository, sourceEntry);
    mkdirSync(resolve(absolutePath, '..'), { recursive: true });
    writeFileSync(absolutePath, source);
  }

  try {
    const inventory = buildWebRouteInventoryFromSources({
      navigationSource,
      routerSource: isolatedRouterSource,
      repositoryRoot: isolatedRepository,
    });
    const pathsByRegistrationSource = new Map();
    for (const route of inventory.production_routes) {
      const paths = pathsByRegistrationSource.get(route.registration_source) ?? [];
      paths.push(route.path_pattern);
      pathsByRegistrationSource.set(route.registration_source, paths);
    }

    assert.deepEqual(
      pathsByRegistrationSource,
      new Map([
        ['web/src/App.tsx', ['/tenant']],
        [
          'web/src/routes/ProjectRoutes.tsx',
          ['/tenant/:tenantId/project/:projectId', '/tenant/:tenantId/project/:projectId/settings'],
        ],
        ['web/src/routes/TenantRoutes.tsx', ['/tenant/:tenantId']],
      ])
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});

test('route source resolution rejects symlinks that escape the repository', () => {
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-route-source-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const pagesDirectory = resolve(isolatedRepository, 'web/src/pages');
  const externalSource = resolve(sandbox, 'external-page.tsx');
  mkdirSync(pagesDirectory, { recursive: true });
  writeFileSync(externalSource, 'export default function ExternalPage() {}');
  symlinkSync(externalSource, resolve(pagesDirectory, 'EscapedPage.tsx'));

  try {
    assert.throws(
      () => resolveRouteSourceEntry('./pages/EscapedPage', isolatedRepository, 'lazy'),
      /source entry escapes repository/
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});

test('reachable module resolution rejects relative traversal outside the repository', () => {
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-route-traversal-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const importerDirectory = resolve(isolatedRepository, 'web/src/routes');
  mkdirSync(importerDirectory, { recursive: true });
  writeFileSync(resolve(sandbox, 'outside.tsx'), 'export function Outside() {}');

  try {
    assert.throws(
      () =>
        resolveWebSourceEntry({
          moduleSpecifier: '../../../../outside',
          repositoryRoot: isolatedRepository,
          entryKind: 'reachable Web module',
          importerRelativePath: 'web/src/routes/ProjectRoutes.tsx',
        }),
      /source entry escapes repository/
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});

test('inventory structurally extracts useRoutes objects and detects route or page changes', () => {
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-use-routes-inventory-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const isolatedRouterSource = `
import { Route, Routes } from 'react-router-dom';
import { ProjectRoutes } from './routes/ProjectRoutes';

export function App() {
  return (
    <Routes>
      <Route path="/tenant">
        <ProjectRoutes />
      </Route>
    </Routes>
  );
}
`;
  const projectRoutesSource = `
import { useRoutes } from 'react-router-dom';
import { ProjectOverview } from '../pages/ProjectOverview';
import { ProjectSettings } from '../pages/ProjectSettings';

const projectRoutes = [
  {
    path: ':projectId',
    element: <ProjectOverview />,
    children: [
      {
        path: 'settings',
        Component: ProjectSettings,
      },
    ],
  },
];

export function ProjectRoutes() {
  return useRoutes(projectRoutes);
}
`;
  const projectOverviewSource =
    'export function ProjectOverview() { return <main>Project overview</main>; }\n';
  const projectSettingsSource =
    'export function ProjectSettings() { return <main>Project settings</main>; }\n';
  const sources = new Map([
    ['web/src/App.tsx', isolatedRouterSource],
    ['web/src/config/navigation.ts', navigationSource],
    ['web/src/routes/ProjectRoutes.tsx', projectRoutesSource],
    ['web/src/pages/ProjectOverview.tsx', projectOverviewSource],
    ['web/src/pages/ProjectSettings.tsx', projectSettingsSource],
  ]);
  for (const [sourceEntry, source] of sources) {
    const absolutePath = resolve(isolatedRepository, sourceEntry);
    mkdirSync(resolve(absolutePath, '..'), { recursive: true });
    writeFileSync(absolutePath, source);
  }

  try {
    const inventory = buildWebRouteInventoryFromSources({
      navigationSource,
      routerSource: isolatedRouterSource,
      repositoryRoot: isolatedRepository,
    });
    assert.deepEqual(
      inventory.production_routes.map((route) => [
        route.path_pattern,
        route.registration_source,
        route.element_components,
      ]),
      [
        ['/tenant', 'web/src/App.tsx', []],
        ['/tenant/:projectId', 'web/src/routes/ProjectRoutes.tsx', ['ProjectOverview']],
        ['/tenant/:projectId/settings', 'web/src/routes/ProjectRoutes.tsx', ['ProjectSettings']],
      ]
    );
    assert.deepEqual(inventory.route_registration_sources, [
      'web/src/App.tsx',
      'web/src/routes/ProjectRoutes.tsx',
    ]);
    assert.equal(
      inventory.audited_sources.some(
        (source) =>
          source.source_entry === 'web/src/pages/ProjectSettings.tsx' &&
          source.roles.includes('routed_page')
      ),
      true
    );

    const changedPath = projectRoutesSource.replace("path: 'settings'", "path: 'preferences'");
    writeFileSync(resolve(isolatedRepository, 'web/src/routes/ProjectRoutes.tsx'), changedPath);
    assert.throws(
      () =>
        assertWebRouteInventoryMatchesSources({
          inventory,
          navigationSource,
          routerSource: isolatedRouterSource,
          repositoryRoot: isolatedRepository,
        }),
      /Web route inventory is stale/
    );

    const changedPage = projectRoutesSource.replace(
      "import { ProjectSettings } from '../pages/ProjectSettings';",
      "import { ProjectSettings } from '../pages/RenamedProjectSettings';"
    );
    writeFileSync(
      resolve(isolatedRepository, 'web/src/pages/RenamedProjectSettings.tsx'),
      projectSettingsSource
    );
    writeFileSync(resolve(isolatedRepository, 'web/src/routes/ProjectRoutes.tsx'), changedPage);
    assert.throws(
      () =>
        assertWebRouteInventoryMatchesSources({
          inventory,
          navigationSource,
          routerSource: isolatedRouterSource,
          repositoryRoot: isolatedRepository,
        }),
      /Web route inventory is stale/
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});

test('inventory structurally extracts createBrowserRouter and createRoutesFromElements', () => {
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-data-router-inventory-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const isolatedRouterSource = `
import {
  createBrowserRouter,
  createRoutesFromElements,
  Route,
} from 'react-router-dom';
import { BrowserHome } from './pages/BrowserHome';
import { JsxSettings } from './pages/JsxSettings';

export const router = createBrowserRouter([
  {
    path: '/browser',
    Component: BrowserHome,
  },
]);

export const jsxRoutes = createRoutesFromElements(
  <Route path="/jsx" element={<JsxSettings />} />
);
`;
  const sources = new Map([
    ['web/src/App.tsx', isolatedRouterSource],
    ['web/src/config/navigation.ts', navigationSource],
    [
      'web/src/pages/BrowserHome.tsx',
      'export function BrowserHome() { return <main>Browser</main>; }\n',
    ],
    [
      'web/src/pages/JsxSettings.tsx',
      'export function JsxSettings() { return <main>JSX</main>; }\n',
    ],
  ]);
  for (const [sourceEntry, source] of sources) {
    const absolutePath = resolve(isolatedRepository, sourceEntry);
    mkdirSync(resolve(absolutePath, '..'), { recursive: true });
    writeFileSync(absolutePath, source);
  }

  try {
    const inventory = buildWebRouteInventoryFromSources({
      navigationSource,
      routerSource: isolatedRouterSource,
      repositoryRoot: isolatedRepository,
    });
    assert.deepEqual(
      inventory.production_routes
        .map((route) => [route.path_pattern, route.element_components])
        .sort(([left], [right]) => left.localeCompare(right)),
      [
        ['/browser', ['BrowserHome']],
        ['/jsx', ['JsxSettings']],
      ]
    );
    assert.deepEqual(
      inventory.eager_route_entries.map((entry) => entry.symbol),
      ['BrowserHome', 'JsxSettings']
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});

await import('./web-route-inventory-revision-cases.mjs');
