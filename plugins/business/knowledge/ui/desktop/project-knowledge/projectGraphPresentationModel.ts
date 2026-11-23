import type {
  ProjectKnowledgePresentationInput,
  ProjectKnowledgeViewModel,
} from './projectKnowledgePresentationModel';
import type { ProjectGraphNode, ProjectGraphEdge } from './projectGraphClient';
import type { ProjectGraphSelection } from './projectGraphNavigation';
import { buildProjectKnowledgePresentation } from './projectKnowledgePresentationModel';
import { PROJECT_GRAPH_ROUTE_ID, type ProjectGraphSnapshot } from './projectGraphClient';

export type ProjectGraphViewModel = ProjectKnowledgeViewModel &
  Readonly<{
    nodes: readonly ProjectGraphNode[];
    edges: readonly ProjectGraphEdge[];
    scopeRevision: number | null;
    selection: ProjectGraphSelection | null;
    sourceUuid: string | null;
    source: ProjectGraphNode | null;
    sourceState: 'idle' | 'loading' | 'ready' | 'error';
  }>;

export function buildProjectGraphPresentation(
  input: ProjectKnowledgePresentationInput<ProjectGraphSnapshot>,
): ProjectGraphViewModel {
  const base = buildProjectKnowledgePresentation(PROJECT_GRAPH_ROUTE_ID, input, (snapshot) =>
    Object.freeze({
      items: Object.freeze(
        snapshot.nodes.map((node) =>
          Object.freeze({
            id: node.id,
            title: node.name,
            detail: node.summary,
            kind: node.type,
          }),
        ),
      ),
      total: snapshot.nodes.length,
    }),
  );
  return Object.freeze({
    ...base,
    nodes: input.kind === 'snapshot' ? input.snapshot.nodes : Object.freeze([]),
    edges: input.kind === 'snapshot' ? input.snapshot.edges : Object.freeze([]),
    scopeRevision: input.kind === 'snapshot' ? input.snapshot.scopeRevision : null,
    selection: null,
    sourceUuid: null,
    source: null,
    sourceState: 'idle',
  });
}
