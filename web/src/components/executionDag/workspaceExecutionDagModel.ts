import type { NodeFilter } from '@/components/blackboard/tabs/planRunSnapshotModel';
import {
  iterationNodeIndex,
  matchesFilter,
  shortId,
} from '@/components/blackboard/tabs/planRunSnapshotModel';

import type { WorkspaceAgent, WorkspacePlanNode, WorkspacePlanSnapshot } from '@/types/workspace';

import type { ExecutionDagEdge, ExecutionDagModel, ExecutionDagNode } from './types';

interface WorkspaceExecutionDagOptions {
  iterationIndex?: number | null | undefined;
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function uniqueEdges(edges: ExecutionDagEdge[]): ExecutionDagEdge[] {
  const seen = new Set<string>();
  const result: ExecutionDagEdge[] = [];
  for (const edge of edges) {
    const key = `${edge.kind}:${edge.sourceId}:${edge.targetId}`;
    if (seen.has(key) || edge.sourceId === edge.targetId) {
      continue;
    }
    seen.add(key);
    result.push(edge);
  }
  return result;
}

export function resolveWorkspaceAgentLabel(
  agentId: string | null | undefined,
  agents: WorkspaceAgent[]
): string | undefined {
  if (!agentId) {
    return undefined;
  }
  const agent = agents.find((item) => item.id === agentId || item.agent_id === agentId);
  return agent?.display_name ?? agent?.label ?? agent?.agent_id ?? agentId;
}

function nodeToDagNode(node: WorkspacePlanNode, agents: WorkspaceAgent[]): ExecutionDagNode {
  return {
    id: node.id,
    title: node.title,
    kind: node.kind,
    status: node.intent,
    execution: node.execution,
    agentLabel: resolveWorkspaceAgentLabel(node.assignee_agent_id, agents),
    attemptId: shortId(node.current_attempt_id),
    progress: node.progress.percent,
    subtitle: node.description,
    sourceNodeId: node.id,
    workspaceTaskId: node.workspace_task_id ?? undefined,
    metrics: {
      artifacts: node.evidence_bundle?.artifacts.length ?? 0,
      evidence: node.evidence_bundle?.evidence_refs.length ?? 0,
      changedFiles: node.evidence_bundle?.changed_files.length ?? 0,
      dependencies: node.depends_on.length,
    },
  };
}

function rootNode(snapshot: WorkspacePlanSnapshot): ExecutionDagNode {
  const plan = snapshot.plan;
  const goalNode = plan?.nodes.find((node) => node.kind === 'goal') ?? plan?.nodes[0] ?? null;
  const rootGoal = snapshot.root_goal ?? null;
  return {
    id: rootDagNodeId(snapshot),
    title: rootGoal?.title ?? goalNode?.title ?? 'Root goal',
    kind: 'root',
    status: rootGoal?.status ?? plan?.status ?? 'active',
    execution: snapshot.iteration?.active_phase ?? goalNode?.execution,
    progress: rootGoal?.status === 'done' ? 100 : goalNode?.progress.percent,
    subtitle: rootGoal?.goal_health ?? snapshot.iteration?.current_sprint_goal ?? undefined,
    selectable: false,
    metrics: {
      artifacts: snapshot.artifact_index?.final_deliverables.length ?? 0,
      evidence: snapshot.artifact_index?.verified_outputs.length ?? 0,
      dependencies: plan?.nodes.length ?? 0,
    },
  };
}

function rootDagNodeId(snapshot: WorkspacePlanSnapshot): string {
  return `root:${snapshot.root_goal?.id ?? snapshot.plan?.id ?? snapshot.workspace_id}`;
}

export function buildWorkspaceExecutionDag(
  snapshot: WorkspacePlanSnapshot | null,
  agents: WorkspaceAgent[],
  options: WorkspaceExecutionDagOptions = {}
): ExecutionDagModel | null {
  if (!snapshot?.plan) {
    return null;
  }

  const planNodes = snapshot.plan.nodes;
  const runnableNodes = planNodes.filter((node) => {
    if (node.kind !== 'task' && node.kind !== 'verify') {
      return false;
    }
    return !options.iterationIndex || iterationNodeIndex(node) === options.iterationIndex;
  });
  const structuralNodes = planNodes.filter((node) => {
    if (node.kind === 'task' || node.kind === 'verify') {
      return false;
    }
    return runnableNodes.some(
      (child) => child.parent_id === node.id || child.depends_on.includes(node.id)
    );
  });
  const visiblePlanNodes = [...structuralNodes, ...runnableNodes];
  const visibleIds = new Set(visiblePlanNodes.map((node) => node.id));
  const rootId = rootDagNodeId(snapshot);
  const nodes: ExecutionDagNode[] = [
    rootNode(snapshot),
    ...visiblePlanNodes.map((node) => ({
      ...nodeToDagNode(node, agents),
      selectable: node.kind === 'task' || node.kind === 'verify',
    })),
  ];
  const edges: ExecutionDagEdge[] = [];

  for (const node of visiblePlanNodes) {
    let hasIncoming = false;
    for (const dependencyId of node.depends_on) {
      if (!visibleIds.has(dependencyId)) {
        continue;
      }
      edges.push({
        id: `dependency:${dependencyId}:${node.id}`,
        sourceId: dependencyId,
        targetId: node.id,
        kind: 'dependency',
      });
      hasIncoming = true;
    }

    if (!hasIncoming && node.parent_id && visibleIds.has(node.parent_id)) {
      edges.push({
        id: `hierarchy:${node.parent_id}:${node.id}`,
        sourceId: node.parent_id,
        targetId: node.id,
        kind: 'hierarchy',
      });
      hasIncoming = true;
    }

    if (!hasIncoming) {
      edges.push({
        id: `hierarchy:${rootId}:${node.id}`,
        sourceId: rootId,
        targetId: node.id,
        kind: 'hierarchy',
      });
    }
  }

  return {
    rootId,
    nodes,
    edges: uniqueEdges(edges),
  };
}

export function workspaceDagDimmedNodeIds(
  model: ExecutionDagModel | null,
  snapshot: WorkspacePlanSnapshot | null,
  filter: NodeFilter,
  query: string
): Set<string> {
  if (!model || !snapshot?.plan) {
    return new Set();
  }
  const normalizedQuery = query.trim().toLowerCase();
  const sourceNodes = new Map(snapshot.plan.nodes.map((node) => [node.id, node]));
  const dimmed = new Set<string>();
  for (const node of model.nodes) {
    const source = node.sourceNodeId ? sourceNodes.get(node.sourceNodeId) : null;
    if (!source) {
      continue;
    }
    const matchesQuery =
      !normalizedQuery ||
      [
        source.id,
        source.title,
        source.description,
        source.intent,
        source.execution,
        source.assignee_agent_id ?? '',
        source.current_attempt_id ?? '',
        readText(source.metadata.iteration_phase),
      ]
        .join(' ')
        .toLowerCase()
        .includes(normalizedQuery);
    if (!matchesFilter(source, filter) || !matchesQuery) {
      dimmed.add(node.id);
    }
  }
  return dimmed;
}
