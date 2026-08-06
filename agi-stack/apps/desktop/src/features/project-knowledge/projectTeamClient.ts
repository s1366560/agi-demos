import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  observeProjectKnowledgeScope,
  optionalText,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requestProjectKnowledgeNoContent,
  requireIdentifier,
  requireNonnegativeInteger,
  requireProjectKnowledgeScope,
  requireText,
  type ProjectKnowledgeClient,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_TEAM_ROUTE_ID = 'project-project-team' as const;
export const PROJECT_TEAM_LOCAL_REASON = 'local_project_team_authority_unavailable' as const;

export type ProjectTeamRole = 'owner' | 'admin' | 'member' | 'editor' | 'viewer';
export type ProjectTeamMember = Readonly<{
  userId: string;
  email: string;
  name: string | null;
  role: ProjectTeamRole;
  permissions: Readonly<Record<string, unknown>>;
  createdAt: string;
}>;
export type ProjectAgentTeammate = Readonly<{
  id: string;
  name: string;
  enabled: boolean;
  model: string | null;
}>;
export type ProjectTeamSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{
    members: readonly ProjectTeamMember[];
    agents: readonly ProjectAgentTeammate[];
    currentUserRole: ProjectTeamRole;
  }>;
export type ProjectTeamClient = ProjectKnowledgeClient<ProjectTeamSnapshot> &
  Readonly<{
    invite(
      scope: ProjectKnowledgeScope,
      input: Readonly<{ email: string; role: ProjectTeamRole; message?: string }>,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<void>;
    updateRole(
      scope: ProjectKnowledgeScope,
      userId: string,
      role: ProjectTeamRole,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<void>;
    removeMember(
      scope: ProjectKnowledgeScope,
      userId: string,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<void>;
    startAgentChat(
      scope: ProjectKnowledgeScope,
      agentId: string,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<string>;
  }>;

const ROLES = new Set<ProjectTeamRole>(['owner', 'admin', 'member', 'editor', 'viewer']);
const READ_ACTIONS = Object.freeze(['view', 'list-members', 'list-agent-teammates']);
const ADMIN_ACTIONS = Object.freeze([...READ_ACTIONS, 'invite', 'update-role', 'remove']);
const OWNER_ACTIONS = Object.freeze([...ADMIN_ACTIONS, 'start-agent-chat']);

export function createProjectTeamClient(config: DesktopRuntimeConfig): ProjectTeamClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ProjectTeamClient = {
    async load(scope, options) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        scope,
        PROJECT_TEAM_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(
        runtimeConfig,
        currentScope,
        options,
      );
      const [mePayload, membersPayload, agentsPayload] = await Promise.all([
        requestProjectKnowledgeJson(runtimeConfig, '/api/v1/auth/me', options),
        requestProjectKnowledgeJson(runtimeConfig, membersPath(currentScope), options),
        requestProjectKnowledgeJson(runtimeConfig, agentsPath(currentScope), options),
      ]);
      const currentUserId = parseCurrentUserId(mePayload);
      const members = parseMembers(membersPayload);
      const currentUser = members.find((member) => member.userId === currentUserId);
      if (!currentUser) throw projectKnowledgeError('project_team_current_membership_missing', 403);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: actionsForRole(currentUser.role),
        members,
        agents: parseAgents(agentsPayload, currentScope.projectId),
        currentUserRole: currentUser.role,
      });
    },
    async invite(scope, input, options) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        scope,
        PROJECT_TEAM_LOCAL_REASON,
      );
      await requestProjectKnowledgeJson(
        runtimeConfig,
        `/api/v1/tenants/${encodeURIComponent(currentScope.tenantId)}/invitations`,
        {
          ...options,
          method: 'POST',
          body: {
            email: requireIdentifier(input.email, 'project_team_invitation_email_required'),
            role: requireRole(input.role),
            ...(input.message?.trim() ? { message: input.message.trim() } : {}),
          },
        },
      );
    },
    async updateRole(scope, userId, role, options) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        scope,
        PROJECT_TEAM_LOCAL_REASON,
      );
      await requestProjectKnowledgeJson(
        runtimeConfig,
        memberPath(currentScope, userId),
        { ...options, method: 'PATCH', body: { role: requireRole(role) } },
      );
    },
    async removeMember(scope, userId, options) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        scope,
        PROJECT_TEAM_LOCAL_REASON,
      );
      await requestProjectKnowledgeNoContent(
        runtimeConfig,
        memberPath(currentScope, userId),
        { ...options, method: 'DELETE' },
      );
    },
    async startAgentChat(scope, agentId, options) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        scope,
        PROJECT_TEAM_LOCAL_REASON,
      );
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        '/api/v1/agent/conversations',
        {
          ...options,
          method: 'POST',
          body: {
            project_id: currentScope.projectId,
            title: requireIdentifier(agentId, 'project_team_agent_id_required'),
            agent_config: { selected_agent_id: agentId },
          },
        },
      );
      if (!isRecord(payload)) {
        throw projectKnowledgeError('project_team_conversation_contract_invalid');
      }
      return requireIdentifier(payload.id, 'project_team_conversation_contract_invalid');
    },
  };
  return Object.freeze(client);
}

