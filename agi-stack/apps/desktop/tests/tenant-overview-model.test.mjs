import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  buildTenantOverviewPresentation,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantOverviewPresentationModel.js'
);

const scope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
});

test('presentation exposes authoritative cloud summary and projects', () => {
  const model = buildTenantOverviewPresentation({
    kind: 'ready',
    snapshot: snapshot({
      authority: 'cloud',
      availability: 'available',
      reasonCode: null,
    }),
  });

  assert.equal(model.state, 'ready');
  assert.equal(model.tenant.organizationId, '#TEN-ABC');
  assert.deepEqual(
    model.summary.map((field) => [field.id, field.availability, field.value]),
    [
      ['storage', 'available', 1024],
      ['projects', 'available', 1],
      ['members', 'available', 3],
    ],
  );
  assert.equal(model.projects.length, 1);
  assert.equal(model.projects[0].owner, 'Ada');
});

test('presentation retains structured local degradation without placeholder values', () => {
  const localScope = { authority: 'local', tenantId: 'tenant-local' };
  const model = buildTenantOverviewPresentation({
    kind: 'ready',
    snapshot: snapshot({
      scope: localScope,
      authority: 'local',
      availability: 'degraded',
      reasonCode: 'local_tenant_overview_memory_projection_unavailable',
      storage: unavailableField('local_tenant_memory_projection_unavailable'),
      memoryHistory: {
        availability: 'unavailable',
        reasonCode: 'local_tenant_memory_projection_unavailable',
        value: [],
      },
      projects: {
        availability: 'degraded',
        reasonCode: 'local_tenant_project_owner_projection_unavailable',
        value: [
          {
            id: 'project-local',
            name: 'Local project',
            owner: unavailableField('local_project_owner_projection_unavailable'),
            memoryConsumed: unavailableField(
              'local_project_memory_projection_unavailable',
            ),
            status: 'active',
          },
        ],
        active: 1,
        newThisWeek: 0,
      },
    }),
  });

  assert.equal(model.state, 'degraded');
  assert.equal(model.reasonCode, 'local_tenant_overview_memory_projection_unavailable');
  assert.equal(model.summary[0].value, null);
  assert.equal(model.summary[0].availability, 'unavailable');
  assert.equal(model.projects[0].owner, null);
  assert.equal(model.projects[0].memoryConsumed, null);
});

test('presentation maps loading, scope switch and terminal states', () => {
  assert.equal(
    buildTenantOverviewPresentation({
      kind: 'loading',
      scope,
      scopeSwitch: false,
    }).state,
    'loading',
  );
  assert.equal(
    buildTenantOverviewPresentation({
      kind: 'loading',
      scope,
      scopeSwitch: true,
    }).state,
    'scope_switch',
  );
  for (const state of ['empty', 'error', 'forbidden', 'unavailable']) {
    const input =
      state === 'error'
        ? {
            kind: state,
            scope,
            reasonCode: 'request_failed',
            retryable: true,
          }
        : state === 'unavailable'
          ? {
              kind: state,
              scope,
              reasonCode: 'runtime_unavailable',
              retryable: true,
            }
          : { kind: state, scope, reasonCode: `${state}_reason` };
    const model = buildTenantOverviewPresentation(input);
    assert.equal(model.state, state);
    assert.equal(model.tenant, null);
  }
});

function snapshot(overrides = {}) {
  return {
    scope,
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view'],
    authorityRevision: null,
    tenantInfo: {
      organizationId: '#TEN-ABC',
      plan: 'Pro',
      region: availableField('US East'),
      nextBillingDate: availableField('2026-08-01'),
    },
    storage: availableField({ used: 1024, total: 4096, percentage: 25 }),
    projects: {
      availability: 'available',
      reasonCode: null,
      value: [
        {
          id: 'project-1',
          name: 'Alpha',
          owner: availableField('Ada'),
          memoryConsumed: availableField('1.0 KB'),
          status: 'active',
        },
      ],
      active: 1,
      newThisWeek: 1,
    },
    members: availableField({ total: 3, newAdded: 1 }),
    memoryHistory: availableField([]),
    ...overrides,
  };
}

function availableField(value) {
  return { availability: 'available', reasonCode: null, value };
}

function unavailableField(reasonCode) {
  return { availability: 'unavailable', reasonCode, value: null };
}
