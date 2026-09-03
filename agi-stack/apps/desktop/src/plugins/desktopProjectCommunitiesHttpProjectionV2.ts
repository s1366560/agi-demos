import {
  PROJECT_COMMUNITIES_DEGRADED_REASON,
  PROJECT_COMMUNITIES_LOCAL_REASON,
  type ProjectCommunitiesSnapshot,
  type ProjectCommunity,
} from '../features/project-knowledge/projectCommunitiesClient';
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
  cloneDesktopProjectCommunitiesRuntimeConfigV2,
  cloneDesktopProjectCommunitiesScopeV2,
} from './desktopProjectCommunitiesOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view', 'list']);

export type DesktopProjectCommunitiesHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectCommunitiesSnapshot>;
}>;

export function createDesktopProjectCommunitiesHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): DesktopProjectCommunitiesHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectCommunitiesRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectCommunitiesScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_COMMUNITIES_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(runtimeConfig, currentScope, {
        signal,
      });
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        communityListPathV2(currentScope),
        { signal },
      );
      const page = parseCommunityPageV2(payload, currentScope);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_COMMUNITIES_DEGRADED_REASON,
        allowedActions: ACTIONS_V2,
        ...page,
      });
    },
  });
}

function communityListPathV2(scope: ProjectKnowledgeScope): string {
  return (
    `/api/v1/graph/communities/?tenant_id=${encodeURIComponent(scope.tenantId)}` +
    `&project_id=${encodeURIComponent(scope.projectId)}&limit=50&offset=0`
  );
}

function parseCommunityPageV2(
  payload: unknown,
  scope: ProjectKnowledgeScope,
): Readonly<{ communities: readonly ProjectCommunity[]; total: number }> {
  if (!isRecord(payload) || !Array.isArray(payload.communities)) {
    throw projectKnowledgeError('project_communities_page_contract_invalid');
  }
  const communities = Object.freeze(
    payload.communities.map((value) => parseCommunityV2(value, scope)),
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

function parseCommunityV2(
  payload: unknown,
  scope: ProjectKnowledgeScope,
): ProjectCommunity {
  if (!isRecord(payload)) throw projectKnowledgeError('project_community_contract_invalid');
  if (
    (payload.tenant_id !== undefined &&
      payload.tenant_id !== null &&
      payload.tenant_id !== scope.tenantId) ||
    (payload.project_id !== undefined &&
      payload.project_id !== null &&
      payload.project_id !== scope.projectId)
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
