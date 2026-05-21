export type ExecutionDagEdgeKind = 'dependency' | 'hierarchy' | 'handoff';

export interface ExecutionDagNodeMetrics {
  artifacts?: number | undefined;
  evidence?: number | undefined;
  changedFiles?: number | undefined;
  dependencies?: number | undefined;
}

export interface ExecutionDagNode {
  id: string;
  title: string;
  kind: string;
  status: string;
  execution?: string | undefined;
  agentLabel?: string | undefined;
  attemptId?: string | undefined;
  progress?: number | undefined;
  subtitle?: string | undefined;
  metrics?: ExecutionDagNodeMetrics | undefined;
  selectable?: boolean | undefined;
  sourceNodeId?: string | undefined;
  workspaceTaskId?: string | undefined;
}

export interface ExecutionDagEdge {
  id: string;
  sourceId: string;
  targetId: string;
  kind: ExecutionDagEdgeKind;
  label?: string | undefined;
}

export interface ExecutionDagModel {
  rootId: string;
  nodes: ExecutionDagNode[];
  edges: ExecutionDagEdge[];
  selectedNodeId?: string | null | undefined;
}

export interface ExecutionDagNodeLayout extends ExecutionDagNode {
  x: number;
  y: number;
  level: number;
  order: number;
}
