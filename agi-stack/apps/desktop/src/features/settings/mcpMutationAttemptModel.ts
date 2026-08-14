import type { DesktopMCPServerSummary } from '../../api/client';

export function mcpServerRevision(server: DesktopMCPServerSummary): number {
  const revision = server.runtime_metadata?.revision;
  if (typeof revision !== 'number' || !Number.isSafeInteger(revision) || revision < 1) {
    throw new Error('MCP server revision is unavailable');
  }
  return revision;
}

export function mcpToggleAttemptIdentity(
  contextKey: string,
  server: DesktopMCPServerSummary,
): string {
  return JSON.stringify([contextKey, server.id, mcpServerRevision(server), !server.enabled]);
}

export function resolveMCPMutationAttemptKey(
  attempts: Map<string, string>,
  identity: string,
  createKey: () => string,
): string {
  const current = attempts.get(identity);
  if (current) return current;
  const key = createKey();
  attempts.set(identity, key);
  return key;
}

export function retainCurrentMCPToggleAttempts(
  attempts: Map<string, string>,
  contextKey: string,
  servers: readonly DesktopMCPServerSummary[],
): void {
  const currentIdentities = new Set<string>();
  for (const server of servers) {
    try {
      currentIdentities.add(mcpToggleAttemptIdentity(contextKey, server));
    } catch {
      // A malformed server cannot be mutated and must not retain retry authority.
    }
  }
  for (const identity of attempts.keys()) {
    if (!currentIdentities.has(identity)) attempts.delete(identity);
  }
}
