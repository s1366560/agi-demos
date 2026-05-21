import { describe, expect, it } from 'vitest';

import { buildChatExecutionDag } from '@/components/executionDag/chatExecutionDagModel';

import type { AgentGraphApiResponse } from '@/services/agent/graph/agentGraphApi';
import type { GraphRunState } from '@/stores/graphStore';

function run(overrides: Partial<GraphRunState> = {}): GraphRunState {
  return {
    graphRunId: 'run-1',
    graphId: 'graph-1',
    graphName: 'Review pipeline',
    pattern: 'pipeline',
    status: 'running',
    entryNodeIds: ['planner'],
    nodes: new Map(),
    handoffs: [],
    startedAt: Date.now(),
    ...overrides,
  };
}

const graphDefinition: AgentGraphApiResponse = {
  id: 'graph-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  name: 'Review pipeline',
  description: '',
  pattern: 'pipeline',
  nodes: [
    {
      node_id: 'planner',
      agent_definition_id: 'planner-agent',
      label: 'Planner',
      instruction: '',
      config: {},
      is_entry: true,
      is_terminal: false,
    },
    {
      node_id: 'verifier',
      agent_definition_id: 'verifier-agent',
      label: 'Verifier',
      instruction: '',
      config: {},
      is_entry: false,
      is_terminal: true,
    },
  ],
  edges: [{ source_node_id: 'planner', target_node_id: 'verifier', condition: 'ready' }],
  shared_context_keys: [],
  max_total_steps: 10,
  metadata: {},
  is_active: true,
  created_at: '2026-05-01T00:00:00Z',
};

describe('chatExecutionDagModel', () => {
  it('uses static graph definition edges when available', () => {
    const model = buildChatExecutionDag(run(), graphDefinition);

    expect(model?.rootId).toBe('graph-root:run-1');
    expect(model?.nodes.map((node) => node.id)).toEqual([
      'graph-root:run-1',
      'planner',
      'verifier',
    ]);
    expect(model?.edges).toContainEqual({
      id: 'dependency:planner:verifier',
      sourceId: 'planner',
      targetId: 'verifier',
      kind: 'dependency',
      label: 'ready',
    });
  });

  it('falls back to live handoff edges without a graph definition', () => {
    const model = buildChatExecutionDag(
      run({
        nodes: new Map([
          ['planner', { nodeId: 'planner', label: 'Planner', status: 'completed' }],
          ['verifier', { nodeId: 'verifier', label: 'Verifier', status: 'running' }],
        ]),
        handoffs: [
          {
            fromNodeId: 'planner',
            toNodeId: 'verifier',
            fromLabel: 'Planner',
            toLabel: 'Verifier',
            contextSummary: 'handoff summary',
            timestamp: 123,
          },
        ],
      }),
      null
    );

    expect(model?.edges).toContainEqual({
      id: 'handoff:planner:verifier:123',
      sourceId: 'planner',
      targetId: 'verifier',
      kind: 'handoff',
      label: 'handoff summary',
    });
  });
});
