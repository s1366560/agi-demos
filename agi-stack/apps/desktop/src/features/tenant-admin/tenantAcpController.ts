import type { TenantAcpAgentInput, TenantAcpClient, TenantAcpTestInput } from './tenantAcpClient';
import {
  buildTenantAcpPresentation,
  type TenantAcpViewModel,
} from './tenantAcpPresentationModel';
import {
  createTenantManagementController,
  type TenantManagementControllerCore,
} from './tenantManagementController';
import type { TenantManagementScope } from './tenantManagementHttp';

export type TenantAcpController = TenantManagementControllerCore<
  TenantManagementScope,
  TenantAcpViewModel
> &
  Readonly<{
    createAgent: (input: TenantAcpAgentInput & Readonly<{ agentKey: string }>) => Promise<void>;
    updateAgent: (agentKey: string, input: TenantAcpAgentInput) => Promise<void>;
    deleteAgent: (agentKey: string) => Promise<void>;
    testAgent: (agentKey: string, input: TenantAcpTestInput) => Promise<void>;
  }>;

export function createTenantAcpController({
  client,
  initialScope,
}: Readonly<{ client: TenantAcpClient; initialScope: TenantManagementScope }>): TenantAcpController {
  const core = createTenantManagementController({
    initialScope,
    reasonPrefix: 'tenant_acp',
    loadAuthority: client.load,
    isEmpty: (data) => data.status.agents.length === 0 && data.runnerPools.length === 0,
    buildPresentation: buildTenantAcpPresentation,
  });
  return Object.freeze({
    ...core,
    createAgent: (input) =>
      core.runAction('create-agent', async (scope, signal) => {
        await client.createAgent(scope, input, { signal });
      }),
    updateAgent: (agentKey, input) =>
      core.runAction('update-agent', async (scope, signal) => {
        await client.updateAgent(scope, agentKey, input, { signal });
      }),
    deleteAgent: (agentKey) =>
      core.runAction('delete-agent', (scope, signal) =>
        client.deleteAgent(scope, agentKey, { signal }),
      ),
    testAgent: (agentKey, input) =>
      core.runAction('test-agent', async (scope, signal) => {
        await client.testAgent(scope, agentKey, input, { signal });
      }),
  });
}
