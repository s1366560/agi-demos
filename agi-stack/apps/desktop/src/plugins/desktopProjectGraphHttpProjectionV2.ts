import { parseGraphV2 } from '@business/knowledge/ui/desktop/project-knowledge/graphWire';
import {
  PROJECT_GRAPH_DEGRADED_REASON,
  PROJECT_GRAPH_LOCAL_REASON,
  type ProjectGraphSnapshot,
  type ProjectGraphSourceQuery,
} from '@business/knowledge/ui/desktop/project-knowledge/projectGraphClient';
import {
  observeProjectKnowledgeScope,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requireProjectKnowledgeScope,
  type ProjectKnowledgeScope,
} from '@business/knowledge/ui/desktop/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectGraphRuntimeConfigV2,
  cloneDesktopProjectGraphScopeV2,
  prepareProjectGraphSourceQuery,
  requireProjectGraphSourceSnapshot,
} from './desktopProjectGraphOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view']);

export type DesktopProjectGraphHttpAuthorityV2 = Readonly<{
  load: (
    signal?: AbortSignal,
    sourceQuery?: ProjectGraphSourceQuery,
  ) => Promise<ProjectGraphSnapshot>;
}>;

export function createDesktopProjectGraphHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): DesktopProjectGraphHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectGraphRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectGraphScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal, sourceQuery) {
      const query =
        sourceQuery === undefined ? undefined : prepareProjectGraphSourceQuery(sourceQuery);
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_GRAPH_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(runtimeConfig, currentScope, {
        signal,
      });
      if (query && query.expectedContextRevision !== scopeRevision)
        throw projectKnowledgeError('project_graph_source_context_changed', 409);
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        query ? '/api/v1/graph/memory/graph/subgraph' : graphPathV2(currentScope),
        query
          ? {
              signal,
              method: 'POST',
              body: {
                node_uuids: [query.episodeUuid],
                include_neighbors: false,
                limit: 1,
                tenant_id: currentScope.tenantId,
                project_id: currentScope.projectId,
              },
            }
          : { signal },
      );
      if (
        query &&
        (await observeProjectKnowledgeScope(runtimeConfig, currentScope, { signal })) !==
          scopeRevision
      )
        throw projectKnowledgeError('project_graph_source_context_changed', 409);
      const graph = parseGraphV2(payload, currentScope);
      const snapshot: ProjectGraphSnapshot = Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_GRAPH_DEGRADED_REASON,
        allowedActions: ACTIONS_V2,
        ...graph,
      });
      return query ? requireProjectGraphSourceSnapshot(snapshot, query) : snapshot;
    },
  });
}

function graphPathV2(scope: ProjectKnowledgeScope): string {
  const tenantId = encodeURIComponent(scope.tenantId);
  const projectId = encodeURIComponent(scope.projectId);
  return `/api/v1/graph/memory/graph?tenant_id=${tenantId}&project_id=${projectId}&limit=1000`;
}
