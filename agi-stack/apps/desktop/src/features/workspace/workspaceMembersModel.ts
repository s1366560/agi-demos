import type { WorkspaceMemberRole } from '../../api/client';
import type {
  WorkspaceAuthorityCollection,
  WorkspaceMemberSummary,
} from '../../types';

export const WORKSPACE_MEMBER_ROLES = [
  'owner',
  'editor',
  'viewer',
] as const satisfies readonly WorkspaceMemberRole[];

export function isWorkspaceMemberRole(
  value: string,
): value is WorkspaceMemberRole {
  return WORKSPACE_MEMBER_ROLES.some((role) => role === value);
}

export function canManageWorkspaceMembers(
  members: WorkspaceAuthorityCollection<WorkspaceMemberSummary>,
  actorUserId: string,
): boolean {
  const requiredActorUserId = actorUserId.trim();
  return (
    members.status === 'ready' &&
    Boolean(requiredActorUserId) &&
    members.items.some(
      (member) =>
        member.user_id === requiredActorUserId && member.role === 'owner',
    )
  );
}

export function upsertWorkspaceMember(
  members: WorkspaceMemberSummary[],
  incoming: WorkspaceMemberSummary,
): WorkspaceMemberSummary[] {
  const index = members.findIndex(
    (member) =>
      member.id === incoming.id || member.user_id === incoming.user_id,
  );
  if (index < 0) return [...members, incoming];
  const existing = members[index];
  const merged = {
    ...existing,
    ...incoming,
    user_email: incoming.user_email ?? existing.user_email,
  };
  return members.map((member, memberIndex) =>
    memberIndex === index ? merged : member,
  );
}

export function removeWorkspaceMemberByUserId(
  members: WorkspaceMemberSummary[],
  userId: string,
): WorkspaceMemberSummary[] {
  const requiredUserId = userId.trim();
  if (!requiredUserId) return members;
  const next = members.filter((member) => member.user_id !== requiredUserId);
  return next.length === members.length ? members : next;
}
