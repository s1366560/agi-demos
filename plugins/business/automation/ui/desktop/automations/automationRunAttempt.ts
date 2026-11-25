export type AutomationRunInput = {
  expected_revision: number;
  idempotency_key: string;
  conversation_id?: string | null;
};

export type AutomationRunReceipt = {
  receipt_id: string;
  run_id: string;
  job_id: string;
  status: string;
  duplicate: boolean;
};

type AutomationRunAttempt = {
  fingerprint: string;
  idempotencyKey: string;
};

export class AutomationRunOutcomeUnknownError extends Error {
  readonly code = 'automation_run_outcome_unknown';

  constructor() {
    super('automation run outcome is unknown');
    this.name = 'AutomationRunOutcomeUnknownError';
  }
}

export function automationRunAttemptKey(
  attempts: Map<string, AutomationRunAttempt>,
  scope: string,
  input: Omit<AutomationRunInput, 'idempotency_key'>,
  createKey: () => string = () => crypto.randomUUID(),
): string {
  const fingerprint = JSON.stringify({
    expected_revision: input.expected_revision,
    conversation_id: input.conversation_id ?? null,
  });
  const existing = attempts.get(scope);
  if (existing?.fingerprint === fingerprint) return existing.idempotencyKey;

  const idempotencyKey = `run-${createKey()}`;
  attempts.set(scope, { fingerprint, idempotencyKey });
  return idempotencyKey;
}

export function settleAutomationRunAttempt(
  attempts: Map<string, AutomationRunAttempt>,
  scope: string,
  result?: unknown,
): void {
  if (result instanceof AutomationRunOutcomeUnknownError) return;
  attempts.delete(scope);
}
