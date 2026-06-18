interface AgentChatTenantScope {
  routeTenantId?: string | null | undefined;
  projectTenantId?: string | null | undefined;
  storeTenantId?: string | null | undefined;
}

export function deriveAgentChatTenantId({
  routeTenantId,
  projectTenantId,
  storeTenantId,
}: AgentChatTenantScope): string {
  return routeTenantId || projectTenantId || storeTenantId || '';
}
