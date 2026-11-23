import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const desktopRoot = new URL('../', import.meta.url);

const BROKER_BOUND_CLIENTS = [
  '../../../plugins/business/automation/ui/desktop/automations/automationClient.ts',
  'src/features/runtime/workbenchCapabilityClient.ts',
  'src/plugins/desktopTenantOverviewAuthorityModuleV2.ts',
  'src/plugins/desktopTenantProjectsAuthorityModuleV2.ts',
  'src/plugins/desktopTenantTasksAuthorityModuleV2.ts',
  'src/plugins/desktopTenantAnalyticsAuthorityModuleV2.ts',
  'src/plugins/desktopTenantAgentDashboardAuthorityModuleV2.ts',
  'src/plugins/desktopTenantAgentBindingsAuthorityModuleV2.ts',
  'src/plugins/desktopTenantCreationHttpProjectionV2.ts',
  'src/features/tenant-admin/tenantAdminHttp.ts',
  'src/features/tenant-admin/tenantManagementHttp.ts',
  '../../../plugins/business/environments/ui/desktop/runtime-pool/runtimePoolClient.ts',
  'src/plugins/desktopRuntimeClustersHttpProjectionV2.ts',
  'src/plugins/desktopRuntimeInstancesHttpProjectionV2.ts',
  'src/plugins/desktopRuntimeDeploymentsHttpProjectionV2.ts',
  'src/plugins/desktopDeadLetterQueueHttpProjectionV2.ts',
  'src/plugins/desktopProjectSandboxSurfaceHttpProjectionV2.ts',
  '../../../plugins/business/environments/ui/desktop/sandbox/terminalSessionV2Client.ts',
];

const INJECTABLE_BROKER_CLIENTS = [
  'src/features/device-approval/deviceApprovalClient.ts',
  'src/plugins/desktopInstanceTemplatesHttpProjectionV2.ts',
  'src/features/invitation-acceptance/invitationAcceptanceClient.ts',
  '../../../plugins/business/environments/ui/desktop/unified-runtimes/unifiedRuntimesClient.ts',
  'src/features/settings-routes/nativeRouteHttpClient.ts',
];

test('Cloud custom clients use the vault-bound fetch adapter instead of renderer fetch', () => {
  for (const path of BROKER_BOUND_CLIENTS) {
    const source = readFileSync(new URL(path, desktopRoot), 'utf8');
    assert.match(source, /from ['"](?:\.\.\/.*|@desktop\/)api\/cloudRequestBroker['"]/u, path);
    assert.match(source, /desktopApiFetch\(/u, path);
    assert.doesNotMatch(source, /\bfetch\(/u, path);
  }
});

test('Cloud tenant and terminal gates accept Electron vault authentication without a renderer bearer', () => {
  for (const path of [
    'src/features/tenant-admin/tenantAdminHttp.ts',
    'src/features/tenant-admin/tenantManagementHttp.ts',
    '../../../plugins/business/environments/ui/desktop/sandbox/terminalSessionV2Client.ts',
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
    'src/plugins/desktopTenantCreationHttpProjectionV2.ts',
    'src/features/settings-routes/nativeRouteHttpClient.ts',
  ]) {
    const source = readFileSync(new URL(path, desktopRoot), 'utf8');
    assert.match(source, /desktopApiAuthenticationAvailable\(/u, path);
  }
});

test('Sandbox surface wrappers contain no retired HTTP transport fallback', () => {
  for (const path of [
    '../../../plugins/business/environments/ui/desktop/sandbox/sandboxRuntimeClient.ts',
    '../../../plugins/business/environments/ui/desktop/sandbox/sandboxRuntimeSurfaceClient.ts',
  ]) {
    const source = readFileSync(new URL(path, desktopRoot), 'utf8');
    assert.doesNotMatch(source, /\b(?:desktopApiFetch|fetch|DesktopRuntimeConfig)\b/u, path);
  }
});
