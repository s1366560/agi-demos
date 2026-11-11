import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');

function load(path) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', output)(require, module, module.exports);
  return module.exports;
}

const settlement = load('../src/features/runtime/desktopWorkbenchSnapshotSettlementV2.ts');
const routeModel = load('../src/features/navigation/desktopRouteHostModel.ts');
const revision = load('../src/features/runtime/projectAuthorityRevision.ts');

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

test('critical observation is published before a slow branch is validated', async () => {
  const slow = deferred();
  const seen = [];
  let settled = false;
  const pending = settlement.runCriticalWorkbenchSnapshotPhase({
    async critical() {
      return { entities: 'observed' };
    },
    remaining() {
      return slow.promise;
    },
    project(critical, remaining) {
      return {
        entities: critical.entities,
        admin: remaining ? remaining.admin : 'capability_observation_pending',
      };
    },
    observe(snapshot) {
      seen.push(snapshot);
    },
  });
  pending.then(() => { settled = true; }, () => { settled = true; });
  await Promise.resolve();
  assert.equal(seen.length, 1);
  assert.equal(seen[0].entities, 'observed');
  assert.equal(seen[0].admin, 'capability_observation_pending');
  assert.equal(seen[0].admin === 'available', false);
  assert.equal(settled, false);
  slow.resolve({ admin: 'validated-unavailable' });
  const finalSnapshot = await pending;
  assert.equal(finalSnapshot.entities, 'observed');
  assert.equal(finalSnapshot.admin, 'validated-unavailable');
});

test('a failing slow branch still rejects after the critical observation', async () => {
  const seen = [];
  await assert.rejects(
    settlement.runCriticalWorkbenchSnapshotPhase({
      async critical() {
        return { entities: 'observed' };
      },
      async remaining() {
        throw Object.assign(new Error('branch failed'), { code: 'tenant_admin_authority_unavailable' });
      },
      project(critical, remaining) {
        return { entities: critical.entities, admin: remaining?.admin ?? 'capability_observation_pending' };
      },
      observe(snapshot) {
        seen.push(snapshot);
      },
    }),
    (error) => error.code === 'tenant_admin_authority_unavailable',
  );
  assert.equal(seen.length, 1);
  assert.equal(seen[0].entities, 'observed');
});

test('remaining snapshot branches leave room for the current route', async () => {
  let active = 0;
  let max = 0;
  const starters = Array.from({ length: 6 }, (_, index) => async () => {
    active += 1;
    max = Math.max(max, active);
    await new Promise((resolve) => setTimeout(resolve, 15));
    active -= 1;
    return index;
  });
  const results = await settlement.settleWorkbenchSnapshotBranchesLimitedV2(starters, 2);
  assert.deepEqual(results, [0, 1, 2, 3, 4, 5]);
  assert.equal(max, 2);
});
function scope(tenant, project) {
  return { tenant_id: tenant, project_id: project, workspace_id: null, instance_id: null };
}
function capability(overrides) {
  return {
    availability: 'available',
    reason_code: null,
    authority_revision: 4,
    provenance: 'observed',
    allowed_actions: ['search'],
    scope: scope('tenant-a', 'project-a'),
    ...overrides,
  };
}
test('authority revision is reused only for the same live project and tenant', () => {
  const search = capability({ authority_revision: null, scope: scope(null, null) });
  const sameProject = capability({ authority_revision: 9 });
  const otherProject = capability({ authority_revision: 9, scope: scope('tenant-a', 'project-b') });
  const otherTenant = capability({ authority_revision: 9, scope: scope('tenant-b', 'project-a') });
  const expired = capability({ availability: 'unavailable', reason_code: 'authority_expired', authority_revision: 9 });
  const expected = scope('tenant-a', 'project-a');
  assert.equal(revision.withProjectAuthorityRevision(search, sameProject, expected).authority_revision, 9);
  assert.equal(revision.withProjectAuthorityRevision(search, otherProject, expected).authority_revision, null);
  assert.equal(revision.withProjectAuthorityRevision(search, otherTenant, expected).authority_revision, null);
  assert.equal(revision.withProjectAuthorityRevision(search, expired, expected).authority_revision, null);
  assert.equal(revision.canReuseProjectAuthorityRevision(expired, expected), false);
});
test('pending observation is not an available route capability', () => {
  const pending = {
    availability: 'unavailable',
    reason_code: 'capability_observation_pending',
    authority_revision: null,
    provenance: 'declared',
    authority_source: 'renderer',
    allowed_actions: [],
    scope: scope('tenant-a', 'project-a'),
  };
  const access = routeModel.evaluateDesktopRouteAccess({
    match: {
      context: { tenantId: 'tenant-a', projectId: 'project-a' },
      definition: {
        requiredPermission: [['authenticated']],
        localPolicy: 'allowed',
        capability: 'tenant-tenant-tasks',
        scope: ['project'],
      },
    },
    mode: 'cloud',
    permissions: new Set(['authenticated']),
    capability: pending,
  });
  assert.equal(access.status, 'unavailable');
  assert.equal(access.reasonCode, 'capability_observation_pending');
  assert.notEqual(access.status, 'allowed');
});
test('an unchanged entity observation does not look like a new route capability', () => {
  const capability = {
    availability: 'degraded',
    reason_code: 'desktop_project_entities_actions_partial',
    authority_revision: 2,
    provenance: 'observed',
    authority_source: 'cloud_service',
    allowed_actions: ['view', 'list'],
    scope: { tenant_id: 'tenant', project_id: 'project', workspace_id: null, instance_id: null },
  };
  assert.equal(
    routeModel.desktopRouteCapabilityObservationUnchanged(capability, { ...capability }),
    true,
  );
  assert.equal(
    routeModel.desktopRouteCapabilityObservationUnchanged(capability, {
      ...capability,
      reason_code: 'capability_observation_pending',
      availability: 'unavailable',
    }),
    false,
  );
  assert.equal(routeModel.desktopRouteCapabilityObservationUnchanged(null, capability), false);
});
