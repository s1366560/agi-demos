import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { test } from 'node:test';

import { isolatedGitEnvironment } from './isolated-git-environment.mjs';

import { checkWebRouteInventory, serializeWebRouteInventory } from './web-route-inventory.mjs';

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

test('inventory binds audited source hashes to its declared revision and current HEAD blobs', () => {
  const env = isolatedGitEnvironment();
  const sandbox = mkdtempSync(resolve(tmpdir(), 'memstack-route-revision-binding-'));
  const isolatedRepository = resolve(sandbox, 'repository');
  const contractPath = resolve(
    isolatedRepository,
    'agi-stack/apps/desktop/contracts/desktop-web-parity/web-route-inventory.v2.json'
  );
  const sources = new Map([
    ['web/src/App.tsx', routerSource],
    ['web/src/config/navigation.ts', navigationSource],
    ['web/src/pages/EagerPage.tsx', 'export function EagerPage() { return <main>Eager</main>; }\n'],
    [
      'web/src/pages/tenant/TenantOverview.tsx',
      'export function TenantOverview() { return <main>Overview</main>; }\n',
    ],
    ['web/src/pages/DefaultPage.tsx', "export { default } from './DefaultPageImpl';\n"],
    [
      'web/src/pages/DefaultPageImpl.tsx',
      'export default function DefaultPage() { return <main>Default</main>; }\n',
    ],
  ]);
  for (const [sourceEntry, source] of sources) {
    const absolutePath = resolve(isolatedRepository, sourceEntry);
    mkdirSync(resolve(absolutePath, '..'), { recursive: true });
    writeFileSync(absolutePath, source);
  }
  execFileSync('git', ['init', '-q'], { env, cwd: isolatedRepository });
  execFileSync('git', ['config', 'user.email', 'route-inventory@example.invalid'], {
    env,
    cwd: isolatedRepository,
  });
  execFileSync('git', ['config', 'user.name', 'Route Inventory Test'], {
    env,
    cwd: isolatedRepository,
  });
  execFileSync('git', ['add', '.'], { env, cwd: isolatedRepository });
  execFileSync('git', ['commit', '-qm', 'test: add route sources'], {
    env,
    cwd: isolatedRepository,
  });
  const sourceRevision = execFileSync('git', ['rev-parse', 'HEAD'], {
    env,
    cwd: isolatedRepository,
    encoding: 'utf8',
  }).trim();

  try {
    mkdirSync(resolve(contractPath, '..'), { recursive: true });
    writeFileSync(
      contractPath,
      serializeWebRouteInventory({
        repositoryRoot: isolatedRepository,
        sourceRevision,
      })
    );
    execFileSync('git', ['add', '.'], { env, cwd: isolatedRepository });
    execFileSync('git', ['commit', '-qm', 'test: add route inventory'], {
      env,
      cwd: isolatedRepository,
    });
    assert.deepEqual(checkWebRouteInventory({ repositoryRoot: isolatedRepository }).errors, []);

    const dependencyPath = resolve(isolatedRepository, 'web/src/pages/DefaultPageImpl.tsx');
    const dependencySource = sources.get('web/src/pages/DefaultPageImpl.tsx');
    const changedDependency = dependencySource.replace('>Default<', '>Changed dependency<');
    writeFileSync(dependencyPath, changedDependency);
    const dirtyDependencyErrors = checkWebRouteInventory({
      repositoryRoot: isolatedRepository,
    }).errors;
    assert.equal(
      dirtyDependencyErrors.some(
        (error) =>
          error.includes('web/src/pages/DefaultPageImpl.tsx') &&
          error.includes('declared Git revision')
      ),
      true
    );
    writeFileSync(dependencyPath, dependencySource);
    assert.deepEqual(checkWebRouteInventory({ repositoryRoot: isolatedRepository }).errors, []);

    writeFileSync(dependencyPath, changedDependency);
    execFileSync('git', ['add', 'web/src/pages/DefaultPageImpl.tsx'], {
      env,
      cwd: isolatedRepository,
    });
    execFileSync('git', ['commit', '-qm', 'test: change routed production dependency'], {
      env,
      cwd: isolatedRepository,
    });
    const committedDependencyErrors = checkWebRouteInventory({
      repositoryRoot: isolatedRepository,
    }).errors;
    assert.equal(
      committedDependencyErrors.some(
        (error) =>
          error.includes('web/src/pages/DefaultPageImpl.tsx') &&
          error.includes('declared Git revision')
      ),
      true
    );
    writeFileSync(dependencyPath, dependencySource);
    execFileSync('git', ['add', 'web/src/pages/DefaultPageImpl.tsx'], {
      env,
      cwd: isolatedRepository,
    });
    execFileSync('git', ['commit', '-qm', 'test: restore routed production dependency'], {
      env,
      cwd: isolatedRepository,
    });
    assert.deepEqual(checkWebRouteInventory({ repositoryRoot: isolatedRepository }).errors, []);

    const changedRouter = routerSource.replace('path=":tenantId"', 'path=":organizationId"');
    writeFileSync(resolve(isolatedRepository, 'web/src/App.tsx'), changedRouter);
    const dirtyErrors = checkWebRouteInventory({ repositoryRoot: isolatedRepository }).errors;
    assert.equal(
      dirtyErrors.some(
        (error) => error.includes('declared Git revision') || error.includes('current HEAD blob')
      ),
      true
    );

    execFileSync('git', ['add', 'web/src/App.tsx'], { env, cwd: isolatedRepository });
    execFileSync('git', ['commit', '-qm', 'test: change production route'], {
      env,
      cwd: isolatedRepository,
    });
    const committedErrors = checkWebRouteInventory({ repositoryRoot: isolatedRepository }).errors;
    assert.equal(
      committedErrors.some(
        (error) => error.includes('declared Git revision') || error.includes('current HEAD blob')
      ),
      true
    );
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
});
