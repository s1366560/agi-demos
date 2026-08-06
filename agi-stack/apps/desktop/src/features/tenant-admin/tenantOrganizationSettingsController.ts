import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type {
  TenantGenePolicyInput,
  TenantOrganizationSettingsClient,
  TenantRegistryInput,
  TenantSmtpInput,
} from './tenantOrganizationSettingsClient';
import {
  buildTenantOrganizationSettingsPresentation,
  type TenantOrganizationSettingsViewModel,
} from './tenantOrganizationSettingsPresentationModel';

export type TenantOrganizationSettingsController = TenantManagementControllerCore<
  TenantManagementScope,
  TenantOrganizationSettingsViewModel
> &
  Readonly<{
    saveRegistry: (input: TenantRegistryInput) => Promise<void>;
    deleteRegistry: (registryId: string) => Promise<void>;
    testRegistry: (registryId: string) => Promise<void>;
    saveSmtp: (input: TenantSmtpInput) => Promise<void>;
    deleteSmtp: () => Promise<void>;
    testSmtp: (recipientEmail: string) => Promise<void>;
    saveGenePolicy: (input: TenantGenePolicyInput) => Promise<void>;
    deleteGenePolicy: (policyKey: string) => Promise<void>;
  }>;

export function createTenantOrganizationSettingsController({
  client,
  initialScope,
}: Readonly<{
  client: TenantOrganizationSettingsClient;
  initialScope: TenantManagementScope;
}>): TenantOrganizationSettingsController {
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_org_settings',
    loadAuthority: client.load,
    isEmpty: () => false,
    buildPresentation: buildTenantOrganizationSettingsPresentation,
  });
  return Object.freeze({
    ...core,
    saveRegistry: (input) => core.runAction('manage-registries', async (scope, signal) => {
      await client.saveRegistry(scope, input, { signal });
    }),
    deleteRegistry: (registryId) => core.runAction('manage-registries', (scope, signal) =>
      client.deleteRegistry(scope, registryId, { signal })),
    testRegistry: (registryId) => core.runAction('manage-registries', async (scope, signal) => {
      await client.testRegistry(scope, registryId, { signal });
    }),
    saveSmtp: (input) => core.runAction('update-smtp', async (scope, signal) => {
      await client.saveSmtp(scope, input, { signal });
    }),
    deleteSmtp: () => core.runAction('delete-smtp', (scope, signal) =>
      client.deleteSmtp(scope, { signal })),
    testSmtp: (recipientEmail) => core.runAction('test-smtp', async (scope, signal) => {
      await client.testSmtp(scope, recipientEmail, { signal });
    }),
    saveGenePolicy: (input) => core.runAction('manage-gene-policies', async (scope, signal) => {
      await client.saveGenePolicy(scope, input, { signal });
    }),
    deleteGenePolicy: (policyKey) => core.runAction('manage-gene-policies', (scope, signal) =>
      client.deleteGenePolicy(scope, policyKey, { signal })),
  });
}
