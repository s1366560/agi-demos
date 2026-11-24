import { expect, it } from 'vitest';

import { useAgentV3Store } from '@business/agent/ui/web/stores/agentV3';
import { useConversationsStore } from '@business/agent/ui/web/stores/agent/conversationsStore';
import { useSandboxStore } from '@business/environments/ui/web/stores/sandbox';
import { retireTenantScope } from '../../core/tenantScopeLifecycle';

it('retires loaded conversation state and sandbox sessions together on a scope change', async () => {
  const generation = useAgentV3Store.getState().conversationScopeGeneration;
  useAgentV3Store.setState({ activeConversationId: 'old-conversation' });
  useConversationsStore.setState({ conversationsTotal: 17 });
  useSandboxStore.setState({ activeProjectId: 'old-project' });

  await retireTenantScope();

  expect(useAgentV3Store.getState().conversationScopeGeneration).toBe(generation + 1);
  expect(useAgentV3Store.getState().activeConversationId).toBeNull();
  expect(useConversationsStore.getState().conversationsTotal).toBe(0);
  expect(useSandboxStore.getState().activeProjectId).toBeNull();
});
