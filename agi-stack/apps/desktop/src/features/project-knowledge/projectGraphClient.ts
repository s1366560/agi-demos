import type { DesktopRuntimeConfig } from '../../types';
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
  type ProjectKnowledgeClient,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_GRAPH_ROUTE_ID = 'project-project-graph' as const;
export const PROJECT_GRAPH_LOCAL_REASON = 'local_project_graph_authority_unavailable' as const;
export const PROJECT_GRAPH_DEGRADED_REASON = 'project_graph_export_file_ipc_unavailable' as const;

export type ProjectGraphNode = Readonly<{
  id: string;
  label: string;
  type: 'Entity' | 'Episodic' | 'Community';
  name: string;
  summary: string | null;
}>;
export type ProjectGraphEdge = Readonly<{
  id: string;
  source: string;
  target: string;
  label: string;
  weight: number | null;
}>;
export type ProjectGraphSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{ nodes: readonly ProjectGraphNode[]; edges: readonly ProjectGraphEdge[] }>;
export type ProjectGraphClient = ProjectKnowledgeClient<ProjectGraphSnapshot>;

const ACTIONS = Object.freeze(['view', 'navigate-graph', 'inspect-node', 'inspect-edge']);
const NODE_TYPES = new Set<ProjectGraphNode['type']>(['Entity', 'Episodic', 'Community']);

export function createProjectGraphClient(config: DesktopRuntimeConfig): ProjectGraphClient {
  const runtimeConfig = Object.freeze({ ...config });
  const client: ProjectGraphClient = {
    async load(scope, options) {
      const currentScope = requireProjectKnowledgeScope(
        runtimeConfig,
        scope,
        PROJECT_GRAPH_LOCAL_REASON,
      );
      const scopeRevision = await observeProjectKnowledgeScope(
        runtimeConfig,
        currentScope,
        options,
      );
      const payload = await requestProjectKnowledgeJson(
        runtimeConfig,
        graphPath(currentScope),
        options,
      );
      const graph = parseGraph(payload, currentScope);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: PROJECT_GRAPH_DEGRADED_REASON,
        allowedActions: ACTIONS,
        ...graph,
      });
    },
  };
  return Object.freeze(client);
}

function graphPath(scope: ProjectKnowledgeScope): string {
  const tenantId = encodeURIComponent(scope.tenantId);
  const projectId = encodeURIComponent(scope.projectId);
  return `/api/v1/graph/memory/graph?tenant_id=${tenantId}&project_id=${projectId}&limit=1000`;
}

function parseGraph(
  payload: unknown,
  scope: ProjectKnowledgeScope,
): Readonly<{ nodes: readonly ProjectGraphNode[]; edges: readonly ProjectGraphEdge[] }> {
  if (!isRecord(payload) || !isRecord(payload.elements)) {
    throw projectKnowledgeError('project_graph_contract_invalid');
  }
  if (!Array.isArray(payload.elements.nodes) || !Array.isArray(payload.elements.edges)) {
    throw projectKnowledgeError('project_graph_contract_invalid');
  }
  const nodes = Object.freeze(payload.elements.nodes.map((value) => parseNode(value, scope)));
  const ids = new Set(nodes.map((node) => node.id));
  const edges = Object.freeze(payload.elements.edges.map((value) => parseEdge(value, ids)));
  return Object.freeze({ nodes, edges });
}

function parseNode(value: unknown, scope: ProjectKnowledgeScope): ProjectGraphNode {
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
  if (typeof data.type !== 'string' || !NODE_TYPES.has(data.type as ProjectGraphNode['type'])) {
    throw projectKnowledgeError('project_graph_node_contract_invalid');
  }
  return Object.freeze({
    id: requireIdentifier(data.id, 'project_graph_node_contract_invalid'),
    label: requireText(data.label, 'project_graph_node_contract_invalid'),
    type: data.type as ProjectGraphNode['type'],
    name: requireIdentifier(data.name, 'project_graph_node_contract_invalid'),
    summary: optionalText(data.summary, 'project_graph_node_contract_invalid'),
  });
}

function parseEdge(value: unknown, nodeIds: ReadonlySet<string>): ProjectGraphEdge {
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
  });
}
