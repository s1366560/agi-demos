import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const ts = require('typescript');

function load(path) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const module = { exports: {} };
  const localRequire = (id) => {
    if (id.endsWith('/api/client')) {
      return {
        DesktopApiError: class DesktopApiError extends Error {
          constructor(message, status) {
            super(message);
            this.status = status;
          }
        },
      };
    }
    return require(id);
  };
  new Function('require', 'module', 'exports', output)(localRequire, module, module.exports);
  return module.exports;
}

const analytics = load('../src/features/tenant/tenantAnalyticsCapability.ts');
const dashboard = load('../src/features/tenant/tenantAgentDashboardCapability.ts');
const bindings = load('../src/features/tenant/tenantAgentBindingsCapability.ts');
const projects = load('../src/features/tenant/tenantProjectsCapability.ts');

const config = {
  mode: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
};

function snapshot(allowedActions) {
  return {
    availability: 'available',
    reasonCode: null,
    serviceVersion: '1.0.0',
    contractVersion: '1.0.0',
    allowedActions,
    authorityRevision: 4,
  };
}

test('tenant analytics loader calls loadTenantAnalytics for the tenant scope', async () => {
  const calls = [];
  const result = await analytics.loadTenantAnalyticsCapability(config, {
    async loadTenantAnalytics(input) {
      calls.push(input);
      return snapshot(['view', 'retry']);
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].scope.tenantId, 'tenant-1');
  assert.equal(calls[0].scope.authority, 'cloud');
  assert.equal(result.availability, 'available');
  assert.deepEqual(result.allowed_actions, ['view', 'retry']);
});

test('tenant dashboard loader calls loadTenantAgentDashboard', async () => {
  const calls = [];
  await dashboard.loadTenantAgentDashboardCapability(config, {
    async loadTenantAgentDashboard(input) {
      calls.push(input);
      return snapshot(['view-config', 'refresh']);
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].scope.tenantId, 'tenant-1');
});

test('tenant bindings loader calls listTenantAgentBindings', async () => {
  const calls = [];
  await bindings.loadTenantAgentBindingsCapability(config, {
    async listTenantAgentBindings(input) {
      calls.push(input);
      return snapshot(['view', 'list']);
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].scope.tenantId, 'tenant-1');
});

test('tenant projects loader calls listTenantProjects', async () => {
  const calls = [];
  await projects.loadTenantProjectsCapability(config, {
    async listTenantProjects(input) {
      calls.push(input);
      return snapshot(['view', 'list']);
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].scope.tenantId, 'tenant-1');
  assert.equal(calls[0].scope.authority, 'cloud');
  assert.deepEqual(calls[0].query, { page: 1, pageSize: 1 });
});

test('empty tenant scope does not call the tenant operations', async () => {
  const calls = [];
  const empty = { ...config, tenantId: '  ' };
  const result = await analytics.loadTenantAnalyticsCapability(empty, {
    async loadTenantAnalytics(input) {
      calls.push(input);
      return snapshot(['view', 'retry']);
    },
  });
  assert.equal(calls.length, 0);
  assert.equal(result.availability, 'unavailable');
  assert.equal(result.reason_code, 'tenant_analytics_scope_unavailable');
});
