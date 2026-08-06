import type { DesktopRuntimeConfig } from '../../types';
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
  type ProjectKnowledgeClient,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';
import type { ProjectEntity } from './projectEntitiesClient';

export const PROJECT_COMMUNITIES_ROUTE_ID = 'project-project-communities' as const;
export const PROJECT_COMMUNITIES_LOCAL_REASON =
  'local_project_communities_authority_unavailable' as const;
export const PROJECT_COMMUNITIES_DEGRADED_REASON =
  'project_communities_trusted_task_stream_unavailable' as const;

export type ProjectCommunity = Readonly<{
  id: string;
  name: string;
  summary: string;
  memberCount: number;
  projectId: string | null;
  createdAt: string | null;
}>;
export type ProjectCommunitiesSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{ communities: readonly ProjectCommunity[]; total: number }>;
export type ProjectCommunitiesClient = ProjectKnowledgeClient<ProjectCommunitiesSnapshot> &
  Readonly<{
    members(
      scope: ProjectKnowledgeScope,
      communityId: string,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<readonly ProjectEntity[]>;
    rebuild(
      scope: ProjectKnowledgeScope,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<string>;
    cancel(
      scope: ProjectKnowledgeScope,
      taskId: string,
      options?: ProjectKnowledgeReadOptions,
    ): Promise<void>;
  }>;

const ACTIONS = Object.freeze(['view', 'list', 'inspect-members', 'rebuild', 'cancel-rebuild']);

export function createProjectCommunitiesClient(
  config: DesktopRuntimeConfig,
): ProjectCommunitiesClient {
  const runtimeConfig = Object.freeze({ ...config });
  const withScope = (scope: ProjectKnowledgeScope) =>
    requireProjectKnowledgeScope(runtimeConfig, scope, PROJECT_COMMUNITIES_LOCAL_REASON);
  const client: ProjectCommunitiesClient = {
    async load(scope, options) {
      const currentScope = withScope(scope);
      const scopeRevision = await observeProjectKnowledgeScope(
        runtimeConfig,
        currentScope,
        options,
      );
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        communityListPath(currentScope),
        options,
      );
      const page = parseCommunityPage(payload, currentScope.projectId);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_COMMUNITIES_DEGRADED_REASON,
        allowedActions: ACTIONS,
        ...page,
      });
    },
    async members(scope, communityId, options) {
      const currentScope = withScope(scope);
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        communityMembersPath(communityId),
        options,
      );
      if (!isRecord(payload) || !Array.isArray(payload.members)) {
        throw projectKnowledgeError('project_community_members_contract_invalid');
      }
      return Object.freeze(
        payload.members.map((value) => parseCommunityMember(value, currentScope.projectId)),
      );
    },
    async rebuild(scope, options) {
      const currentScope = withScope(scope);
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        communityRebuildPath(currentScope),
        { ...options, method: 'POST' },
      );
      if (!isRecord(payload)) {
        throw projectKnowledgeError('project_community_rebuild_contract_invalid');
      }
      return requireIdentifier(payload.task_id, 'project_community_rebuild_contract_invalid');
    },
    async cancel(scope, taskId, options) {
      withScope(scope);
      await requestProjectKnowledgeJson(
        runtimeConfig,
        taskCancelPath(taskId),
        { ...options, method: 'POST' },
      );
    },
  };
  return Object.freeze(client);
}

function communityListPath(scope: ProjectKnowledgeScope): string {
  const tenantId = encodeURIComponent(scope.tenantId);
  const projectId = encodeURIComponent(scope.projectId);
  return (
    `/api/v1/graph/communities/?tenant_id=${tenantId}` +
    `&project_id=${projectId}&limit=50&offset=0`
  );
}

function communityMembersPath(communityId: string): string {
  const id = requireIdentifier(communityId, 'project_community_id_required');
  return `/api/v1/graph/communities/${encodeURIComponent(id)}/members?limit=100`;
}

function communityRebuildPath(scope: ProjectKnowledgeScope): string {
  return (
    '/api/v1/graph/communities/rebuild?background=true&project_id=' +
    encodeURIComponent(scope.projectId)
  );
}

function taskCancelPath(taskId: string): string {
  const id = requireIdentifier(taskId, 'project_community_task_id_required');
  return `/api/v1/tasks/${encodeURIComponent(id)}/cancel`;
}

function parseCommunityPage(
  payload: unknown,
  projectId: string,
): Readonly<{ communities: readonly ProjectCommunity[]; total: number }> {
  if (!isRecord(payload) || !Array.isArray(payload.communities)) {
    throw projectKnowledgeError('project_communities_page_contract_invalid');
  }
  const communities = Object.freeze(
    payload.communities.map((value) => parseCommunity(value, projectId)),
  );
  const total = requireNonnegativeInteger(
    payload.total,
    'project_communities_page_contract_invalid',
  );
  if (total < communities.length) {
    throw projectKnowledgeError('project_communities_page_contract_invalid');
  }
  return Object.freeze({ communities, total });
}

function parseCommunity(payload: unknown, projectId: string): ProjectCommunity {
  if (!isRecord(payload)) throw projectKnowledgeError('project_community_contract_invalid');
  if (
    payload.project_id !== undefined &&
    payload.project_id !== null &&
    payload.project_id !== projectId
  ) {
    throw projectKnowledgeError('project_community_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(payload.uuid, 'project_community_contract_invalid'),
    name: requireIdentifier(payload.name, 'project_community_contract_invalid'),
    summary: requireText(payload.summary, 'project_community_contract_invalid'),
    memberCount: requireNonnegativeInteger(
      payload.member_count,
      'project_community_contract_invalid',
    ),
    projectId: optionalText(payload.project_id, 'project_community_contract_invalid'),
    createdAt: optionalText(
      payload.formed_at ?? payload.created_at,
      'project_community_contract_invalid',
    ),
  });
}

function parseCommunityMember(payload: unknown, projectId: string): ProjectEntity {
  if (!isRecord(payload)) throw projectKnowledgeError('project_community_member_contract_invalid');
  if (
    payload.project_id !== undefined &&
    payload.project_id !== null &&
    payload.project_id !== projectId
  ) {
    throw projectKnowledgeError('project_community_member_scope_conflict', 409);
  }
  return Object.freeze({
    id: requireIdentifier(payload.uuid, 'project_community_member_contract_invalid'),
    name: requireIdentifier(payload.name, 'project_community_member_contract_invalid'),
    entityType: requireIdentifier(payload.entity_type, 'project_community_member_contract_invalid'),
    summary: requireText(payload.summary, 'project_community_member_contract_invalid'),
    projectId: optionalText(payload.project_id, 'project_community_member_contract_invalid'),
    createdAt: optionalText(payload.created_at, 'project_community_member_contract_invalid'),
  });
}
