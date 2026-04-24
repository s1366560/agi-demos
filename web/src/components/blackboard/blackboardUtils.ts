import { deriveObjectiveProgressPct } from '@/utils/objectiveProgress';

import type {
  BlackboardPost,
  CyberObjective,
  TopologyEdge,
  TopologyNode,
  Workspace,
  WorkspaceAgent,
  WorkspaceTask,
  WorkspaceTaskStatus,
} from '@/types/workspace';

/**
 * Map a worker status string to a tailwind background token class used
 * on small status dots throughout the blackboard surface.
 */
export function statusBadgeTone(status: string | undefined): string {
  if (status === 'busy' || status === 'running') return 'bg-success';
  if (status === 'error') return 'bg-error';
  if (status === 'idle') return 'bg-text-muted dark:bg-text-muted';
  return 'bg-warning';
}


export type BlackboardCanvasActorKind = 'agent' | 'human';

export interface BlackboardCanvasActor {
  key: string;
  kind: BlackboardCanvasActorKind;
  title: string;
  statusLabel: string;
  q: number;
  r: number;
}

export interface BlackboardCanvasLink {
  id: string;
  from: { q: number; r: number };
  to: { q: number; r: number };
}

export interface BlackboardStats {
  totalTasks: number;
  completedTasks: number;
  blockedTasks: number;
  pendingAdjudicationTasks: number;
  activeAgents: number;
  humanSeats: number;
  discussions: number;
  openPosts: number;
  pinnedPosts: number;
  completionRatio: number;
}

export interface BlackboardNoteCard {
  id: string;
  kind: 'workspace' | 'objective' | 'post';
  title: string;
  summary: string;
}

const FALLBACK_AGENT_COORDS: Array<{ q: number; r: number }> = [
  { q: -1, r: 0 },
  { q: 0, r: -1 },
  { q: 1, r: -1 },
  { q: 2, r: -1 },
  { q: 2, r: 0 },
  { q: 1, r: 1 },
  { q: 0, r: 1 },
  { q: -1, r: 1 },
];

const FALLBACK_HUMAN_COORDS: Array<{ q: number; r: number }> = [
  { q: 1, r: 0 },
  { q: 1, r: 1 },
  { q: -1, r: 2 },
  { q: 2, r: -2 },
];

const PRIORITY_RANK: Record<string, number> = {
  urgent: 5,
  high: 4,
  P1: 4,
  medium: 3,
  P2: 3,
  low: 2,
  P3: 2,
  P4: 1,
};

const TASK_STATUSES: WorkspaceTaskStatus[] = ['todo', 'in_progress', 'done', 'blocked'];

function hasHexPosition(
  item: { hex_q?: number | undefined; hex_r?: number | undefined } | null | undefined
): item is { hex_q: number; hex_r: number } {
  return (
    item !== null && item !== undefined && item.hex_q !== undefined && item.hex_r !== undefined
  );
}

function getStatusLabel(status: string | undefined, isActive: boolean | undefined): string {
  if (status === 'busy') return 'busy';
  if (status === 'running') return 'running';
  if (status === 'error') return 'error';
  if (isActive) return 'active';
  return 'idle';
}

function claimCoordinate(
  preferred: { q: number; r: number } | null,
  occupied: Set<string>,
  fallbacks: Array<{ q: number; r: number }>
): { q: number; r: number } {
  if (preferred) {
    const preferredKey = `${String(preferred.q)},${String(preferred.r)}`;
    if (!occupied.has(preferredKey) && preferredKey !== '0,0') {
      occupied.add(preferredKey);
      return preferred;
    }
  }

  for (const fallback of fallbacks) {
    const fallbackKey = `${String(fallback.q)},${String(fallback.r)}`;
    if (!occupied.has(fallbackKey) && fallbackKey !== '0,0') {
      occupied.add(fallbackKey);
      return fallback;
    }
  }

  occupied.add('3,0');
  return { q: 3, r: 0 };
}

export function buildBlackboardStats(
  tasks: WorkspaceTask[],
  posts: BlackboardPost[],
  agents: WorkspaceAgent[],
  topologyNodes: TopologyNode[]
): BlackboardStats {
  const totalTasks = tasks.length;
  const completedTasks = tasks.filter((task) => task.status === 'done').length;
  const blockedTasks = tasks.filter((task) => task.status === 'blocked').length;
  const pendingAdjudicationTasks = tasks.filter(
    (task) => task.pending_leader_adjudication === true || task.metadata.pending_leader_adjudication === true
  ).length;
  const activeAgents = agents.filter(
    (agent) => agent.is_active || agent.status === 'running' || agent.status === 'busy'
  ).length;
  const humanSeats = topologyNodes.filter((node) => node.node_type === 'human_seat').length;
  const discussions = posts.length;
  const openPosts = posts.filter((post) => post.status === 'open').length;
  const pinnedPosts = posts.filter((post) => post.is_pinned).length;

  return {
    totalTasks,
    completedTasks,
    blockedTasks,
    pendingAdjudicationTasks,
    activeAgents,
    humanSeats,
    discussions,
    openPosts,
    pinnedPosts,
    completionRatio: totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0,
  };
}

