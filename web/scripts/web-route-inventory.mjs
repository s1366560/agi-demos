import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { lstatSync, readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { isAbsolute, posix, relative, resolve, sep, win32 } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isDeepStrictEqual } from 'node:util';

import {
  addProductionRouteKeys,
  extractCanonicalNavigationTargets,
  extractEagerRouteEntries,
  extractLazyPageEntries,
  extractProductionRoutes,
} from './web-route-extractors.mjs';
import { discoverRoutedProductionDependencies } from './web-production-dependency-graph.mjs';
import { resolveRouteRegistrationMounts } from './web-route-mounts.mjs';
import { discoverReachableWebRouteSources } from './web-route-source-graph.mjs';
import { ROUTER_RELATIVE_PATH } from './web-route-source-resolver.mjs';

export {
  extractCanonicalNavigationTargets,
  extractEagerRouteEntries,
  extractLazyPageEntries,
  extractProductionRoutes,
} from './web-route-extractors.mjs';

const INVENTORY_RELATIVE_PATH =
  'agi-stack/apps/desktop/contracts/desktop-web-parity/web-route-inventory.v2.json';
const NAVIGATION_RELATIVE_PATH = 'web/src/config/navigation.ts';
const REVISION_PATTERN = /^[0-9a-f]{40}$/u;

const INVENTORY_SOURCES = Object.freeze({
  canonical_navigation_registry: 'web/src/config/navigation.ts#CANONICAL_NAVIGATION_DESTINATIONS',
  eager_route_entries:
    'reachable route registration modules#relative imports used by JSX or object routes',
  lazy_page_entries: 'reachable route registration modules#lazy(import())',
  production_dependency_entries:
    'web/index.html#transitive local runtime, stylesheet, data, asset, and build inputs',
  production_dependency_ownership:
    'production dependency graph#routed-source reachability or explicit build-input exclusion',
  production_entry:
    'web/index.html#module script bootstrap through web/src/main.tsx and web/src/App.tsx',
  production_router:
    'reachable modules registering JSX Route or static react-router-dom route objects',
});

function compareText(left, right) {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

function sha256(source) {
  return `sha256:${createHash('sha256').update(source).digest('hex')}`;
}

function canonicalRepositoryPath(sourceEntry) {
  if (
    typeof sourceEntry !== 'string' ||
    sourceEntry.length === 0 ||
    isAbsolute(sourceEntry) ||
    posix.isAbsolute(sourceEntry) ||
    win32.isAbsolute(sourceEntry) ||
    sourceEntry.includes('\\')
  ) {
    return null;
  }
  const segments = sourceEntry.split('/');
  if (segments.some((segment) => segment.length === 0 || segment === '.' || segment === '..')) {
    return null;
  }
  return posix.normalize(sourceEntry) === sourceEntry ? sourceEntry : null;
}

function pathEscapesRoot(root, candidate) {
  const relativePath = relative(root, candidate);
  return relativePath === '..' || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath);
}

function resolveRepositorySource(repositoryRoot, sourceEntry) {
  const canonicalSourceEntry = canonicalRepositoryPath(sourceEntry);
  if (!canonicalSourceEntry) {
    throw new Error(`Audited source path must be repository-relative: ${sourceEntry}`);
  }
  const canonicalRoot = realpathSync(repositoryRoot);
  const candidate = resolve(canonicalRoot, canonicalSourceEntry);
  if (pathEscapesRoot(canonicalRoot, candidate)) {
    throw new Error(`Audited source path escapes repository: ${sourceEntry}`);
  }
  const stats = lstatSync(candidate);
  if (stats.isSymbolicLink()) {
    throw new Error(`Audited source must not be a symbolic link: ${sourceEntry}`);
  }
  if (!stats.isFile()) {
    throw new Error(`Audited source must be a regular file: ${sourceEntry}`);
  }
  const canonicalCandidate = realpathSync(candidate);
  if (pathEscapesRoot(canonicalRoot, canonicalCandidate)) {
    throw new Error(`Audited source escapes repository through a link: ${sourceEntry}`);
  }
  return canonicalCandidate;
}

function readRepositorySource(repositoryRoot, sourceEntry) {
  return readFileSync(resolveRepositorySource(repositoryRoot, sourceEntry), 'utf8');
}

