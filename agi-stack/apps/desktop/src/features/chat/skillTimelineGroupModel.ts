import type { AgentTimelineItem } from '../../types';

export type SkillTimelineStatus =
  | 'matched'
  | 'executing'
  | 'completed'
  | 'failed'
  | 'fallback';

export type SkillToolStepStatus = 'pending' | 'running' | 'completed' | 'error';

export type SkillToolStep = {
  key: string;
  stepIndex: number;
  toolName: string;
  input: unknown;
  result: unknown;
  error: string;
  durationMs: number | null;
  status: SkillToolStepStatus;
};

export type SkillTimelineGroup = {
  id: string;
  startItemId: string;
  itemIds: string[];
  items: AgentTimelineItem[];
  skillId: string;
  skillName: string;
  status: SkillTimelineStatus;
  executionMode: string;
  matchScore: number | null;
  tools: string[];
  query: string;
  currentStep: number;
  totalSteps: number;
  toolSteps: SkillToolStep[];
  summary: string;
  error: string;
  reason: string;
  executionTimeMs: number | null;
};

export type SkillTimelineGrouping = {
  groups: SkillTimelineGroup[];
  claimedItemIds: string[];
};

const skillEventTypes = new Set([
  'skill_matched',
  'skill_execution_start',
  'skill_tool_start',
  'skill_tool_result',
  'skill_execution_complete',
  'skill_fallback',
]);

const terminalSkillEventTypes = new Set(['skill_execution_complete', 'skill_fallback']);

export function isSkillTimelineEvent(item: AgentTimelineItem): boolean {
  return skillEventTypes.has(item.type);
}

export function groupSkillTimelineItems(
  items: readonly AgentTimelineItem[],
): SkillTimelineGrouping {
  const groups: SkillTimelineGroup[] = [];
  const claimedIndexes = new Set<number>();

  for (let index = 0; index < items.length; index += 1) {
    const first = items[index];
    if (!first || claimedIndexes.has(index) || !isSkillTimelineEvent(first)) continue;

    const groupedIndexes = [index];
    const groupedItems = [first];
    for (let cursor = index + 1; cursor < items.length; cursor += 1) {
      const candidate = items[cursor];
      if (!candidate || claimedIndexes.has(cursor) || !isSkillTimelineEvent(candidate)) continue;
      if (!compatibleSkillEvent(groupedItems, candidate)) continue;
      if (startsAnotherSkillExecution(groupedItems, candidate)) break;
      groupedIndexes.push(cursor);
      groupedItems.push(candidate);
      if (terminalSkillEventTypes.has(candidate.type)) break;
    }

    groupedIndexes.forEach((claimedIndex) => claimedIndexes.add(claimedIndex));
    groups.push(buildSkillTimelineGroup(groupedItems));
  }

  return {
    groups,
    claimedItemIds: items.flatMap((item, index) => (claimedIndexes.has(index) ? [item.id] : [])),
  };
}

function compatibleSkillEvent(
  items: readonly AgentTimelineItem[],
  candidate: AgentTimelineItem,
): boolean {
  const known = skillIdentity(items);
  const incoming = eventSkillIdentity(candidate);
  if (known.id && incoming.id) return known.id === incoming.id;
  if (known.name && incoming.name) return known.name === incoming.name;
  return !known.id && !known.name && !incoming.id && !incoming.name;
}

function startsAnotherSkillExecution(
  items: readonly AgentTimelineItem[],
  candidate: AgentTimelineItem,
): boolean {
  if (candidate.type === 'skill_matched') {
    return items.some((item) => item.type === 'skill_matched');
  }
  if (candidate.type === 'skill_execution_start') {
    return items.some(
      (item) =>
        item.type === 'skill_execution_start' ||
        item.type === 'skill_tool_start' ||
        item.type === 'skill_tool_result',
    );
  }
  return false;
}

type SkillIdentity = { id: string; name: string };

function skillIdentity(items: readonly AgentTimelineItem[]): SkillIdentity {
  const identity: SkillIdentity = { id: '', name: '' };
  for (const item of items) {
    const candidate = eventSkillIdentity(item);
    identity.id ||= candidate.id;
    identity.name ||= candidate.name;
  }
  return identity;
}

function eventSkillIdentity(item: AgentTimelineItem): SkillIdentity {
  return {
    id: eventString(item, ['skill_id', 'skillId']),
    name: eventString(item, ['skill_name', 'skillName']),
  };
}

