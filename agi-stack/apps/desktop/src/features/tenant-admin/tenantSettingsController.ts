import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';
import type { TenantSettingsClient, TenantSettingsUpdate } from './tenantSettingsClient';
import {
  buildTenantSettingsPresentation,
  type TenantSettingsViewModel,
} from './tenantSettingsPresentationModel';

export type TenantSettingsController = TenantManagementControllerCore<
  TenantManagementScope,
  TenantSettingsViewModel
> &
  Readonly<{
    updateTenant: (input: TenantSettingsUpdate) => Promise<void>;
    deleteTenant: () => Promise<void>;
  }>;

export function createTenantSettingsController({
  client,
  initialScope,
}: Readonly<{
  client: TenantSettingsClient;
  initialScope: TenantManagementScope;
}>): TenantSettingsController {
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_settings',
    loadAuthority: client.load,
    isEmpty: () => false,
    buildPresentation: buildTenantSettingsPresentation,
  });
  return Object.freeze({
    ...core,
    updateTenant: (input) =>
      core.runAction('update', async (scope, signal) => {
        await client.updateTenant(scope, input, { signal });
      }),
    deleteTenant: () =>
      core.runAction('delete', (scope, signal) => client.deleteTenant(scope, { signal })),
  });
}
