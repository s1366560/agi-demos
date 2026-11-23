import { projectKnowledgeError } from './projectKnowledgeClient';

/** Only properties emitted by the graph store; graph element IDs and UUIDs stay distinct. */
export const GRAPH_NODE_PROVENANCE_KEYS = Object.freeze([
  'uuid',
  'entity_type',
  'content',
  'source',
  'source_description',
  'memory_id',
  'created_at',
  'valid_at',
  'tenant_id',
  'project_id',
] as const);
export const GRAPH_EDGE_PROVENANCE_KEYS = Object.freeze([
  'uuid',
  'relationship_type',
  'fact',
  'created_at',
  'valid_at',
  'invalid_at',
  'expired_at',
] as const);
export type ProjectGraphNodeProvenance = Readonly<
  Partial<Record<(typeof GRAPH_NODE_PROVENANCE_KEYS)[number], string | null>>
>;
export type ProjectGraphEdgeProvenance = Readonly<
  Partial<Record<(typeof GRAPH_EDGE_PROVENANCE_KEYS)[number], string | null>>
> &
  Readonly<{ episodes?: readonly string[] }>;

export function validGraphProvenance(
  value: Record<string, unknown>,
  textKeys: readonly string[],
  includeEpisodes = false,
): boolean {
  return (
    textKeys.every(
      (key) => !Object.hasOwn(value, key) || value[key] === null || typeof value[key] === 'string',
    ) &&
    (!includeEpisodes ||
      !Object.hasOwn(value, 'episodes') ||
      (Array.isArray(value.episodes) &&
        value.episodes.every((id) => typeof id === 'string' && id.length > 0 && id === id.trim())))
  );
}

export function readGraphNodeProvenance(
  value: Record<string, unknown>,
): ProjectGraphNodeProvenance {
  if (!validGraphProvenance(value, GRAPH_NODE_PROVENANCE_KEYS))
    throw projectKnowledgeError('project_graph_node_contract_invalid');
  return Object.freeze(
    Object.fromEntries(
      GRAPH_NODE_PROVENANCE_KEYS.filter((key) => Object.hasOwn(value, key)).map((key) => [
        key,
        value[key],
      ]),
    ),
  );
}

export function readGraphEdgeProvenance(
  value: Record<string, unknown>,
): ProjectGraphEdgeProvenance {
  if (!validGraphProvenance(value, GRAPH_EDGE_PROVENANCE_KEYS, true))
    throw projectKnowledgeError('project_graph_edge_contract_invalid');
  return Object.freeze({
    ...Object.fromEntries(
      GRAPH_EDGE_PROVENANCE_KEYS.filter((key) => Object.hasOwn(value, key)).map((key) => [
        key,
        value[key],
      ]),
    ),
    ...(Object.hasOwn(value, 'episodes')
      ? { episodes: Object.freeze([...(value.episodes as string[])]) }
      : {}),
  });
}
