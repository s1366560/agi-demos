import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type { TenantGovernanceSnapshot, TenantInvitation, TenantInvitationInput, TenantMemberRole } from '../features/tenant-admin/tenantGovernanceClient';
import type { TenantAdminScope } from '../features/tenant-admin/tenantAdminHttp';

export type DesktopTenantGovernanceInputV2 = Readonly<{ config: DesktopRuntimeConfig; scope: TenantAdminScope; signal?: AbortSignal }>;
export type DesktopTenantGovernanceInviteInputV2 = DesktopTenantGovernanceInputV2 & Readonly<{ invitation: TenantInvitationInput }>;
export type DesktopTenantGovernanceMemberInputV2 = DesktopTenantGovernanceInputV2 & Readonly<{ userId: string }>;
export type DesktopTenantGovernanceRoleInputV2 = DesktopTenantGovernanceMemberInputV2 & Readonly<{ role: TenantMemberRole }>;
const CONFIG_KEYS = ['apiBaseUrl', 'deviceAuthorizationBaseUrl', 'apiKey', 'localApiToken', 'tenantId', 'projectId', 'workspaceId', 'mode', 'workspaceRoot'] as const;
const ROLES = new Set(['owner', 'admin', 'member', 'editor', 'viewer']);

export function prepareTenantGovernanceInputV2(input: DesktopTenantGovernanceInputV2) { return Object.freeze(common(input)); }
export function prepareTenantGovernanceInviteV2(input: DesktopTenantGovernanceInviteInputV2) {
  const prepared = common(input); if (!record(input.invitation)) throw invalidInput();
  const email = text(input.invitation.email); const role = memberRole(input.invitation.role);
  const message = input.invitation.message; if (message !== undefined && (typeof message !== 'string' || message !== message.trim())) throw invalidInput();
  return Object.freeze({ ...prepared, invitation: Object.freeze({ email, role, ...(message === undefined ? {} : { message }) }) });
}
export function prepareTenantGovernanceMemberV2(input: DesktopTenantGovernanceMemberInputV2) { return Object.freeze({ ...common(input), userId: text(input.userId) }); }
export function prepareTenantGovernanceRoleV2(input: DesktopTenantGovernanceRoleInputV2) { return Object.freeze({ ...common(input), userId: text(input.userId), role: memberRole(input.role) }); }
export function freezeTenantGovernanceConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  if (!record(config) || Object.keys(config).length !== CONFIG_KEYS.length || CONFIG_KEYS.some((key) => !Object.hasOwn(config, key)) || (config.mode !== 'cloud' && config.mode !== 'local')) throw invalidInput();
  for (const key of CONFIG_KEYS) if (key !== 'mode' && typeof config[key] !== 'string') throw invalidInput(); text(config.tenantId); return Object.freeze({ ...config });
}
export function requireTenantGovernanceSnapshotV2(value: unknown, scope: TenantAdminScope): TenantGovernanceSnapshot {
  if (!record(value) || !record(value.scope) || value.scope.authority !== scope.authority || value.scope.tenantId !== scope.tenantId || value.authority !== 'cloud' || value.availability !== 'available' || value.reasonCode !== null || value.contractVersion !== '4.0.0' || !Array.isArray(value.allowedActions) || !record(value.data) || value.members !== value.data.members || value.invitations !== value.data.invitations || value.membershipRole !== value.data.membershipRole || value.pendingInvitationTotal !== value.data.pendingInvitationTotal || !Array.isArray(value.members) || !Array.isArray(value.invitations)) throw invalidResponse();
  return value as unknown as TenantGovernanceSnapshot;
}
export function requireTenantGovernanceInvitationV2(value: unknown, tenantId: string): TenantInvitation {
  if (!record(value) || value.tenantId !== tenantId || !ROLES.has(value.role as string) || ['id','email','status','invitedBy','expiresAt','createdAt'].some((key) => typeof value[key] !== 'string' || !value[key])) throw invalidResponse();
  return value as unknown as TenantInvitation;
}
function common(input: DesktopTenantGovernanceInputV2) { if (!record(input)) throw invalidInput(); const config = freezeTenantGovernanceConfigV2(input.config); if (!record(input.scope) || Object.keys(input.scope).length !== 2 || input.scope.authority !== config.mode || input.scope.tenantId !== config.tenantId) throw invalidInput(); if (input.signal !== undefined && (!record(input.signal) || typeof input.signal.aborted !== 'boolean' || typeof input.signal.addEventListener !== 'function')) throw invalidInput(); return { config, scope: Object.freeze({ ...input.scope }), ...(input.signal === undefined ? {} : { signal: input.signal }) }; }
function memberRole(value: unknown): TenantMemberRole { if (typeof value !== 'string' || !ROLES.has(value)) throw invalidInput(); return value as TenantMemberRole; }
function text(value: unknown): string { if (typeof value !== 'string' || !value || value !== value.trim()) throw invalidInput(); return value; }
function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function invalidInput() { return new RuntimeV2Error('desktop_tenant_governance_operation_input_invalid', 'desktop tenant governance operation input invalid'); }
function invalidResponse() { return new RuntimeV2Error('desktop_tenant_governance_operation_response_invalid', 'desktop tenant governance operation response invalid'); }
