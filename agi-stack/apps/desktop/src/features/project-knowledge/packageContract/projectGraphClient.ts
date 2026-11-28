import type {
  ProjectGraphNodeProvenance,
  ProjectGraphEdgeProvenance,
} from './projectGraphProvenance';
import {
  type ProjectKnowledgeClient,
  type ProjectKnowledgeSnapshotBase,
  type ProjectKnowledgeScope,
} from './projectKnowledgeClient';

export const PROJECT_GRAPH_ROUTE_ID = 'project-project-graph' as const;
export const PROJECT_GRAPH_LOCAL_REASON = 'local_project_graph_authority_unavailable' as const;
export const PROJECT_GRAPH_DEGRADED_REASON = 'desktop_project_graph_actions_partial' as const;

export type ProjectGraphNode = ProjectGraphNodeProvenance &
  Readonly<{
    id: string;
    label: string;
    type: 'Entity' | 'Episodic' | 'Community';
    name: string;
    summary: string | null;
  }>;
export type ProjectGraphEdge = ProjectGraphEdgeProvenance &
  Readonly<{
    id: string;
    source: string;
    target: string;
    label: string;
    weight: number | null;
  }>;
export type ProjectGraphSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{ nodes: readonly ProjectGraphNode[]; edges: readonly ProjectGraphEdge[] }>;
export type ProjectGraphSourceQuery = Readonly<{
  episodeUuid: string;
  expectedContextRevision: number;
}>;
export type ProjectGraphClient = ProjectKnowledgeClient<ProjectGraphSnapshot> &
  Readonly<{
    loadSource: (
      scope: ProjectKnowledgeScope,
      query: ProjectGraphSourceQuery,
      options?: Readonly<{ signal?: AbortSignal }>,
    ) => Promise<ProjectGraphSnapshot>;
  }>;
