import { readGraphNodeProvenance, readGraphEdgeProvenance } from './projectGraphProvenance';
import type { ProjectGraphNode, ProjectGraphEdge } from './projectGraphClient';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import { isRecord, optionalText, projectKnowledgeError, requireFiniteNumber, requireIdentifier, requireText } from './projectKnowledgeValues';

const NODE_TYPES_V2 = new Set<ProjectGraphNode['type']>(['Entity', 'Episodic', 'Community']);

export function parseGraphV2(
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
