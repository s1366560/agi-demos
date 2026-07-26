import type { AgentTimelineItem } from '../../types';

export type WorkPlanTimelineStep = {
  stepNumber: number;
  description: string;
  expectedOutput: string | null;
};

export type WorkPlanTimelinePresentation = {
  steps: WorkPlanTimelineStep[];
  totalSteps: number;
  currentStep: number | null;
  status: string | null;
};

export function workPlanTimelinePresentation(
  item: AgentTimelineItem,
): WorkPlanTimelinePresentation | null {
  const payload = isRecord(item.payload) ? item.payload : null;
  if (item.type === 'task_list_updated') {
    const directTasks = Array.isArray(item.tasks) ? item.tasks : null;
    const payloadTasks = Array.isArray(payload?.tasks) ? payload.tasks : null;
    return taskListTimelinePresentation(directTasks ?? payloadTasks ?? []);
  }

  const directSteps = Array.isArray(item.steps) ? item.steps : null;
  const payloadSteps = Array.isArray(payload?.steps) ? payload.steps : null;
  const steps = normalizeSteps(directSteps ?? payloadSteps ?? []);

  if (!steps.length) return null;

  const declaredTotal = readInteger(item.total_steps) ?? readInteger(payload?.total_steps);
  const currentStep = readInteger(item.current_step) ?? readInteger(payload?.current_step);
  const status = readString(item.status) ?? readString(payload?.status);

  return {
    steps,
    totalSteps: declaredTotal && declaredTotal > 0 ? declaredTotal : steps.length,
    currentStep: currentStep && currentStep > 0 ? currentStep : null,
    status,
  };
}

type NormalizedTaskStep = WorkPlanTimelineStep & {
  orderIndex: number;
  status: string | null;
  sourceIndex: number;
};

function taskListTimelinePresentation(values: unknown[]): WorkPlanTimelinePresentation | null {
  const tasks = values
    .map((value, sourceIndex) => normalizeTaskStep(value, sourceIndex))
    .filter((task): task is NormalizedTaskStep => task !== null)
    .sort(
      (left, right) =>
        left.orderIndex - right.orderIndex || left.sourceIndex - right.sourceIndex,
    );
  if (!tasks.length) return null;

  const steps = tasks.map(({ description, expectedOutput }, index) => ({
    stepNumber: index + 1,
    description,
    expectedOutput,
  }));
  const currentTaskIndex = tasks.findIndex((task) => task.status === 'in_progress');

  return {
    steps,
    totalSteps: steps.length,
    currentStep: currentTaskIndex >= 0 ? currentTaskIndex + 1 : null,
    status: taskListStatus(tasks.map((task) => task.status)),
  };
}

function normalizeTaskStep(value: unknown, sourceIndex: number): NormalizedTaskStep | null {
  if (!isRecord(value)) return null;
  const description = readString(value.content) ?? readString(value.title);
  if (!description) return null;
  const orderIndex = readInteger(value.order_index) ?? readInteger(value.orderIndex);
  return {
    stepNumber: sourceIndex + 1,
    description,
    expectedOutput: null,
    orderIndex: orderIndex !== null && orderIndex >= 0 ? orderIndex : sourceIndex,
    status: readString(value.status),
    sourceIndex,
  };
}

function taskListStatus(statuses: Array<string | null>): string | null {
  if (statuses.includes('failed')) return 'failed';
  if (statuses.includes('in_progress')) return 'in_progress';
  if (statuses.every((status) => status === 'completed')) return 'completed';
  if (statuses.every((status) => status === 'cancelled')) return 'cancelled';
  if (statuses.some((status) => status === 'pending')) return 'pending';
  return null;
}

function normalizeSteps(values: unknown[]): WorkPlanTimelineStep[] {
  const steps: WorkPlanTimelineStep[] = [];
  const stepNumbers = new Set<number>();
  for (const value of values) {
    const step = normalizeStep(value);
    if (!step || stepNumbers.has(step.stepNumber)) continue;
    stepNumbers.add(step.stepNumber);
    steps.push(step);
  }
  return steps;
}

function normalizeStep(value: unknown): WorkPlanTimelineStep | null {
  if (!isRecord(value)) return null;
  const stepNumber = value.step_number ?? value.stepNumber;
  const description = value.description;
  if (
    !Number.isInteger(stepNumber) ||
    (stepNumber as number) < 1 ||
    typeof description !== 'string'
  ) {
    return null;
  }
  const normalizedDescription = description.trim();
  if (!normalizedDescription) return null;
  const expectedOutput = readString(value.expected_output) ?? readString(value.expectedOutput);
  return {
    stepNumber: stepNumber as number,
    description: normalizedDescription,
    expectedOutput,
  };
}

function readInteger(value: unknown): number | null {
  return Number.isInteger(value) ? (value as number) : null;
}

function readString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
