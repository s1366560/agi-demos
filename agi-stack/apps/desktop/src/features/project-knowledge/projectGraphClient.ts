import {
  type ProjectKnowledgeClient,
  type ProjectKnowledgeSnapshotBase,
} from './projectKnowledgeClient';

export const PROJECT_GRAPH_ROUTE_ID = 'project-project-graph' as const;
export const PROJECT_GRAPH_LOCAL_REASON = 'local_project_graph_authority_unavailable' as const;
export const PROJECT_GRAPH_DEGRADED_REASON = 'desktop_project_graph_actions_partial' as const;

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
