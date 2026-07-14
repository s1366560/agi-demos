const sessionAuthorityEventTypes = new Set([
  'act',
  'observe',
  'run_status',
  'run_input_queued',
  'run_input_promoted',
  'recovery_forked',
  'review_decision',
  'worktree_created',
  'environment_selected',
  'clarification_asked',
  'decision_asked',
  'env_var_requested',
  'permission_asked',
  'permission_replied',
  'clarification_answered',
  'decision_answered',
  'env_var_provided',
  'a2ui_action_asked',
  'a2ui_action_answered',
  'hitl_responded',
  'artifact_created',
  'artifact_ready',
  'artifact_error',
  'artifacts_batch',
  'artifact_approved',
  'artifact_changes_requested',
  'artifact_delivered',
  'task_list_updated',
  'task_updated',
  'task_execution_session_updated',
  'workspace_plan_updated',
]);

export function socketEventInvalidatesSessionProjection(event: unknown): boolean {
  const root = recordValue(event);
  if (!root) return false;
  const queue = [root];
  const seen = new Set<Record<string, unknown>>();
  while (queue.length) {
    const current = queue.shift();
    if (!current || seen.has(current)) continue;
    seen.add(current);
    const eventType = nonEmptyString(current.event_type) ?? nonEmptyString(current.type);
    if (eventType && sessionAuthorityEventTypes.has(eventType)) return true;
    for (const key of ['payload', 'data']) {
      const nested = recordValue(current[key]);
      if (nested) queue.push(nested);
    }
  }
  return false;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
