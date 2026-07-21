/**
 * Shared permission helpers.
 *
 * Keep role/ownership checks in one place so pages do not drift apart.
 */

import type { Tenant, User } from '../types/memory';

/**
 * Whether the user may manage tenant-level agent definitions and bindings.
 * True for admin/owner/system_admin roles and for the tenant owner.
 */
export function canManageTenantAgents(
  user: Pick<User, 'id' | 'roles'> | null | undefined,
  tenant: Pick<Tenant, 'owner_id'> | null | undefined
): boolean {
  const roles = new Set((user?.roles ?? []).map((role) => role.toLowerCase()));
  return (
    roles.has('admin') ||
    roles.has('owner') ||
    roles.has('system_admin') ||
    tenant?.owner_id === user?.id
  );
}