export function groupTasksByStatus(
  tasks: WorkspaceTask[]
): Record<WorkspaceTaskStatus, WorkspaceTask[]> {
  const groups: Record<WorkspaceTaskStatus, WorkspaceTask[]> = {
    todo: [],
    in_progress: [],
    done: [],
    blocked: [],
  };

  for (const task of tasks) {
    if (TASK_STATUSES.includes(task.status)) {
      groups[task.status].push(task);
    }
  }

  for (const status of TASK_STATUSES) {
    groups[status].sort((left, right) => {
      const leftPriority = PRIORITY_RANK[left.priority ?? ''] ?? 0;
      const rightPriority = PRIORITY_RANK[right.priority ?? ''] ?? 0;
      if (leftPriority !== rightPriority) {
        return rightPriority - leftPriority;
      }

      return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    });
  }

  return groups;
}

export function buildCanvasActors(
  agents: WorkspaceAgent[],
  topologyNodes: TopologyNode[]
): BlackboardCanvasActor[] {
  const occupied = new Set<string>(['0,0']);
  const displayedAgents = [...agents]
    .sort((left, right) => {
      const rightHasCoords = Number(hasHexPosition(right));
      const leftHasCoords = Number(hasHexPosition(left));
      if (rightHasCoords !== leftHasCoords) {
        return rightHasCoords - leftHasCoords;
      }

      const rightActive = Number(
        right.is_active || right.status === 'running' || right.status === 'busy'
      );
      const leftActive = Number(
        left.is_active || left.status === 'running' || left.status === 'busy'
      );
      if (rightActive !== leftActive) {
        return rightActive - leftActive;
      }

      return (right.display_name ?? right.agent_id).localeCompare(
        left.display_name ?? left.agent_id
      );
    })
    .slice(0, 6);

  const actors: BlackboardCanvasActor[] = displayedAgents.map((agent, index) => {
    const preferred = hasHexPosition(agent) ? { q: agent.hex_q, r: agent.hex_r } : null;
    const fallbackCoords = FALLBACK_AGENT_COORDS.slice(index).concat(
      FALLBACK_AGENT_COORDS.slice(0, index)
    );
    const coord = claimCoordinate(preferred, occupied, fallbackCoords);

    return {
      key: `agent:${agent.id}`,
      kind: 'agent' as const,
      title: agent.display_name ?? agent.label ?? agent.agent_id,
      statusLabel: getStatusLabel(agent.status, agent.is_active),
      q: coord.q,
      r: coord.r,
    };
  });

  const displayedHumans = topologyNodes
    .filter((node) => node.node_type === 'human_seat')
    .slice(0, 2)
    .map((node, index) => {
      const preferred = hasHexPosition(node) ? { q: node.hex_q, r: node.hex_r } : null;
      const fallbackCoords = FALLBACK_HUMAN_COORDS.slice(index).concat(
        FALLBACK_HUMAN_COORDS.slice(0, index)
      );
      const coord = claimCoordinate(preferred, occupied, fallbackCoords);

      return {
        key: `human:${node.id}`,
        kind: 'human' as const,
        title: node.title || 'Human Seat',
        statusLabel: node.status ?? 'ready',
        q: coord.q,
        r: coord.r,
      };
    });

  return [...actors, ...displayedHumans];
}

export function buildCanvasLinks(
  actors: BlackboardCanvasActor[],
  topologyEdges: TopologyEdge[]
): BlackboardCanvasLink[] {
  const actorPositions = new Set(actors.map((actor) => `${String(actor.q)},${String(actor.r)}`));
  const seen = new Set<string>();
  const links: BlackboardCanvasLink[] = [];

  for (const edge of topologyEdges) {
    if (
      edge.source_hex_q === undefined ||
      edge.source_hex_r === undefined ||
      edge.target_hex_q === undefined ||
      edge.target_hex_r === undefined
    ) {
      continue;
    }

    const fromKey = `${String(edge.source_hex_q)},${String(edge.source_hex_r)}`;
    const toKey = `${String(edge.target_hex_q)},${String(edge.target_hex_r)}`;

    if (!actorPositions.has(fromKey) || !actorPositions.has(toKey)) {
      continue;
    }

    const dedupeKey = [fromKey, toKey].sort().join('::');
    if (seen.has(dedupeKey)) {
      continue;
    }

    seen.add(dedupeKey);
    links.push({
      id: edge.id,
      from: { q: edge.source_hex_q, r: edge.source_hex_r },
      to: { q: edge.target_hex_q, r: edge.target_hex_r },
    });
  }

  return links;
}

export function buildBlackboardNotes(
  workspace: Workspace | null,
  objectives: CyberObjective[],
  posts: BlackboardPost[],
  tasks: WorkspaceTask[] = []
): BlackboardNoteCard[] {
  const notes: BlackboardNoteCard[] = [];

  if (workspace?.description?.trim()) {
    notes.push({
      id: `workspace:${workspace.id}`,
      kind: 'workspace',
      title: workspace.name,
      summary: workspace.description.trim(),
    });
  }

  for (const objective of objectives.slice(0, 2)) {
    notes.push({
      id: `objective:${objective.id}`,
      kind: 'objective',
      title: objective.title,
      summary:
        objective.description?.trim() ||
        `Progress ${String(deriveObjectiveProgressPct(objective, tasks))}% · ${objective.obj_type.replace('_', ' ')}`,
    });
  }

  const pinnedPosts = posts.filter((post) => post.is_pinned).slice(0, 3);
  const fallbackPosts = pinnedPosts.length > 0 ? pinnedPosts : posts.slice(0, 3);

  for (const post of fallbackPosts) {
    notes.push({
      id: `post:${post.id}`,
      kind: 'post',
      title: post.title,
      summary: post.content.trim(),
    });
  }

  return notes.slice(0, 6);
}
