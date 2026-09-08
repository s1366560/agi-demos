import type { ProjectGraphEdge, ProjectGraphNode } from './projectGraphClient';

export type ProjectGraphSelection = Readonly<{ kind: 'node' | 'edge'; id: string }>;
export type ProjectGraphElements = Readonly<{
  nodes: readonly ProjectGraphNode[];
  edges: readonly ProjectGraphEdge[];
}>;

export function projectGraphAdjacentEdges(graph: ProjectGraphElements, nodeId: string) {
  return graph.edges.filter((edge) => edge.source === nodeId || edge.target === nodeId);
}

/** Relationship meaning comes from stored edge types and explicit supporting UUID fields. */
export function projectGraphSourceUuids(
  graph: ProjectGraphElements,
  selection: ProjectGraphSelection | null,
): readonly string[] {
  const ids = new Set<string>();
  const add = (uuid: string | null | undefined) => {
    if (uuid) ids.add(uuid);
  };
  if (selection?.kind === 'node') {
    const node = graph.nodes.find((item) => item.id === selection.id);
    if (node?.type === 'Episodic') add(node.uuid);
    if (node?.type === 'Entity') {
      for (const edge of graph.edges) {
        if (edge.target !== node.id || edge.label !== 'MENTIONS') continue;
        const episode = graph.nodes.find((item) => item.id === edge.source);
        if (episode?.type === 'Episodic') add(episode.uuid);
      }
    }
  } else if (selection?.kind === 'edge') {
    const edge = graph.edges.find((item) => item.id === selection.id);
    for (const uuid of edge?.episodes ?? []) add(uuid);
    if (edge?.label === 'MENTIONS') {
      const episode = graph.nodes.find((item) => item.id === edge.source);
      if (episode?.type === 'Episodic') add(episode.uuid);
    }
  }
  return Object.freeze([...ids]);
}
