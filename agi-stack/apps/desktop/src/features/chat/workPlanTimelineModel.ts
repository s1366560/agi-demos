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
