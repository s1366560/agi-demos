import type { GraphData, GraphNode } from '@/services/graphService';

import type { EdgeData, GraphSnapshot, NodeData } from '@/components/graph/CytoscapeGraph/types';

export type GraphSelection = { kind: 'node'; data: NodeData } | { kind: 'edge'; data: EdgeData };

export function graphSourceUuids(graph: GraphSnapshot, selection: GraphSelection): string[] {
  const sources = new Set<string>();
  const addEpisode = (node: NodeData | undefined) => {
    if (node?.type === 'Episodic' && typeof node.uuid === 'string' && node.uuid) {
      sources.add(node.uuid);
    }
  };
  if (selection.kind === 'node') {
    addEpisode(selection.data);
    if (selection.data.type === 'Entity') {
      graph.edges
        .filter((edge) => edge.label === 'MENTIONS' && edge.target === selection.data.id)
        .forEach((edge) => { addEpisode(graph.nodes.find((node) => node.id === edge.source)); });
    }
  } else {
    if (Array.isArray(selection.data.episodes)) {
      selection.data.episodes.forEach((uuid: unknown) => {
        if (typeof uuid === 'string' && uuid) sources.add(uuid);
      });
    }
    if (selection.data.label === 'MENTIONS') {
      addEpisode(graph.nodes.find((node) => node.id === selection.data.source));
    }
  }
  return [...sources];
}

export function requireGraphSource(
  data: GraphData,
  uuid: string,
  tenantId: string,
  projectId: string
): GraphNode | null {
  if (data.elements.edges.length !== 0 || data.elements.nodes.length > 1)
    throw new Error('Invalid source response');
  const source = data.elements.nodes[0]?.data;
  if (!source) return null;
  if (
    source.uuid !== uuid ||
    source.type !== 'Episodic' ||
    source.tenant_id !== tenantId ||
    source.project_id !== projectId
  ) {
    throw new Error('Source scope mismatch');
  }
  return source;
}
