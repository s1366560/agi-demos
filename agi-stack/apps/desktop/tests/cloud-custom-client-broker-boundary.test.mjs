import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const desktopRoot = new URL('../', import.meta.url);

const BROKER_BOUND_CLIENTS = [
  'src/features/automations/automationClient.ts',
  'src/features/runtime/workbenchCapabilityClient.ts',
  'src/features/tenant/tenantOverviewHttpClient.ts',
  'src/features/tenant/tenantProjectsHttpClient.ts',
  'src/features/tenant/tenantTasksHttpClient.ts',
  'src/features/tenant/tenantAnalyticsHttpClient.ts',
  'src/features/tenant/tenantAgentBindingsHttpClient.ts',
  'src/features/tenant/tenantAgentDashboardHttpClient.ts',
  'src/features/tenant-admin/tenantAdminHttp.ts',
  'src/features/tenant-admin/tenantManagementHttp.ts',
  'src/features/runtime-pool/runtimePoolClient.ts',
  'src/features/governance/deadLetterQueueHttpClient.ts',
  'src/features/sandbox/sandboxRuntimeSurfaceClient.ts',
  'src/features/sandbox/terminalSessionV2Client.ts',
];

const INJECTABLE_BROKER_CLIENTS = [
  'src/features/device-approval/deviceApprovalClient.ts',
  'src/features/instance-templates/instanceTemplatesClient.ts',
  'src/features/invitation-acceptance/invitationAcceptanceClient.ts',
  'src/features/runtime-clusters/runtimeClustersClient.ts',
  'src/features/runtime-deployments/runtimeDeploymentsClient.ts',
  'src/features/runtime-instances/runtimeInstancesClient.ts',
  'src/features/tenant-creation/tenantCreationClient.ts',
  'src/features/unified-runtimes/unifiedRuntimesClient.ts',
  'src/features/settings-routes/nativeRouteHttpClient.ts',
];

test('Cloud custom clients use the vault-bound fetch adapter instead of renderer fetch', () => {
  for (const path of BROKER_BOUND_CLIENTS) {
    const source = readFileSync(new URL(path, desktopRoot), 'utf8');
    assert.match(source, /from ['"]\.\.\/.*api\/cloudRequestBroker['"]/u, path);
    assert.match(source, /desktopApiFetch\(/u, path);
    assert.doesNotMatch(source, /\bfetch\(/u, path);
  }
});

test('Cloud tenant and terminal gates accept Electron vault authentication without a renderer bearer', () => {
  for (const path of [
    'src/features/tenant-admin/tenantAdminHttp.ts',
    'src/features/tenant-admin/tenantManagementHttp.ts',
    'src/features/sandbox/terminalSessionV2Client.ts',
  ]) {
    const source = readFileSync(new URL(path, desktopRoot), 'utf8');
    assert.match(source, /desktopApiAuthenticationAvailable\(config\)/u, path);
    assert.doesNotMatch(source, /!desktopApiCredential\(config\)|!config\.apiKey\.trim\(\)/u, path);
  }
});

test('injectable Cloud clients default to the vault broker while retaining explicit test transports', () => {
  for (const path of INJECTABLE_BROKER_CLIENTS) {
    const source = readFileSync(new URL(path, desktopRoot), 'utf8');
    assert.match(source, /api\/cloudRequestBroker/u, path);
    assert.match(source, /desktopApiFetch\(/u, path);
  }
});

test('Cloud-only creation, approval, invitation, and settings gates accept vault authentication', () => {
  for (const path of [
    'src/features/device-approval/deviceApprovalClient.ts',
    'src/features/invitation-acceptance/invitationAcceptanceClient.ts',
    'src/features/tenant-creation/tenantCreationClient.ts',
    'src/features/settings-routes/nativeRouteHttpClient.ts',
  ]) {
    const source = readFileSync(new URL(path, desktopRoot), 'utf8');
    assert.match(source, /desktopApiAuthenticationAvailable\(/u, path);
  }
});