function resolveGitRevision(repositoryRoot, revision = 'HEAD') {
  const resolvedRevision = execFileSync('git', ['rev-parse', '--verify', `${revision}^{commit}`], {
    cwd: repositoryRoot,
    encoding: 'utf8',
  }).trim();
  if (!REVISION_PATTERN.test(resolvedRevision)) {
    throw new Error(`Git revision did not resolve to a full commit: ${revision}`);
  }
  return resolvedRevision;
}

function readGitBlob(repositoryRoot, revision, sourceEntry) {
  const canonicalSourceEntry = canonicalRepositoryPath(sourceEntry);
  if (!canonicalSourceEntry) {
    throw new Error(`Audited source path must be repository-relative: ${sourceEntry}`);
  }
  return execFileSync('git', ['show', `${revision}:${canonicalSourceEntry}`], {
    cwd: repositoryRoot,
    maxBuffer: 16 * 1024 * 1024,
  });
}

function assertRevisionIsAncestor(repositoryRoot, sourceRevision, headRevision) {
  try {
    execFileSync('git', ['merge-base', '--is-ancestor', sourceRevision, headRevision], {
      cwd: repositoryRoot,
      stdio: 'pipe',
    });
  } catch {
    throw new Error(
      `Inventory source_revision ${sourceRevision} must be an ancestor of current HEAD ${headRevision}`
    );
  }
}

function assertAuditedSourcesMatchGit({ auditedSources, repositoryRoot, sourceRevision }) {
  if (!REVISION_PATTERN.test(sourceRevision)) {
    throw new Error('Inventory source_revision must be a full Git commit');
  }
  const declaredRevision = resolveGitRevision(repositoryRoot, sourceRevision);
  const headRevision = resolveGitRevision(repositoryRoot);
  assertRevisionIsAncestor(repositoryRoot, declaredRevision, headRevision);

  for (const source of auditedSources) {
    const liveBytes = readFileSync(resolveRepositorySource(repositoryRoot, source.source_entry));
    if (sha256(liveBytes) !== source.sha256) {
      throw new Error(
        `Audited source hash does not match working tree bytes: ${source.source_entry}`
      );
    }
    const declaredBlobDigest = sha256(
      readGitBlob(repositoryRoot, declaredRevision, source.source_entry)
    );
    if (declaredBlobDigest !== source.sha256) {
      throw new Error(
        `Audited source hash does not match declared Git revision ${declaredRevision}: ` +
          source.source_entry
      );
    }
    const headBlobDigest = sha256(readGitBlob(repositoryRoot, headRevision, source.source_entry));
    if (headBlobDigest !== source.sha256) {
      throw new Error(
        `Audited source hash does not match current HEAD blob ${headRevision}: ` +
          source.source_entry
      );
    }
  }
}

function compareSourceEntries(left, right) {
  const sourceOrder = compareText(left.source_entry, right.source_entry);
  return sourceOrder !== 0 ? sourceOrder : compareText(left.symbol, right.symbol);
}

function buildAuditedSources({
  navigationSource,
  productionEntrySources,
  productionDependencySources,
  reachableSources,
  routeRegistrationSources,
  routedSourceEntries,
  repositoryRoot,
}) {
  const sourceByEntry = new Map(
    [...reachableSources, ...productionDependencySources, ...productionEntrySources].map(
      (source) => [source.source_entry, source.source]
    )
  );
  sourceByEntry.set(NAVIGATION_RELATIVE_PATH, navigationSource);
  const rolesBySource = new Map();

  function addRole(sourceEntry, role) {
    const roles = rolesBySource.get(sourceEntry) ?? new Set();
    roles.add(role);
    rolesBySource.set(sourceEntry, roles);
  }

  addRole(NAVIGATION_RELATIVE_PATH, 'canonical_navigation_registry');
  for (const source of productionEntrySources) {
    addRole(source.source_entry, 'production_entry');
  }
  for (const source of routeRegistrationSources) {
    addRole(source.source_entry, 'production_router');
  }
  for (const entry of routedSourceEntries) {
    addRole(entry.source_entry, 'routed_page');
  }
  for (const source of productionDependencySources) {
    const existingRoles = rolesBySource.get(source.source_entry);
    if (!existingRoles?.has('routed_page') && !existingRoles?.has('production_router')) {
      addRole(source.source_entry, 'production_dependency');
    }
  }

  return [...rolesBySource]
    .map(([sourceEntry, roles]) => {
      let source = sourceByEntry.get(sourceEntry);
      if (source === undefined && repositoryRoot) {
        source = readRepositorySource(repositoryRoot, sourceEntry);
      }
      if (source === undefined) {
        return null;
      }
      return {
        source_entry: sourceEntry,
        roles: [...roles].sort(compareText),
        sha256: sha256(source),
      };
    })
    .filter(Boolean)
    .sort((left, right) => compareText(left.source_entry, right.source_entry));
}

