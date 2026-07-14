import type { AgentPlanTask } from '../../types';

export type NewTaskKind = 'general' | 'programming';

export type NewTaskDefinition = {
  title: string;
  objective: string;
  kind: NewTaskKind;
  workspaceRoot?: string;
};

export function buildPlanningPrompt(definition: NewTaskDefinition): string {
  const codeContext =
    definition.kind === 'programming'
      ? `\nCode workspace: ${definition.workspaceRoot?.trim() || 'Use the configured workspace root.'}`
      : '';
  return [
    'Work in Plan mode. Analyze the objective without changing files or executing the solution.',
    'Inspect only the context needed to make the plan concrete.',
    'Publish the final plan through the available structured task-list tool.',
    'On MemStack cloud use todowrite with action="replace". In the local desktop runtime call submit_plan with JSON input {"tasks":[{"content":"actionable step","priority":"high|medium|low"}]}.',
    'Every task must be actionable, ordered, and independently reviewable by a human.',
    'Do not start implementation until the human explicitly approves the plan.',
    `Task title: ${definition.title.trim()}`,
    `Objective: ${definition.objective.trim()}${codeContext}`,
  ].join('\n\n');
}

export function buildRevisionPrompt(feedback: string): string {
  return [
    'The human reviewed the current plan and requested a revision.',
    `Feedback: ${feedback.trim()}`,
    'Remain in Plan mode. Update the structured task list in full and do not implement anything.',
  ].join('\n\n');
}

export function buildExecutionPrompt(): string {
  return [
    'The human approved the current structured plan.',
    'Build mode is now active. Execute the approved tasks in order.',
    'Keep the task list status current and pause for any permission, credential, or irreversible decision.',
  ].join('\n\n');
}

export function planTaskSignature(tasks: AgentPlanTask[]): string {
  return [...tasks]
    .sort((left, right) => left.order_index - right.order_index)
    .map((task) => `${task.order_index}:${task.priority}:${task.content}:${task.updated_at}`)
    .join('|');
}

export function orderedPlanTasks(tasks: AgentPlanTask[]): AgentPlanTask[] {
  return [...tasks].sort((left, right) => left.order_index - right.order_index);
}
