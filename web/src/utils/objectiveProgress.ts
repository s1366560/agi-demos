import type { CyberObjective, WorkspaceTask } from '@/types/workspace';

/**
 * Normalise a CyberObjective.progress value to a 0-100 percent.
 *
 * The backend domain validates progress as a fraction in [0.0, 1.0],
 * but several UI entry points (e.g. ObjectiveCreateModal's Slider)
 * send values on a 0-100 scale. This helper accepts either and always
 * returns a clamped integer percent.
 */
export function toPercent(raw: unknown): number {
  const n = typeof raw === 'number' && Number.isFinite(raw) ? raw : 0;
  const scaled = n > 1 ? n : n * 100;
  return Math.max(0, Math.min(100, Math.round(scaled)));
}

/**
 * Derive an objective's effective progress from its projected tasks.
 *
 * The backend does not auto-update `CyberObjective.progress` when child
 * tasks complete — it is only written via explicit PATCH. So in practice
 * the stored value stays at 0 while tasks progress underneath. To give
 * operators accurate feedback on the blackboard, we:
 *
 *   1. Prefer the explicitly stored progress when non-zero (honours
 *      manual overrides via the create/edit modal).
 *   2. Otherwise, compute done / total across the root task and its
 *      descendants, matching the logic GoalsTab already uses for its
 *      counters (metadata.objective_id + metadata.root_goal_task_id).
 *   3. Fall back to 0 when there is no root task yet.
 *
 * Always returns a clamped integer 0-100.
 */
export function deriveObjectiveProgressPct(
  objective: CyberObjective,
  tasks: WorkspaceTask[] | undefined,
): number {
  const stored = toPercent(objective.progress);
  if (stored > 0) {
    return stored;
  }
  if (!tasks || tasks.length === 0) {
    return 0;
  }
  const rootTask = tasks.find((task) => task.metadata?.objective_id === objective.id);
  if (!rootTask) {
    return 0;
  }
  const descendants = tasks.filter(
    (task) => task.id === rootTask.id || task.metadata?.root_goal_task_id === rootTask.id,
  );
  if (descendants.length === 0) {
    return 0;
  }
  const done = descendants.filter((task) => task.status === 'done').length;
  const pct = Math.round((done / descendants.length) * 100);
  return Math.max(0, Math.min(100, pct));
}
