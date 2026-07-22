import type { AgentTimelineItem, HitlType } from '../../types';

type HitlResponseContract = {
  requestType: string;
  responseType: string;
};

export type HitlResponsePresentation = {
  labelKey: string;
  value?: string;
  valueKey?: string;
};

const responseContracts: Record<string, HitlResponseContract> = {
  clarification_answered: {
    requestType: 'clarification_asked',
    responseType: 'clarification_answered',
  },
  decision_answered: {
    requestType: 'decision_asked',
    responseType: 'decision_answered',
  },
  env_var_provided: {
    requestType: 'env_var_requested',
    responseType: 'env_var_provided',
  },
  permission_replied: {
    requestType: 'permission_asked',
    responseType: 'permission_replied',
  },
  permission_granted: {
    requestType: 'permission_asked',
    responseType: 'permission_replied',
  },
  a2ui_action_answered: {
    requestType: 'a2ui_action_asked',
    responseType: 'a2ui_action_answered',
  },
  elicitation_answered: {
    requestType: 'elicitation_asked',
    responseType: 'elicitation_answered',
  },
};

const genericRequestTypes: Record<string, string> = {
  clarification: 'clarification_asked',
  decision: 'decision_asked',
  env_var: 'env_var_requested',
  permission: 'permission_asked',
  a2ui_action: 'a2ui_action_asked',
};

/**
 * Fold authoritative HITL response events into their original request cards.
 * Response events are protocol updates, not independent conversation rows.
 */
export function applyHitlResponseStreamEvent(
  existing: AgentTimelineItem[],
  event: unknown,
): { handled: boolean; items: AgentTimelineItem[] } {
  const envelope = recordValue(event);
  const eventType = stringValue(envelope?.type ?? envelope?.event_type);
  if (!eventType) return { handled: false, items: existing };
  const data = recordValue(envelope?.data) ?? recordValue(envelope?.payload) ?? envelope;
  const contract = responseContract(eventType, data);
  if (!contract) return { handled: false, items: existing };
  const requestId = stringValue(data?.request_id ?? data?.requestId);
  if (!requestId) return { handled: true, items: existing };

  let changed = false;
  const items = existing.map((item) => {
    if (item.type !== contract.requestType || timelineRequestId(item) !== requestId) return item;
    changed = true;
    return applyResponse(item, contract.responseType, data ?? {});
  });
  return { handled: true, items: changed ? items : existing };
}

/**
 * Replay persisted HITL events through the same reducer used by live streams.
 * Response-only rows are consumed even when their request is unavailable so
 * encrypted-variable and MCP elicitation values never reach generic cards.
 */
export function foldHitlResponseTimelineItems(
  items: AgentTimelineItem[],
): AgentTimelineItem[] {
  return items.reduce<AgentTimelineItem[]>((folded, item) => {
    const result = applyHitlResponseStreamEvent(folded, item);
    return result.handled ? result.items : [...folded, item];
  }, []);
}

export function hitlResponsePresentation(
  item: AgentTimelineItem,
  hitlType: HitlType,
): HitlResponsePresentation | null {
  if (!item.answered) return null;
  const payload = recordValue(item.payload);
  if (hitlType === 'clarification') {
    const value = stringValue(item.answer ?? payload?.answer);
    return value ? { labelKey: 'chat.response.answer', value } : null;
  }
  if (hitlType === 'decision') {
    const value = stringValue(item.decision ?? payload?.decision);
    return value ? { labelKey: 'chat.response.decision', value } : null;
  }
  if (hitlType === 'env_var') {
    const names = responseVariableNames(item, payload);
    return names.length
      ? { labelKey: 'chat.response.variables', value: names.join(', ') }
      : null;
  }
  if (hitlType === 'permission') {
    const granted = booleanValue(item.granted ?? payload?.granted);
    return granted === null
      ? null
      : {
          labelKey: 'chat.response.permission',
          valueKey: granted ? 'chat.response.allowed' : 'chat.response.denied',
        };
  }
  const value = stringValue(item.actionName ?? item.action_name ?? payload?.action_name);
  return value ? { labelKey: 'chat.response.action', value } : null;
}

function responseContract(
  eventType: string,
  data: Record<string, unknown> | null,
): HitlResponseContract | null {
  const direct = responseContracts[eventType];
  if (direct) return direct;
  if (eventType !== 'hitl_responded') return null;
  const hitlType = stringValue(data?.hitl_type ?? data?.hitlType);
  const requestType = hitlType ? genericRequestTypes[hitlType] : undefined;
  return requestType ? { requestType, responseType: eventType } : null;
}

function applyResponse(
  item: AgentTimelineItem,
  responseType: string,
  data: Record<string, unknown>,
): AgentTimelineItem {
  if (responseType === 'clarification_answered') {
    return { ...item, answered: true, answer: stringValue(data.answer) ?? '' };
  }
  if (responseType === 'decision_answered') {
    return { ...item, answered: true, decision: stringValue(data.decision) ?? '' };
  }
  if (responseType === 'env_var_provided') {
    return { ...item, answered: true, providedVariables: responseVariableNames(data, data) };
  }
  if (responseType === 'permission_replied') {
    const granted = booleanValue(data.granted);
    return { ...item, answered: true, ...(granted === null ? {} : { granted }) };
  }
  if (responseType === 'a2ui_action_answered') {
    const actionName = stringValue(data.action_name ?? data.actionName);
    const sourceComponentId = stringValue(
      data.source_component_id ?? data.sourceComponentId,
    );
    return {
      ...item,
      answered: true,
      ...(actionName ? { actionName } : {}),
      ...(sourceComponentId ? { sourceComponentId } : {}),
    };
  }
  if (responseType === 'elicitation_answered') {
    const response = recordValue(data.response);
    const providedFields = response ? safeRecordKeys(response) : [];
    return {
      ...item,
      answered: true,
      ...(providedFields.length ? { providedFields } : {}),
    };
  }
  return { ...item, answered: true };
}

function responseVariableNames(
  source: Record<string, unknown>,
  payload: Record<string, unknown> | null,
): string[] {
  for (const value of [
    source.providedVariables,
    source.variableNames,
    source.saved_variables,
    source.variable_names,
    payload?.providedVariables,
    payload?.variableNames,
    payload?.saved_variables,
    payload?.variable_names,
  ]) {
    if (Array.isArray(value)) {
      return [...new Set(value.flatMap((candidate) => stringListValue(candidate)))];
    }
  }
  const values = recordValue(source.values) ?? recordValue(payload?.values);
  return values
    ? [...new Set(Object.keys(values).flatMap((candidate) => stringListValue(candidate)))]
    : [];
}

function stringListValue(value: unknown): string[] {
  const normalized = stringValue(value);
  return normalized ? [normalized] : [];
}

function safeRecordKeys(value: Record<string, unknown>): string[] {
  const unsafeKeys = new Set(['__proto__', 'constructor', 'prototype']);
  return [...new Set(Object.keys(value).flatMap((key) => stringListValue(key)))].filter(
    (key) => !unsafeKeys.has(key),
  );
}

function timelineRequestId(item: AgentTimelineItem): string | null {
  const payload = recordValue(item.payload);
  return stringValue(item.requestId ?? item.request_id ?? payload?.request_id ?? payload?.requestId);
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}
