import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const contractRoot = new URL('../contracts/desktop-web-parity/', import.meta.url);

function readCapability(fragmentName, capabilityId) {
  const fragment = JSON.parse(readFileSync(new URL(fragmentName, contractRoot), 'utf8'));
  const capability = fragment.capabilities.find((candidate) => candidate.id === capabilityId);
  assert.ok(capability, `missing capability ${capabilityId}`);
  return capability;
}

function contractKeys(capability, surface) {
  return capability.api_contracts
    .filter((contract) => contract.surface === surface)
    .map((contract) => `${contract.method} ${contract.path}`);
}

test('Tenant Audit records native export while retaining the runtime-hook surface gap', () => {
  const audit = readCapability(
    'parity-capability-definitions.13-tenant-governance-operations.v2.json',
    'tenant-tenant-audit-logs',
  );

  assert.equal(audit.cloud_status, 'partial');
  assert.equal(audit.cloud_reason_code, 'desktop_audit_runtime_hook_surface_incomplete');
  assert.deepEqual(audit.cloud_actions, [
    'view',
    'filter',
    'inspect-runtime-hooks',
    'export',
  ]);
  assert.ok(
    contractKeys(audit, 'desktop_cloud').includes(
      'GET /api/v1/tenants/{tenant_id}/audit-logs/export',
    ),
  );
  assert.match(audit.judgment_rationale, /CSV.*JSON.*native/iu);
  assert.match(audit.judgment_rationale, /runtime-hook/iu);
});

test('Tenant Settings promotes its revision-bound Cloud route', () => {
  const settings = readCapability(
    'parity-capability-definitions.15-organization-governance.v2.json',
    'tenant-tenant-settings',
  );

  assert.equal(settings.cloud_status, 'implemented');
  assert.equal(Object.hasOwn(settings, 'cloud_reason_code'), false);
  assert.deepEqual(settings.cloud_actions, ['view', 'update', 'delete', 'inspect-usage']);
  assert.doesNotMatch(settings.judgment_rationale, /authority_contract_invalid/u);
  assert.match(settings.judgment_rationale, /scope revision/iu);
});