export function buildWebRouteInventoryFromSources({
  navigationSource,
  routerSource,
  repositoryRoot,
  sourceRevision = null,
}) {
  const canonicalNavigationTargets = extractCanonicalNavigationTargets(navigationSource);
  const sourceGraph = discoverReachableWebRouteSources({
    routerSource,
    repositoryRoot,
  });
  const routeRegistrationMounts = resolveRouteRegistrationMounts(sourceGraph, repositoryRoot);
  const lazyPageEntries = [];
  const eagerRouteEntries = [];
  const unkeyedProductionRoutes = [];
  for (const routeSource of sourceGraph.route_registration_sources) {
    const extractionOptions = {
      repositoryRoot,
      sourceEntry: routeSource.source_entry,
    };
    const sourceLazyEntries = extractLazyPageEntries(routeSource.source, extractionOptions);
    const sourceEagerEntries = extractEagerRouteEntries(routeSource.source, extractionOptions);
    lazyPageEntries.push(...sourceLazyEntries);
    eagerRouteEntries.push(...sourceEagerEntries);
    const mountPaths = routeRegistrationMounts.get(routeSource.source_entry);
    if (!mountPaths || mountPaths.length === 0) {
      throw new Error(`Route registration source is unreachable: ${routeSource.source_entry}`);
    }
    for (const parentRoutePath of mountPaths) {
      unkeyedProductionRoutes.push(
        ...extractProductionRoutes(
          routeSource.source,
          [...sourceLazyEntries, ...sourceEagerEntries],
          {
            sourceEntry: routeSource.source_entry,
            addRouteKeys: false,
            parentRoutePath,
          }
        )
      );
    }
  }
  lazyPageEntries.sort(compareSourceEntries);
  eagerRouteEntries.sort(compareSourceEntries);
  const routedSourceEntries = [...lazyPageEntries, ...eagerRouteEntries];
  const productionDependencies = discoverRoutedProductionDependencies({
    repositoryRoot,
    routedSourceEntries,
  });
  const productionRoutes = addProductionRouteKeys(unkeyedProductionRoutes);
  const auditedSources = buildAuditedSources({
    navigationSource,
    productionEntrySources: productionDependencies.entry_sources,
    productionDependencySources: productionDependencies.dependency_sources,
    reachableSources: sourceGraph.reachable_sources,
    routeRegistrationSources: sourceGraph.route_registration_sources,
    routedSourceEntries,
    repositoryRoot,
  });
  const routeRegistrationSources = sourceGraph.route_registration_sources.map(
    (source) => source.source_entry
  );

  return {
    schema_version: '2.0.0',
    checker_version: '2.1.0',
    source_revision: sourceRevision,
    sources: INVENTORY_SOURCES,
    counts: {
      audited_sources: auditedSources.length,
      canonical_navigation_targets: canonicalNavigationTargets.length,
      eager_route_entries: eagerRouteEntries.length,
      lazy_page_entries: lazyPageEntries.length,
      production_dependency_edges: productionDependencies.dependency_edges.length,
      production_dependency_ownership: productionDependencies.dependency_ownership.length,
      production_dependency_sources: productionDependencies.dependency_sources.length,
      production_entry_sources: productionDependencies.production_entry_sources.length,
      production_routes: productionRoutes.length,
      route_registration_sources: routeRegistrationSources.length,
    },
    audited_sources: auditedSources,
    canonical_navigation_targets: canonicalNavigationTargets,
    production_routes: productionRoutes,
    eager_route_entries: eagerRouteEntries,
    lazy_page_entries: lazyPageEntries,
    production_dependency_edges: productionDependencies.dependency_edges,
    production_dependency_ownership: productionDependencies.dependency_ownership,
    production_dependency_sources: productionDependencies.dependency_sources.map(
      (source) => source.source_entry
    ),
    production_entry_sources: productionDependencies.production_entry_sources,
    route_registration_sources: routeRegistrationSources,
  };
}

