import type { NativeKnowledgeGraphModel } from './nativeKnowledgeGraphController';

/** Exact literal and positional filtering; no semantic matching or identity merging. */
export function nativeKnowledgeGraphPresentation(
  graph: NativeKnowledgeGraphModel['graph'],
  literal: string,
  selectedNode: number | null,
) {
  const visibleNodes = new Set<number>();
  const visibleEdges =
    graph?.relationships.flatMap((edge, index) => {
      const matches =
        !literal ||
        edge.relation_type.includes(literal) ||
        edge.fact.includes(literal) ||
        [edge.source_index, edge.target_index].some(
          (i) =>
            graph.entities[i]?.name.includes(literal) || graph.entities[i]?.kind.includes(literal),
        );
      if (
        !matches ||
        (selectedNode !== null &&
          edge.source_index !== selectedNode &&
          edge.target_index !== selectedNode)
      )
        return [];
      visibleNodes.add(edge.source_index);
      visibleNodes.add(edge.target_index);
      return [{ edge, index }];
    }) ?? [];
  graph?.entities.forEach((entity, index) => {
    if (
      (!literal || entity.name.includes(literal) || entity.kind.includes(literal)) &&
      (selectedNode === null || selectedNode === index)
    )
      visibleNodes.add(index);
  });
  const visibleIndexes = [...visibleNodes].sort((a, b) => a - b);
  return { visibleNodes, visibleEdges, visibleIndexes };
}
