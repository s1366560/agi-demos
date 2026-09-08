import {
  readGraphNodeProvenance,
  readGraphEdgeProvenance,
} from '../features/project-knowledge/projectGraphProvenance';
import {
  PROJECT_GRAPH_DEGRADED_REASON,
  PROJECT_GRAPH_LOCAL_REASON,
  type ProjectGraphEdge,
  type ProjectGraphNode,
  type ProjectGraphSnapshot,
} from '../features/project-knowledge/projectGraphClient';
import {
  isRecord,
  observeProjectKnowledgeScope,
  optionalText,
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  requireFiniteNumber,
  requireIdentifier,
  requireProjectKnowledgeScope,
  requireText,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectGraphRuntimeConfigV2,
  cloneDesktopProjectGraphScopeV2,
} from './desktopProjectGraphOperationContractV2';

const ACTIONS_V2 = Object.freeze(['view']);
const NODE_TYPES_V2 = new Set<ProjectGraphNode['type']>(['Entity', 'Episodic', 'Community']);

export type DesktopProjectGraphHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectGraphSnapshot>;
}>;

export function createDesktopProjectGraphHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): DesktopProjectGraphHttpAuthorityV2 {
  const runtimeConfig = cloneDesktopProjectGraphRuntimeConfigV2(config);
  const operationScope = cloneDesktopProjectGraphScopeV2(scope, runtimeConfig);
  return Object.freeze({
    async load(signal) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        operationScope,
        PROJECT_GRAPH_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(runtimeConfig, currentScope, {
        signal,
      });
      const payload = await requestProjectKnowledgeJson(runtimeConfig, graphPathV2(currentScope), {
        signal,
      });
      const graph = parseGraphV2(payload, currentScope);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_GRAPH_DEGRADED_REASON,
        allowedActions: ACTIONS_V2,
        ...graph,
      });
    },
  });
}

function graphPathV2(scope: ProjectKnowledgeScope): string {
  const tenantId = encodeURIComponent(scope.tenantId);
  const projectId = encodeURIComponent(scope.projectId);
  return `/api/v1/graph/memory/graph?tenant_id=${tenantId}&project_id=${projectId}&limit=1000`;
}

function parseGraphV2(
  payload: unknown,
  scope: ProjectKnowledgeScope,
): Readonly<{ nodes: readonly ProjectGraphNode[]; edges: readonly ProjectGraphEdge[] }> {
  if (
    !isRecord(payload) ||
    !isRecord(payload.elements) ||
    !Array.isArray(payload.elements.nodes) ||
    !Array.isArray(payload.elements.edges)
  ) {
    throw projectKnowledgeError('project_graph_contract_invalid');
  }
  const nodes = Object.freeze(payload.elements.nodes.map((value) => parseNodeV2(value, scope)));
  const ids = new Set(nodes.map((node) => node.id));
  if (ids.size !== nodes.length) {
    throw projectKnowledgeError('project_graph_node_contract_invalid');
  }
  const edges = Object.freeze(payload.elements.edges.map((value) => parseEdgeV2(value, ids)));
  if (new Set(edges.map((edge) => edge.id)).size !== edges.length) {
    throw projectKnowledgeError('project_graph_edge_contract_invalid');
  }
  return Object.freeze({ nodes, edges });
}

function parseNodeV2(value: unknown, scope: ProjectKnowledgeScope): ProjectGraphNode {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw projectKnowledgeError('project_graph_node_contract_invalid');
  }
  const data = value.data;
  if (
    (data.project_id !== undefined &&
      data.project_id !== null &&
      data.project_id !== scope.projectId) ||
    (data.tenant_id !== undefined && data.tenant_id !== null && data.tenant_id !== scope.tenantId)
  ) {
    throw projectKnowledgeError('project_graph_node_scope_conflict', 409);
  }
  if (typeof data.type !== 'string' || !NODE_TYPES_V2.has(data.type as ProjectGraphNode['type'])) {
    throw projectKnowledgeError('project_graph_node_contract_invalid');
  }
  return Object.freeze({
    id: requireIdentifier(data.id, 'project_graph_node_contract_invalid'),
    label: requireText(data.label, 'project_graph_node_contract_invalid'),
    type: data.type as ProjectGraphNode['type'],
    name: requireIdentifier(data.name, 'project_graph_node_contract_invalid'),
    summary: optionalText(data.summary, 'project_graph_node_contract_invalid'),
    ...readGraphNodeProvenance(data),
  });
}

function parseEdgeV2(value: unknown, nodeIds: ReadonlySet<string>): ProjectGraphEdge {
  if (!isRecord(value) || !isRecord(value.data)) {
    throw projectKnowledgeError('project_graph_edge_contract_invalid');
  }
  const data = value.data;
  const source = requireIdentifier(data.source, 'project_graph_edge_contract_invalid');
  const target = requireIdentifier(data.target, 'project_graph_edge_contract_invalid');
  if (!nodeIds.has(source) || !nodeIds.has(target)) {
    throw projectKnowledgeError('project_graph_edge_node_missing', 409);
  }
  return Object.freeze({
    id: requireIdentifier(data.id, 'project_graph_edge_contract_invalid'),
    source,
    target,
    label: requireText(data.label, 'project_graph_edge_contract_invalid'),
    weight:
      data.weight === undefined || data.weight === null
        ? null
        : requireFiniteNumber(data.weight, 'project_graph_edge_contract_invalid'),
    ...readGraphEdgeProvenance(data),
  });
}