function staleInventoryError(inventory, actual) {
  const expectedCounts = JSON.stringify(inventory?.counts ?? {});
  const actualCounts = JSON.stringify(actual.counts);
  return new Error(
    `Web route inventory is stale (inventory counts ${expectedCounts}; ` +
      `production counts ${actualCounts}). Regenerate and review ${INVENTORY_RELATIVE_PATH}.`
  );
}

export function assertWebRouteInventoryMatchesSources({
  inventory,
  navigationSource,
  routerSource,
  repositoryRoot,
  requireGitBinding = false,
}) {
  let actual;
  try {
    const sourceRevision = inventory?.source_revision ?? null;
    if (requireGitBinding && !REVISION_PATTERN.test(sourceRevision)) {
      throw new Error('Inventory source_revision must bind the audited sources to Git');
    }
    actual = buildWebRouteInventoryFromSources({
      navigationSource,
      routerSource,
      repositoryRoot,
      sourceRevision,
    });
    if (repositoryRoot && sourceRevision !== null) {
      assertAuditedSourcesMatchGit({
        auditedSources: actual.audited_sources,
        repositoryRoot,
        sourceRevision,
      });
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Web route inventory is stale (source extraction failed: ${detail}). ` +
        `Regenerate and review ${INVENTORY_RELATIVE_PATH}.`,
      { cause: error }
    );
  }

  if (!isDeepStrictEqual(inventory, actual)) {
    throw staleInventoryError(inventory, actual);
  }

  return actual;
}

export function checkWebRouteInventory({ repositoryRoot }) {
  const navigationSource = readRepositorySource(repositoryRoot, NAVIGATION_RELATIVE_PATH);
  const routerSource = readRepositorySource(repositoryRoot, ROUTER_RELATIVE_PATH);
  const inventory = JSON.parse(
    readFileSync(resolve(repositoryRoot, INVENTORY_RELATIVE_PATH), 'utf8')
  );
  const errors = [];

  try {
    assertWebRouteInventoryMatchesSources({
      inventory,
      navigationSource,
      routerSource,
      repositoryRoot,
      requireGitBinding: true,
    });
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }

  return {
    errors,
    inventory,
  };
}

export function serializeWebRouteInventory({ repositoryRoot, sourceRevision = 'HEAD' }) {
  const navigationSource = readRepositorySource(repositoryRoot, NAVIGATION_RELATIVE_PATH);
  const routerSource = readRepositorySource(repositoryRoot, ROUTER_RELATIVE_PATH);
  const resolvedSourceRevision = resolveGitRevision(repositoryRoot, sourceRevision);
  const inventory = buildWebRouteInventoryFromSources({
    navigationSource,
    routerSource,
    repositoryRoot,
    sourceRevision: resolvedSourceRevision,
  });
  assertAuditedSourcesMatchGit({
    auditedSources: inventory.audited_sources,
    repositoryRoot,
    sourceRevision: resolvedSourceRevision,
  });
  return `${JSON.stringify(inventory, null, 2)}\n`;
}

function runCli() {
  const repositoryRoot = resolve(fileURLToPath(new URL('../..', import.meta.url)));
  if (process.argv.includes('--print')) {
    process.stdout.write(serializeWebRouteInventory({ repositoryRoot }));
    return;
  }
  if (process.argv.includes('--write')) {
    const inventoryPath = resolve(repositoryRoot, INVENTORY_RELATIVE_PATH);
    writeFileSync(inventoryPath, serializeWebRouteInventory({ repositoryRoot }), {
      encoding: 'utf8',
      mode: 0o600,
    });
    process.stdout.write(`Updated ${INVENTORY_RELATIVE_PATH} from production sources.\n`);
    return;
  }

  const result = checkWebRouteInventory({ repositoryRoot });
  if (result.errors.length > 0) {
    for (const error of result.errors) {
      process.stderr.write(`${error}\n`);
    }
    process.exitCode = 1;
    return;
  }

  const counts = result.inventory.counts;
  process.stdout.write(
    `Web route inventory is current: ${counts.canonical_navigation_targets} canonical targets, ` +
      `${counts.production_routes} production routes, ` +
      `${counts.lazy_page_entries} lazy page entries, ` +
      `${counts.eager_route_entries} eager route entries.\n`
  );
}

const isCliEntry = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isCliEntry) {
  runCli();
}
