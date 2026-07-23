import type {
  WorkspaceBindingAgentDefinition,
} from '../../api/client';
import type {
  WorkspaceAgentBinding,
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
} from '../../types';

export function canManageWorkspaceAgentBindings(
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>,
  actorUserId: string,
): boolean {
  const requiredActorUserId = actorUserId.trim();
  return (
    members.status === 'ready' &&
    Boolean(requiredActorUserId) &&
    members.items.some(
      (member) =>
        member.user_id === requiredActorUserId &&
        (member.role === 'owner' || member.role === 'editor'),
    )
  );
}

export function availableWorkspaceAgentDefinitions(
  definitions: WorkspaceBindingAgentDefinition[],
  bindings: WorkspaceAgentBinding[],
): WorkspaceBindingAgentDefinition[] {
  const boundAgentIds = new Set(bindings.map((binding) => binding.agent_id));
  return definitions.filter((definition) => !boundAgentIds.has(definition.id));
}

export function upsertWorkspaceAgentBinding(
  bindings: WorkspaceAgentBinding[],
  incoming: WorkspaceAgentBinding,
): WorkspaceAgentBinding[] {
  const index = bindings.findIndex(
    (binding) =>
      binding.id === incoming.id || binding.agent_id === incoming.agent_id,
  );
  if (index < 0) return [...bindings, incoming];
  return bindings.map((binding, bindingIndex) =>
    bindingIndex === index ? incoming : binding,
  );
}

export function removeWorkspaceAgentBindingById(
  bindings: WorkspaceAgentBinding[],
  bindingId: string,
): WorkspaceAgentBinding[] {
  const requiredBindingId = bindingId.trim();
  if (!requiredBindingId) return bindings;
  const next = bindings.filter((binding) => binding.id !== requiredBindingId);
  return next.length === bindings.length ? bindings : next;
}
