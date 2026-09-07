import {
  PROJECT_TEAM_DEGRADED_REASON,
  PROJECT_TEAM_LOCAL_REASON,
  type ProjectAgentTeammate,
  type ProjectTeamMember,
  type ProjectTeamRole,
  type ProjectTeamSnapshot,
} from '../features/project-knowledge/projectTeamClient';
import {
  isRecord,
  observeProjectKnowledgeScope,
  optionalText,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectKnowledgeScope,
  requireText,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectTeamRuntimeConfigV2,
  cloneDesktopProjectTeamScopeV2,
} from './desktopProjectTeamOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list-members', 'list-agent-teammates']);
const ROLES_V2 = new Set<ProjectTeamRole>(['owner', 'admin', 'member', 'editor', 'viewer']);

export type DesktopProjectTeamHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectTeamSnapshot>;
}>;

export function createDesktopProjectTeamHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): DesktopProjectTeamHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectTeamRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectTeamScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_TEAM_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(runtimeConfig, currentScope, {
        signal,
      });
      const [mePayload, membersPayload, agentsPayload] = await Promise.all([
        requestProjectKnowledgeJson(runtimeConfig, '/api/v1/auth/me', { signal }),
        requestProjectKnowledgeJson(runtimeConfig, membersPathV2(currentScope), { signal }),
        requestProjectKnowledgeJson(runtimeConfig, agentsPathV2(currentScope), { signal }),
      ]);
      const currentUserId = parseCurrentUserIdV2(mePayload);
      const members = parseMembersV2(membersPayload);
      const currentUser = members.find((member) => member.userId === currentUserId);
      if (currentUser === undefined) {
        throw projectKnowledgeError('project_team_current_membership_missing', 403);
      }
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_TEAM_DEGRADED_REASON,
        allowedActions: ACTIONS_V2,
        members,
        agents: parseAgentsV2(agentsPayload, currentScope.projectId),
        currentUserRole: currentUser.role,
      });
    },
  });
}

function membersPathV2(scope: ProjectKnowledgeScope): string {
  return `/api/v1/projects/${encodeURIComponent(scope.projectId)}/members`;
}

function agentsPathV2(scope: ProjectKnowledgeScope): string {
  return (
    '/api/v1/agent/definitions?include_total=true&limit=50&offset=0' +
    `&tenant_id=${encodeURIComponent(scope.tenantId)}` +
    `&project_id=${encodeURIComponent(scope.projectId)}`
  );
}

function parseCurrentUserIdV2(payload: unknown): string {
  if (!isRecord(payload)) {
    throw projectKnowledgeError('project_team_current_user_contract_invalid');
  }
  return requireIdentifier(
    payload.id ?? payload.user_id,
    'project_team_current_user_contract_invalid',
  );
}

function parseMembersV2(payload: unknown): readonly ProjectTeamMember[] {
  if (!isRecord(payload) || !Array.isArray(payload.members)) {
    throw projectKnowledgeError('project_team_members_contract_invalid');
  }
  const members = Object.freeze(payload.members.map(parseMemberV2));
  if (
    payload.total !== undefined &&
    requireNonnegativeInteger(payload.total, 'project_team_members_contract_invalid') !==
      members.length
  ) {
    throw projectKnowledgeError('project_team_members_contract_invalid');
  }
  return members;
}

function parseMemberV2(value: unknown): ProjectTeamMember {
  if (!isRecord(value) || !isRecord(value.permissions)) {
    throw projectKnowledgeError('project_team_member_contract_invalid');
  }
  return Object.freeze({
    userId: requireIdentifier(value.user_id, 'project_team_member_contract_invalid'),
    email: requireIdentifier(value.email, 'project_team_member_contract_invalid'),
    name: optionalText(value.name, 'project_team_member_contract_invalid'),
    role: requireRoleV2(value.role),
    permissions: Object.freeze({ ...value.permissions }),
    createdAt: requireIdentifier(value.created_at, 'project_team_member_contract_invalid'),
  });
}

function parseAgentsV2(payload: unknown, projectId: string): readonly ProjectAgentTeammate[] {
  const values = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.definitions)
      ? payload.definitions
      : isRecord(payload) && Array.isArray(payload.items)
        ? payload.items
        : null;
  if (values === null) throw projectKnowledgeError('project_team_agents_contract_invalid');
  if (
    isRecord(payload) &&
    payload.total !== undefined &&
    requireNonnegativeInteger(payload.total, 'project_team_agents_contract_invalid') < values.length
  ) {
    throw projectKnowledgeError('project_team_agents_contract_invalid');
  }
  return Object.freeze(values.map((value) => parseAgentV2(value, projectId)));
}

function parseAgentV2(value: unknown, projectId: string): ProjectAgentTeammate {
  if (!isRecord(value)) throw projectKnowledgeError('project_team_agent_contract_invalid');
  if (value.project_id !== undefined && value.project_id !== projectId) {
    throw projectKnowledgeError('project_team_agent_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'project_team_agent_contract_invalid'),
    name: requireIdentifier(
      value.display_name ?? value.name,
      'project_team_agent_contract_invalid',
    ),
    enabled: requireBooleanV2(value.enabled, 'project_team_agent_contract_invalid'),
    model: optionalText(value.model, 'project_team_agent_contract_invalid'),
  });
}

function requireRoleV2(value: unknown): ProjectTeamRole {
  if (typeof value !== 'string' || !ROLES_V2.has(value as ProjectTeamRole)) {
    throw projectKnowledgeError('project_team_role_contract_invalid');
  }
  return value as ProjectTeamRole;
}

function requireBooleanV2(value: unknown, reasonCode: string): boolean {
  if (typeof value !== 'boolean') throw projectKnowledgeError(reasonCode);
  return value;
}
