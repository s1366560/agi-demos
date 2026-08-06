import {
  createTenantAdminController,
  type TenantAdminControllerCore,
} from './tenantAdminController';
import type {
  TenantTrustClient,
  TenantTrustPolicyInput,
  TenantTrustScope,
} from './tenantTrustClient';
import {
  buildTenantTrustPresentation,
  type TenantTrustViewModel,
} from './tenantTrustPresentationModel';

export type TenantTrustController = TenantAdminControllerCore<
  TenantTrustScope,
  TenantTrustViewModel
> &
  Readonly<{
    create: (input: TenantTrustPolicyInput) => Promise<void>;
    revoke: (policyId: string) => Promise<void>;
  }>;

export function createTenantTrustController({
  client,
  initialScope,
}: Readonly<{
  client: TenantTrustClient;
  initialScope: TenantTrustScope;
}>): TenantTrustController {
  const core = createTenantAdminController({
    initialScope,
    reasonPrefix: 'tenant_trust',
    loadAuthority: client.load,
    isEmpty: (data) => data.policies.length === 0,
    buildPresentation: buildTenantTrustPresentation,
  });
  return Object.freeze({
    ...core,
    create: (input) =>
      core.runAction('create', async (scope, signal) => {
        await client.create(scope, input, { signal });
      }),
    revoke: (policyId) =>
      core.runAction('revoke', async (scope, signal) => {
        await client.revoke(scope, policyId, { signal });
      }),
  });
}
