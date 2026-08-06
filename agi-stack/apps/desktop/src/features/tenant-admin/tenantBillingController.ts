import {
  createTenantAdminController,
  type TenantAdminControllerCore,
} from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';
import type { TenantBillingClient, TenantBillingPlan } from './tenantBillingClient';
import {
  buildTenantBillingPresentation,
  type TenantBillingViewModel,
} from './tenantBillingPresentationModel';

export type TenantBillingController = TenantAdminControllerCore<
  TenantAdminScope,
  TenantBillingViewModel
> &
  Readonly<{ upgradePlan: (plan: TenantBillingPlan) => Promise<void> }>;

export function createTenantBillingController({
  client,
  initialScope,
}: Readonly<{
  client: TenantBillingClient;
  initialScope: TenantAdminScope;
}>): TenantBillingController {
  const core = createTenantAdminController({
    initialScope,
    reasonPrefix: 'tenant_billing',
    loadAuthority: client.load,
    isEmpty: () => false,
    buildPresentation: buildTenantBillingPresentation,
  });
  return Object.freeze({
    ...core,
    upgradePlan: (plan) =>
      core.runAction('upgrade-plan', async (scope, signal) => {
        await client.upgradePlan(scope, plan, { signal });
      }),
  });
}
