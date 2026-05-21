import type { GraphNodeState, GraphRunState } from '@/stores/graphStore';

import type { AgentGraphApiResponse } from '@/services/agent/graph/agentGraphApi';

import type { ExecutionDagEdge, ExecutionDagModel, ExecutionDagNode } from './types';

function uniqueEdges(edges: ExecutionDagEdge[]): ExecutionDagEdge[] {
  const seen = new Set<string>();
  return edges.filter((edge) => {
    const key = `${edge.kind}:${edge.sourceId}:${edge.targetId}`;
    if (seen.has(key) || edge.sourceId === edge.targetId) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function rootId(run: GraphRunState): string {
  return `graph-root:${run.graphRunId}`;
}

function graphNodeToDagNode(
  node: GraphNodeState | undefined,
  graphNode: AgentGraphApiResponse['nodes'][number] | undefined
): ExecutionDagNode {
  const id = node?.nodeId ?? graphNode?.node_id ?? '';
  return {
    id,
    title: node?.label ?? graphNode?.label ?? id,
    kind: graphNode?.is_terminal ? 'terminal' : graphNode?.is_entry ? 'entry' : 'agent',
    status: node?.status ?? 'pending',
    execution: node?.status,
    agentLabel: node?.agentDefinitionId ?? graphNode?.agent_definition_id,
    attemptId: node?.agentSessionId,
    subtitle: graphNode?.instruction,
    metrics: {
      artifacts: node?.outputKeys?.length ?? 0,
      evidence: node?.outputKeys?.length ?? 0,
    },
  };
}

export function buildChatExecutionDag(
  run: GraphRunState | null,
  graphDefinition: AgentGraphApiResponse | null
): ExecutionDagModel | null {
  if (!run) {
    return null;
  }
  const root = rootId(run);
  const liveNodes = Array.from(run.nodes.values());
  const graphNodes = graphDefinition?.nodes ?? [];
  const graphNodesById = new Map(graphNodes.map((node) => [node.node_id, node]));
  const liveNodesById = new Map(liveNodes.map((node) => [node.nodeId, node]));
  const nodeIds = new Set<string>([
    ...graphNodes.map((node) => node.node_id),
    ...liveNodes.map((node) => node.nodeId),
  ]);

  const nodes: ExecutionDagNode[] = [
    {
      id: root,
      title: run.graphName,
      kind: 'graph',
      status: run.status,
      execution: run.pattern,
      progress:
        run.totalSteps && run.totalSteps > 0
          ? Math.min(100, Math.round((run.nodes.size / run.totalSteps) * 100))
          : undefined,
      selectable: false,
      metrics: {
        artifacts: run.totalSteps,
        evidence: run.handoffs.length,
        dependencies: nodeIds.size,
      },
    },
    ...Array.from(nodeIds).map((id) =>
      graphNodeToDagNode(liveNodesById.get(id), graphNodesById.get(id))
    ),
  ];

  const edges: ExecutionDagEdge[] = [];
  if (graphDefinition) {
    for (const edge of graphDefinition.edges) {
      edges.push({
        id: `dependency:${edge.source_node_id}:${edge.target_node_id}`,
        sourceId: edge.source_node_id,
        targetId: edge.target_node_id,
        kind: 'dependency',
        label: edge.condition,
      });
    }
  }

  if (edges.length === 0) {
    for (const handoff of run.handoffs) {
      edges.push({
        id: `handoff:${handoff.fromNodeId}:${handoff.toNodeId}:${String(handoff.timestamp)}`,
        sourceId: handoff.fromNodeId,
        targetId: handoff.toNodeId,
        kind: 'handoff',
        label: handoff.contextSummary,
      });
    }
  }

  const incoming = new Set(edges.map((edge) => edge.targetId));
  const entryNodeIds =
    graphDefinition?.nodes.filter((node) => node.is_entry).map((node) => node.node_id) ??
    run.entryNodeIds;
  for (const nodeId of entryNodeIds) {
    if (nodeIds.has(nodeId) && !incoming.has(nodeId)) {
      edges.push({
        id: `hierarchy:${root}:${nodeId}`,
        sourceId: root,
        targetId: nodeId,
        kind: 'hierarchy',
      });
    }
  }
  if (entryNodeIds.length === 0) {
    for (const nodeId of nodeIds) {
      if (!incoming.has(nodeId)) {
        edges.push({
          id: `hierarchy:${root}:${nodeId}`,
          sourceId: root,
          targetId: nodeId,
          kind: 'hierarchy',
        });
      }
    }
  }

  return {
    rootId: root,
    nodes,
    edges: uniqueEdges(edges),
  };
}
