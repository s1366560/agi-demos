import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { useShallow } from 'zustand/react/shallow';

export type GraphRunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
export type GraphNodeStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'cancelled';

export interface GraphNodeState {
  nodeId: string;
  label: string;
  agentDefinitionId?: string | undefined;
  agentSessionId?: string | undefined;
  status: GraphNodeStatus;
  outputKeys?: string[] | undefined;
  errorMessage?: string | undefined;
  skipReason?: string | undefined;
  durationSeconds?: number | undefined;
  startedAt?: number | undefined;
  completedAt?: number | undefined;
}

export interface GraphHandoffRecord {
  fromNodeId: string;
  toNodeId: string;
  fromLabel: string;
  toLabel: string;
  contextSummary: string;
  timestamp: number;
}

export interface GraphRunState {
  graphRunId: string;
  graphId: string;
  graphName: string;
  pattern?: string | undefined;
  status: GraphRunStatus;
  entryNodeIds: string[];
  nodes: Map<string, GraphNodeState>;
  handoffs: GraphHandoffRecord[];
  totalSteps?: number | undefined;
  durationSeconds?: number | undefined;
  errorMessage?: string | undefined;
  failedNodeId?: string | undefined;
  cancelReason?: string | undefined;
  startedAt: number;
  completedAt?: number | undefined;
}

interface GraphState {
  runs: Map<string, GraphRunState>;
  panelOpen: boolean;
  activeRunId: string | null;

  // Run lifecycle actions
  runStarted: (
    graphRunId: string,
    graphId: string,
    graphName: string,
    pattern: string,
    entryNodeIds: string[]
  ) => void;
  runCompleted: (graphRunId: string, totalSteps: number, durationSeconds: number | null) => void;
  runFailed: (graphRunId: string, errorMessage: string, failedNodeId: string | null) => void;
  runCancelled: (graphRunId: string, reason: string) => void;

  // Node lifecycle actions
  nodeStarted: (
    graphRunId: string,
    nodeId: string,
    nodeLabel: string,
    agentDefinitionId: string,
    agentSessionId: string | null
  ) => void;
  nodeCompleted: (
    graphRunId: string,
    nodeId: string,
    outputKeys: string[],
    durationSeconds: number | null
  ) => void;
  nodeFailed: (graphRunId: string, nodeId: string, errorMessage: string) => void;
  nodeSkipped: (graphRunId: string, nodeId: string, reason: string) => void;

  // Handoff action
  handoff: (
    graphRunId: string,
    fromNodeId: string,
    toNodeId: string,
    fromLabel: string,
    toLabel: string,
    contextSummary: string
  ) => void;

  // UI actions
  togglePanel: () => void;
  setPanel: (open: boolean) => void;
  setActiveRun: (runId: string | null) => void;
  clearRun: (graphRunId: string) => void;
  clearAll: () => void;
}

function updateRunNode(
  runs: Map<string, GraphRunState>,
  graphRunId: string,
  nodeId: string,
  updater: (node: GraphNodeState) => GraphNodeState
): Map<string, GraphRunState> {
  const next = new Map(runs);
  const run = next.get(graphRunId);
  if (!run) return runs;
  const nodes = new Map(run.nodes);
  const existing = nodes.get(nodeId);
  if (existing) {
    nodes.set(nodeId, updater(existing));
  }
  next.set(graphRunId, { ...run, nodes });
  return next;
}

