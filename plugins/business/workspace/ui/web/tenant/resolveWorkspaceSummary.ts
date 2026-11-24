import type { CyberObjective, WorkspacePlanSnapshot, WorkspaceTask } from '../types/workspace';
import type { ObjectiveSummary } from './WorkspaceListView';
import {
  calculateWorkspacePlanCompletionRatio,
  getWorkspacePlanCompletionCounts,
} from '../components/blackboard/blackboardUtils';

// Domain validates CyberObjective.progress in [0.0, 1.0], but some
// UIs send 0-100. Auto-detect scale: if any value > 1, assume the
// collection is on a 0-100 scale; otherwise multiply by 100.
function normaliseProgress(items: CyberObjective[]): number[] {
  const raw = items.map((o) => (Number.isFinite(o.progress) ? o.progress : 0));
  const max = raw.reduce((m, v) => (v > m ? v : m), 0);
  const scale = max > 1 ? 1 : 100;
  return raw.map((v) => Math.max(0, Math.min(100, v * scale)));
}

function summarizeObjectives(items: CyberObjective[]): ObjectiveSummary | null {
  const objectives = items.filter((o) => o.obj_type === 'objective');
  const relevant = objectives.length > 0 ? objectives : items;
  const total = relevant.length;
  if (total === 0) return null;
  const percents = normaliseProgress(relevant);
  const sum = percents.reduce((acc, p) => acc + p, 0);
  const completed = percents.filter((p) => p >= 100).length;
  return {
    source: 'objectives',
    total: items.length,
    objectives: objectives.length,
    avgProgress: Math.round(sum / total),
    completed,
    loading: false,
  };
}

function summarizeTasks(tasks: WorkspaceTask[]): ObjectiveSummary {
  const total = tasks.length;
  if (total === 0) {
    return {
      source: 'empty',
      total: 0,
      objectives: 0,
      avgProgress: 0,
      completed: 0,
      loading: false,
    };
  }
  const completed = tasks.filter((t) => t.status === 'done').length;
  return {
    source: 'tasks',
    total,
    objectives: 0,
    avgProgress: Math.round((completed / total) * 100),
    completed,
    loading: false,
  };
}

function summarizePlanSnapshot(snapshot: WorkspacePlanSnapshot | null): ObjectiveSummary | null {
  if (!snapshot?.plan || snapshot.plan.nodes.length === 0) return null;
  const counts = getWorkspacePlanCompletionCounts(snapshot.plan, snapshot.root_goal ?? null);
  return {
    source: 'plan',
    total: counts.totalTasks,
    objectives: 0,
    avgProgress: calculateWorkspacePlanCompletionRatio(snapshot.plan, snapshot.root_goal ?? null),
    completed: counts.completedTasks,
    loading: false,
  };
}

export async function resolveWorkspaceSummary(
  items: CyberObjective[] | null,
  planSnapshot: WorkspacePlanSnapshot | null,
  loadTasks: () => Promise<WorkspaceTask[] | null>
): Promise<ObjectiveSummary> {
  const fromObjectives = summarizeObjectives(items ?? []);
  const fromPlan = summarizePlanSnapshot(planSnapshot);
  // Prefer objectives when they exist AND have any progress. Otherwise use
  // current plan nodes before falling back to historical task projections.
  const useObjectives = fromObjectives !== null && fromObjectives.avgProgress > 0;
  const resolved = useObjectives ? fromObjectives : (fromPlan ?? fromObjectives);
  if (resolved) return resolved;

  let tasks: WorkspaceTask[] | null = null;
  try {
    tasks = await loadTasks();
  } catch {
    tasks = null;
  }
  if (tasks !== null) {
    const summary = summarizeTasks(tasks);
    // Objectives and plan both failed and there are no tasks to fall back to:
    // surface a failure instead of pretending the workspace has no objectives.
    if (summary.source === 'empty' && items === null && planSnapshot === null) {
      return { ...summary, failed: true };
    }
    return summary;
  }
  return {
    source: 'empty',
    total: 0,
    objectives: 0,
    avgProgress: 0,
    completed: 0,
    loading: false,
    failed: true,
  };
}
