import {
  createTenantAdminController,
  type TenantAdminControllerCore,
} from './tenantAdminController';
import type { TenantAdminScope } from './tenantAdminHttp';
import type {
  TenantGovernanceClient,
  TenantInvitationInput,
  TenantMemberRole,
} from './tenantGovernanceClient';
import {
  buildTenantGovernancePresentation,
  type TenantGovernanceViewModel,
} from './tenantGovernancePresentationModel';

export type TenantGovernanceController = TenantAdminControllerCore<
  TenantAdminScope,
  TenantGovernanceViewModel
> &
  Readonly<{
    invite: (input: TenantInvitationInput) => Promise<void>;
    changeRole: (userId: string, role: TenantMemberRole) => Promise<void>;
    removeMember: (userId: string) => Promise<void>;
  }>;

export function createTenantGovernanceController({
  client,
  initialScope,
}: Readonly<{
  client: TenantGovernanceClient;
  initialScope: TenantAdminScope;
}>): TenantGovernanceController {
  const core = createTenantAdminController({
    initialScope,
    reasonPrefix: 'tenant_governance',
    loadAuthority: client.load,
    isEmpty: (data) => data.members.length === 0,
    buildPresentation: buildTenantGovernancePresentation,
  });
  return Object.freeze({
    ...core,
    invite: (input) =>
      core.runAction('invite', async (scope, signal) => {
        await client.invite(scope, input, { signal });
      }),
    changeRole: (userId, role) =>
      core.runAction('change-role', (scope, signal) =>
        client.changeRole(scope, userId, role, { signal }),
      ),
    removeMember: (userId) =>
      core.runAction('remove-member', (scope, signal) =>
        client.removeMember(scope, userId, { signal }),
      ),
  });
}
