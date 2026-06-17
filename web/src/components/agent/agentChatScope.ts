interface AgentChatTenantScope {
  routeTenantId?: string | null | undefined;
  projectTenantId?: string | null | undefined;
}

export function deriveAgentChatTenantId({
  routeTenantId,
  projectTenantId,
}: AgentChatTenantScope): string {
  return routeTenantId || projectTenantId || '';
}