function buildSkillTimelineGroup(items: AgentTimelineItem[]): SkillTimelineGroup {
  const first = items[0] as AgentTimelineItem;
  const last = items[items.length - 1] as AgentTimelineItem;
  const identity = skillIdentity(items);
  const tools: string[] = [];
  let status: SkillTimelineStatus = 'matched';
  let executionMode = '';
  let matchScore: number | null = null;
  let query = '';
  let totalSteps = 0;
  let summary = '';
  let error = '';
  let reason = '';
  let executionTimeMs: number | null = null;

  for (const item of items) {
    appendUnique(tools, eventStringArray(item, ['tools']));
    const toolName = eventString(item, ['tool_name', 'toolName']);
    if (toolName) appendUnique(tools, [toolName]);
    for (const result of eventRecordArray(item, ['tool_results', 'toolResults'])) {
      appendUnique(tools, [recordString(result, ['tool_name', 'toolName'])]);
    }
    executionMode = latestString(
      executionMode,
      eventString(item, ['execution_mode', 'executionMode']),
    );
    matchScore = latestNumber(matchScore, eventNumber(item, ['match_score', 'matchScore']));
    query = latestString(query, eventString(item, ['query']));
    totalSteps = Math.max(totalSteps, eventNumber(item, ['total_steps', 'totalSteps']) ?? 0);
    summary = latestString(summary, eventString(item, ['summary']));
    error = latestString(error, eventString(item, ['error']));
    reason = latestString(reason, eventString(item, ['reason']));
    executionTimeMs = latestNumber(
      executionTimeMs,
      eventNumber(item, ['execution_time_ms', 'executionTimeMs']),
    );
    status = skillStatus(item, status);
  }

  totalSteps = Math.max(totalSteps, tools.length);
  const stepOwner = identity.id || identity.name || first.id;
  const toolSteps = buildToolSteps(items, tools, stepOwner);
  const highestObservedStep = toolSteps.reduce(
    (highest, step) =>
      step.status === 'pending' ? highest : Math.max(highest, step.stepIndex),
    0,
  );
  const executionEnded = items.some((item) => terminalSkillEventTypes.has(item.type));
  const currentStep =
    status === 'completed' ||
    status === 'fallback' ||
    (status === 'failed' && executionEnded)
      ? totalSteps
      : highestObservedStep;

  return {
    id: `skill-group:${first.id}:${last.id}`,
    startItemId: first.id,
    itemIds: items.map((item) => item.id),
    items,
    skillId: identity.id,
    skillName: identity.name,
    status,
    executionMode,
    matchScore,
    tools,
    query,
    currentStep,
    totalSteps,
    toolSteps,
    summary,
    error,
    reason,
    executionTimeMs,
  };
}

function buildToolSteps(
  items: readonly AgentTimelineItem[],
  tools: readonly string[],
  owner: string,
): SkillToolStep[] {
  const steps = new Map<number, SkillToolStep>();
  tools.forEach((toolName, stepIndex) => {
    steps.set(stepIndex, emptyToolStep(owner, stepIndex, toolName));
  });

  for (const item of items) {
    if (item.type === 'skill_tool_start' || item.type === 'skill_tool_result') {
      const toolName = eventString(item, ['tool_name', 'toolName']);
      const explicitIndex = eventNumber(item, ['step_index', 'stepIndex']);
      const stepIndex = explicitIndex ?? Math.max(0, tools.indexOf(toolName));
      const current = steps.get(stepIndex) ?? emptyToolStep(owner, stepIndex, toolName);
      steps.set(stepIndex, {
        ...current,
        toolName: toolName || current.toolName,
        input: eventValue(item, ['tool_input', 'toolInput']) ?? current.input,
        result: eventValue(item, ['result']) ?? current.result,
        error: latestString(current.error, eventString(item, ['error'])),
        durationMs: latestNumber(
          current.durationMs,
          eventNumber(item, ['duration_ms', 'durationMs']),
        ),
        status: toolStepStatus(item, current.status),
      });
    }

    for (const [resultIndex, result] of eventRecordArray(item, [
      'tool_results',
      'toolResults',
    ]).entries()) {
      const toolName = recordString(result, ['tool_name', 'toolName']);
      const explicitIndex = recordNumber(result, ['step_index', 'stepIndex']);
      const declaredIndex = tools.indexOf(toolName);
      const stepIndex = explicitIndex ?? (declaredIndex >= 0 ? declaredIndex : resultIndex);
      const current = steps.get(stepIndex) ?? emptyToolStep(owner, stepIndex, toolName);
      const resultError = recordString(result, ['error']);
      const explicitStatus = recordString(result, ['status']).toLowerCase();
      steps.set(stepIndex, {
        ...current,
        toolName: toolName || current.toolName,
        input: recordValue(result, ['tool_input', 'toolInput']) ?? current.input,
        result: recordValue(result, ['result']) ?? current.result,
        error: latestString(current.error, resultError),
        durationMs: latestNumber(
          current.durationMs,
          recordNumber(result, ['duration_ms', 'durationMs']),
        ),
        status:
          resultError || explicitStatus === 'error' || explicitStatus === 'failed'
            ? 'error'
            : explicitStatus === 'running'
              ? 'running'
              : 'completed',
      });
    }
  }
  return [...steps.values()].sort((left, right) => left.stepIndex - right.stepIndex);
}