export const useGraphStore = create<GraphState>()(
  devtools(
    (set) => ({
      runs: new Map(),
      panelOpen: false,
      activeRunId: null,

      runStarted: (graphRunId, graphId, graphName, pattern, entryNodeIds) => {
        set((state) => {
          const next = new Map(state.runs);
          next.set(graphRunId, {
            graphRunId,
            graphId,
            graphName,
            pattern,
            status: 'running',
            entryNodeIds,
            nodes: new Map(),
            handoffs: [],
            startedAt: Date.now(),
          });
          return { runs: next, activeRunId: graphRunId, panelOpen: true };
        });
      },

      runCompleted: (graphRunId, totalSteps, durationSeconds) => {
        set((state) => {
          const next = new Map(state.runs);
          const run = next.get(graphRunId);
          if (run) {
            next.set(graphRunId, {
              ...run,
              status: 'completed',
              totalSteps,
              durationSeconds: durationSeconds ?? undefined,
              completedAt: Date.now(),
            });
          }
          return { runs: next };
        });
      },

      runFailed: (graphRunId, errorMessage, failedNodeId) => {
        set((state) => {
          const next = new Map(state.runs);
          const run = next.get(graphRunId);
          if (run) {
            next.set(graphRunId, {
              ...run,
              status: 'failed',
              errorMessage,
              failedNodeId: failedNodeId ?? undefined,
              completedAt: Date.now(),
            });
          }
          return { runs: next };
        });
      },

      runCancelled: (graphRunId, reason) => {
        set((state) => {
          const next = new Map(state.runs);
          const run = next.get(graphRunId);
          if (run) {
            next.set(graphRunId, {
              ...run,
              status: 'cancelled',
              cancelReason: reason,
              completedAt: Date.now(),
            });
          }
          return { runs: next };
        });
      },

      nodeStarted: (graphRunId, nodeId, nodeLabel, agentDefinitionId, agentSessionId) => {
        set((state) => {
          const next = new Map(state.runs);
          const run = next.get(graphRunId);
          if (!run) return state;
          const nodes = new Map(run.nodes);
          nodes.set(nodeId, {
            nodeId,
            label: nodeLabel,
            agentDefinitionId,
            agentSessionId: agentSessionId ?? undefined,
            status: 'running',
            startedAt: Date.now(),
          });
          next.set(graphRunId, { ...run, nodes });
          return { runs: next };
        });
      },

      nodeCompleted: (graphRunId, nodeId, outputKeys, durationSeconds) => {
        set((state) => ({
          runs: updateRunNode(state.runs, graphRunId, nodeId, (node) => ({
            ...node,
            status: 'completed',
            outputKeys,
            durationSeconds: durationSeconds ?? undefined,
            completedAt: Date.now(),
          })),
        }));
      },

      nodeFailed: (graphRunId, nodeId, errorMessage) => {
        set((state) => ({
          runs: updateRunNode(state.runs, graphRunId, nodeId, (node) => ({
            ...node,
            status: 'failed',
            errorMessage,
            completedAt: Date.now(),
          })),
        }));
      },

      nodeSkipped: (graphRunId, nodeId, reason) => {
        set((state) => ({
          runs: updateRunNode(state.runs, graphRunId, nodeId, (node) => ({
            ...node,
            status: 'skipped',
            skipReason: reason,
            completedAt: Date.now(),
          })),
        }));
      },

      handoff: (graphRunId, fromNodeId, toNodeId, fromLabel, toLabel, contextSummary) => {
        set((state) => {
          const next = new Map(state.runs);
          const run = next.get(graphRunId);
          if (run) {
            next.set(graphRunId, {
              ...run,
              handoffs: [
                ...run.handoffs,
                { fromNodeId, toNodeId, fromLabel, toLabel, contextSummary, timestamp: Date.now() },
              ],
            });
          }
          return { runs: next };
        });
      },

      togglePanel: () => {
        set((state) => ({ panelOpen: !state.panelOpen }));
      },

      setPanel: (open) => {
        set({ panelOpen: open });
      },

      setActiveRun: (runId) => {
        set({ activeRunId: runId });
      },

      clearRun: (graphRunId) => {
        set((state) => {
          const next = new Map(state.runs);
          next.delete(graphRunId);
          const newActiveRunId = state.activeRunId === graphRunId ? null : state.activeRunId;
          return { runs: next, activeRunId: newActiveRunId };
        });
      },

      clearAll: () => {
        set({ runs: new Map(), activeRunId: null });
      },
    }),
    { name: 'graph-store' }
  )
);

export const useGraphRuns = () =>
  useGraphStore(useShallow((state) => Array.from(state.runs.values())));

export const useActiveGraphRun = () =>
  useGraphStore((state) =>
    state.activeRunId ? (state.runs.get(state.activeRunId) ?? null) : null
  );

export const useGraphPanel = () => useGraphStore((state) => state.panelOpen);

export const useActiveGraphRunNodes = () =>
  useGraphStore(
    useShallow((state) => {
      if (!state.activeRunId) return [];
      const run = state.runs.get(state.activeRunId);
      return run ? Array.from(run.nodes.values()) : [];
    })
  );

export const useGraphActions = () =>
  useGraphStore(
    useShallow((state) => ({
      runStarted: state.runStarted,
      runCompleted: state.runCompleted,
      runFailed: state.runFailed,
      runCancelled: state.runCancelled,
      nodeStarted: state.nodeStarted,
      nodeCompleted: state.nodeCompleted,
      nodeFailed: state.nodeFailed,
      nodeSkipped: state.nodeSkipped,
      handoff: state.handoff,
      togglePanel: state.togglePanel,
      setPanel: state.setPanel,
      setActiveRun: state.setActiveRun,
      clearRun: state.clearRun,
      clearAll: state.clearAll,
    }))
  );
