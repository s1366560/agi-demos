import {
  isRecord,
  optionalText,
  projectAgentError,
  requireIdentifier,
  requireText,
} from './projectAgentClient';

export type ProjectAgentRun = Readonly<{
  id: string;
  title: string;
  detail: string;
  status: string;
  createdAt: string;
  summary: string | null;
}>;

export function parseProjectAgentRuns(
  value: unknown,
  reasonCode: string,
): readonly ProjectAgentRun[] {
  if (!Array.isArray(value)) throw projectAgentError(reasonCode);
  return Object.freeze(value.map((run) => parseRun(run, reasonCode)));
}

function parseRun(value: unknown, reasonCode: string): ProjectAgentRun {
  if (!isRecord(value)) throw projectAgentError(reasonCode);
  return Object.freeze({
    id: requireIdentifier(value.run_id, reasonCode),
    title: requireIdentifier(value.subagent_name, reasonCode),
    detail: requireText(value.task, reasonCode),
    status: requireIdentifier(value.status, reasonCode),
    createdAt: requireIdentifier(value.created_at, reasonCode),
    summary: optionalText(value.summary, reasonCode),
  });
}