function emptyToolStep(owner: string, stepIndex: number, toolName: string): SkillToolStep {
  return {
    key: `${owner}:${String(stepIndex)}:${toolName}`,
    stepIndex,
    toolName,
    input: undefined,
    result: undefined,
    error: '',
    durationMs: null,
    status: 'pending',
  };
}

function skillStatus(
  item: AgentTimelineItem,
  current: SkillTimelineStatus,
): SkillTimelineStatus {
  if (item.type === 'skill_fallback') return 'fallback';
  if (item.type === 'skill_execution_complete') {
    return eventBoolean(item, ['success']) === false || Boolean(eventString(item, ['error']))
      ? 'failed'
      : 'completed';
  }
  if (item.type === 'skill_tool_result') {
    const explicitStatus = eventString(item, ['status']).toLowerCase();
    if (explicitStatus === 'error' || explicitStatus === 'failed' || eventString(item, ['error'])) {
      return 'failed';
    }
    return current === 'matched' ? 'executing' : current;
  }
  if (item.type === 'skill_execution_start' || item.type === 'skill_tool_start') {
    return 'executing';
  }
  return current;
}

function toolStepStatus(
  item: AgentTimelineItem,
  current: SkillToolStepStatus,
): SkillToolStepStatus {
  if (item.type === 'skill_tool_start') return 'running';
  const explicitStatus = eventString(item, ['status']).toLowerCase();
  if (explicitStatus === 'error' || explicitStatus === 'failed' || eventString(item, ['error'])) {
    return 'error';
  }
  return item.type === 'skill_tool_result' ? 'completed' : current;
}

function eventRecords(item: AgentTimelineItem): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [item];
  for (const value of [item.payload, item.data, item.metadata]) {
    if (isRecord(value)) records.push(value);
  }
  return records;
}

function eventString(item: AgentTimelineItem, keys: readonly string[]): string {
  for (const record of eventRecords(item)) {
    const value = recordString(record, keys);
    if (value) return value;
  }
  return '';
}

function eventNumber(item: AgentTimelineItem, keys: readonly string[]): number | null {
  for (const record of eventRecords(item)) {
    const value = recordNumber(record, keys);
    if (value !== null) return value;
  }
  return null;
}

function eventBoolean(item: AgentTimelineItem, keys: readonly string[]): boolean | null {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      const value = record[key];
      if (typeof value === 'boolean') return value;
    }
  }
  return null;
}

function eventStringArray(item: AgentTimelineItem, keys: readonly string[]): string[] {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      const value = record[key];
      if (!Array.isArray(value)) continue;
      return value.flatMap((entry) =>
        typeof entry === 'string' && entry.trim() ? [entry.trim()] : [],
      );
    }
  }
  return [];
}

function eventRecordArray(
  item: AgentTimelineItem,
  keys: readonly string[],
): Record<string, unknown>[] {
  for (const record of eventRecords(item)) {
    for (const key of keys) {
      const value = record[key];
      if (Array.isArray(value)) return value.filter(isRecord);
    }
  }
  return [];
}

function eventValue(item: AgentTimelineItem, keys: readonly string[]): unknown {
  for (const record of eventRecords(item)) {
    const value = recordValue(record, keys);
    if (value !== undefined) return value;
  }
  return undefined;
}

function recordString(record: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function recordNumber(record: Record<string, unknown>, keys: readonly string[]): number | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function recordValue(record: Record<string, unknown>, keys: readonly string[]): unknown {
  for (const key of keys) {
    if (key in record && record[key] !== undefined) return record[key];
  }
  return undefined;
}

function appendUnique(target: string[], values: readonly string[]): void {
  for (const value of values) {
    if (value && !target.includes(value)) target.push(value);
  }
}

function latestString(current: string, next: string): string {
  return next || current;
}

function latestNumber(current: number | null, next: number | null): number | null {
  return next ?? current;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