function membersPath(scope: ProjectKnowledgeScope): string {
  return `/api/v1/projects/${encodeURIComponent(scope.projectId)}/members`;
}

function memberPath(scope: ProjectKnowledgeScope, userId: string): string {
  const id = requireIdentifier(userId, 'project_team_member_id_required');
  return `${membersPath(scope)}/${encodeURIComponent(id)}`;
}

function agentsPath(scope: ProjectKnowledgeScope): string {
  return (
    '/api/v1/agent/definitions?include_total=true&limit=50&offset=0' +
    `&tenant_id=${encodeURIComponent(scope.tenantId)}` +
    `&project_id=${encodeURIComponent(scope.projectId)}`
  );
}

function parseCurrentUserId(payload: unknown): string {
  if (!isRecord(payload)) throw projectKnowledgeError('project_team_current_user_contract_invalid');
  return requireIdentifier(
    payload.id ?? payload.user_id,
    'project_team_current_user_contract_invalid',
  );
}

function parseMembers(payload: unknown): readonly ProjectTeamMember[] {
  if (!isRecord(payload) || !Array.isArray(payload.members)) {
    throw projectKnowledgeError('project_team_members_contract_invalid');
  }
  const members = Object.freeze(payload.members.map(parseMember));
  if (
    payload.total !== undefined &&
    requireNonnegativeInteger(payload.total, 'project_team_members_contract_invalid') !==
      members.length
  ) {
    throw projectKnowledgeError('project_team_members_contract_invalid');
  }
  return members;
}

function parseMember(value: unknown): ProjectTeamMember {
  if (!isRecord(value) || !isRecord(value.permissions)) {
    throw projectKnowledgeError('project_team_member_contract_invalid');
  }
  return Object.freeze({
    userId: requireIdentifier(value.user_id, 'project_team_member_contract_invalid'),
    email: requireText(value.email, 'project_team_member_contract_invalid'),
    name: optionalText(value.name, 'project_team_member_contract_invalid'),
    role: requireRole(value.role),
    permissions: Object.freeze({ ...value.permissions }),
    createdAt: requireText(value.created_at, 'project_team_member_contract_invalid'),
  });
}

function parseAgents(payload: unknown, projectId: string): readonly ProjectAgentTeammate[] {
  const values = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.definitions)
      ? payload.definitions
      : isRecord(payload) && Array.isArray(payload.items)
        ? payload.items
        : null;
  if (!values) throw projectKnowledgeError('project_team_agents_contract_invalid');
  return Object.freeze(
    values.map((value) => {
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
        enabled: value.enabled === true,
        model: optionalText(value.model, 'project_team_agent_contract_invalid'),
      });
    }),
  );
}

function requireRole(value: unknown): ProjectTeamRole {
  if (typeof value !== 'string' || !ROLES.has(value as ProjectTeamRole)) {
    throw projectKnowledgeError('project_team_role_contract_invalid');
  }
  return value as ProjectTeamRole;
}

function actionsForRole(role: ProjectTeamRole): readonly string[] {
  if (role === 'owner') return OWNER_ACTIONS;
  if (role === 'admin') return ADMIN_ACTIONS;
  return READ_ACTIONS;
}
