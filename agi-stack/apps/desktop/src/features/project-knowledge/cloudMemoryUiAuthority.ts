import { validCloudMemoryCapabilitySnapshot } from './cloudMemoryCapabilities';
import type { CloudMemoryCapabilities } from './cloudMemoryCapabilities';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import type { ProjectMemoriesSnapshot, ProjectMemory } from './projectMemoriesClient';

export type CloudMemoryUiAuthority = Readonly<{
  scope: ProjectKnowledgeScope;
  actorId: string | null;
  sessionId: string | null;
  contextRevision: number | null;
  generationDigest: string | null;
  available: boolean;
  allowedActions: readonly string[];
}>;
export function validCloudMemoryUiAuthority(authority: CloudMemoryUiAuthority): boolean {
  const identifier = (value: string | null) =>
    typeof value === 'string' && value.length > 0 && value.trim() === value;
  return Boolean(
    authority.available &&
    authority.scope.authority === 'cloud' &&
    identifier(authority.actorId) &&
    identifier(authority.sessionId) &&
    identifier(authority.generationDigest) &&
    identifier(authority.scope.tenantId) &&
    identifier(authority.scope.projectId) &&
    Number.isSafeInteger(authority.contextRevision) &&
    Number(authority.contextRevision) >= 0,
  );
}
export function cloudMemoryUiCapabilities(
  authority: CloudMemoryUiAuthority,
  snapshot: ProjectMemoriesSnapshot | null,
): CloudMemoryCapabilities | null {
  if (
    !validCloudMemoryUiAuthority(authority) ||
    !snapshot ||
    snapshot.authority !== 'cloud' ||
    snapshot.scope.authority !== 'cloud' ||
    snapshot.scope.tenantId !== authority.scope.tenantId ||
    snapshot.scope.projectId !== authority.scope.projectId ||
    snapshot.scopeRevision !== authority.contextRevision
  )
    return null;
  const value = snapshot.commandCapabilities;
  if (
    !value ||
    !validCloudMemoryCapabilitySnapshot(value, authority.scope, snapshot.memories) ||
    value.actorId !== authority.actorId
  )
    return null;
  return value;
}
export function cloudMemoryRowAction(
  capabilities: CloudMemoryCapabilities | null,
  memory: ProjectMemory,
  action: 'update' | 'delete',
): boolean {
  return (
    capabilities?.objects.some(
      (object) =>
        object.memoryId === memory.id &&
        object.revision === memory.version &&
        object.allowedActions.includes(action),
    ) ?? false
  );
}
export function checkCloudMemoryList(
  authority: CloudMemoryUiAuthority,
  snapshot: ProjectMemoriesSnapshot,
): void {
  if (
    snapshot.authority !== 'cloud' ||
    snapshot.scope.authority !== 'cloud' ||
    snapshot.scope.tenantId !== authority.scope.tenantId ||
    snapshot.scope.projectId !== authority.scope.projectId ||
    snapshot.scopeRevision !== authority.contextRevision ||
    snapshot.memories.some((memory) => memory.projectId !== authority.scope.projectId)
  )
    throw Error('cloud_memory_ui_scope_conflict');
}
