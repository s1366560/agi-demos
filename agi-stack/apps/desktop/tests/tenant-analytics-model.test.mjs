import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  buildTenantAnalyticsPresentation,
  formatTenantAnalyticsBytes,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAnalyticsPresentationModel.js'
);

test('analytics presentation derives KPI values and a structural trend from authority data', () => {
  const model = buildTenantAnalyticsPresentation({
    kind: 'ready',
    snapshot: snapshot({
      memoryGrowth: availableField([
        { date: '2026-07-01', count: 2 },
        { date: '2026-07-02', count: 6 },
      ]),
      summary: {
        totalMemories: availableField(8),
        totalStorageBytes: availableField(2048),
        totalProjects: availableField(2),
        periodDays: 30,
      },
    }),
  });

  assert.equal(model.state, 'ready');
  assert.equal(model.summary.find((item) => item.id === 'average').value, '4');
  assert.equal(model.summary.find((item) => item.id === 'storage').value, '2 KB');
  assert.equal(model.trend, 'up');
});

test('analytics presentation exposes empty and degraded states without replacing unavailable values', () => {
  const empty = buildTenantAnalyticsPresentation({
    kind: 'ready',
    snapshot: snapshot(),
  });
  assert.equal(empty.state, 'empty');

  const degraded = buildTenantAnalyticsPresentation({
    kind: 'ready',
    snapshot: snapshot({
      availability: 'degraded',
      reasonCode: 'local_tenant_analytics_memory_projection_unavailable',
      memoryGrowth: unavailableField(
        [],
        'local_tenant_memory_projection_unavailable',
      ),
      projectStorage: degradedField(
        [
          {
            name: 'Local',
            storageBytes: unavailableField(
              null,
              'local_project_storage_projection_unavailable',
            ),
            memoryCount: unavailableField(
              null,
              'local_project_memory_projection_unavailable',
            ),
          },
        ],
        'local_project_storage_projection_unavailable',
      ),
      summary: {
        totalMemories: unavailableField(
          null,
          'local_tenant_memory_projection_unavailable',
        ),
        totalStorageBytes: unavailableField(
          null,
          'local_tenant_storage_projection_unavailable',
        ),
        totalProjects: availableField(1),
        periodDays: 30,
      },
    }),
  });
  assert.equal(degraded.state, 'degraded');
  assert.equal(
    degraded.summary.find((item) => item.id === 'memories').value,
    null,
  );
  assert.equal(degraded.projects[0].storageBytes, null);
  assert.equal(degraded.trend, null);
});

test('analytics byte formatter is deterministic across supported units', () => {
  assert.equal(formatTenantAnalyticsBytes(0), '0 B');
  assert.equal(formatTenantAnalyticsBytes(1024), '1 KB');
  assert.equal(formatTenantAnalyticsBytes(1536), '1.5 KB');
});

function snapshot(overrides = {}) {
  return {
    scope: { authority: 'cloud', tenantId: 'tenant-1', period: '30d' },
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'retry'],
    authorityRevision: null,
    memoryGrowth: availableField([]),
    projectStorage: availableField([]),
    summary: {
      totalMemories: availableField(0),
      totalStorageBytes: availableField(0),
      totalProjects: availableField(0),
      periodDays: 30,
    },
    ...overrides,
  };
}

function availableField(value) {
  return { availability: 'available', reasonCode: null, value };
}

function degradedField(value, reasonCode) {
  return { availability: 'degraded', reasonCode, value };
}

function unavailableField(value, reasonCode) {
  return { availability: 'unavailable', reasonCode, value };
}
