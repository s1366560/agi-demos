import type { AgentTimelineItem } from '../../types';

export type A2UIActionOption = {
  actionName: string;
  sourceComponentId: string;
  label: string;
};

export type A2UIActionView = {
  actions: A2UIActionOption[];
  reason: string | null;
};

const MAX_COMPONENT_BYTES = 64 * 1024;
const MAX_RECORDS = 128;
const MAX_COMPONENTS = 128;
const MAX_OBJECT_NODES = 512;
const DANGEROUS_KEYS = new Set(['__proto__', 'prototype', 'constructor']);

type JsonRecord = Record<string, unknown>;

export function markA2UIActionAnswered(
  existing: AgentTimelineItem[],
  event: unknown,
): AgentTimelineItem[] {
  const envelope = asRecord(event);
  const eventType = stringValue(envelope?.type ?? envelope?.event_type);
  if (eventType !== 'a2ui_action_answered') return existing;
  const data = asRecord(envelope?.data) ?? asRecord(envelope?.payload) ?? envelope;
  const requestId = stringValue(data?.request_id ?? data?.requestId);
  if (!requestId) return existing;
  return existing.map((item) => {
    if (item.type !== 'a2ui_action_asked') return item;
    const payload = asRecord(item.payload) ?? item;
    const itemRequestId = stringValue(
      item.requestId ?? item.request_id ?? payload.request_id ?? payload.requestId,
    );
    return itemRequestId === requestId ? { ...item, answered: true } : item;
  });
}

export function resolveA2UIActionView(
  item: AgentTimelineItem,
  timeline: AgentTimelineItem[],
): A2UIActionView {
  const payload = asRecord(item.payload) ?? item;
  const surfaceData = asRecord(payload.surface_data) ?? asRecord(payload.surfaceData);
  if (surfaceData && !isEmptyRecord(surfaceData.context)) {
    return unsupported('Dynamic A2UI context must be completed in the Web client.');
  }

  const allowedActions = parseAllowedActions(
    surfaceData?.allowed_actions ??
      surfaceData?.allowedActions ??
      payload.allowed_actions ??
      payload.allowedActions ??
      item.allowed_actions,
  );
  if (allowedActions.size === 0) {
    return unsupported('The server did not provide a trusted A2UI action allow-list.');
  }

  const components =
    stringValue(surfaceData?.components) ??
    stringValue(payload.components) ??
    canvasComponents(item, timeline);
  if (!components) {
    return unsupported('The original A2UI surface is unavailable in this timeline.');
  }

  const surface = parseSurface(components);
  if (!surface) {
    return unsupported('This A2UI surface uses controls that Desktop cannot safely restore.');
  }

  const reachable = reachableComponentIds(surface.root, surface.components);
  const actions: A2UIActionOption[] = [];
  for (const componentId of reachable) {
    const component = surface.components.get(componentId);
    const button = asRecord(asRecord(component?.component)?.Button);
    if (!button) continue;
    const action = asRecord(button.action);
    const actionName = stringValue(action?.name);
    const labelId = stringValue(button.child);
    if (!actionName || !labelId || !isStatelessAction(action)) continue;
    if (!allowedActions.has(actionKey(componentId, actionName))) continue;
    const label = buttonLabel(labelId, surface.components);
    if (!label) continue;
    actions.push({ actionName, sourceComponentId: componentId, label });
  }

  return actions.length > 0
    ? { actions, reason: null }
    : unsupported('No reachable stateless button matched the server action allow-list.');
}

function unsupported(reason: string): A2UIActionView {
  return { actions: [], reason };
}

function parseAllowedActions(value: unknown): Set<string> {
  if (!Array.isArray(value) || value.length > 32) return new Set();
  const actions = new Set<string>();
  for (const candidate of value) {
    const action = asRecord(candidate);
    const sourceComponentId = stringValue(action?.source_component_id ?? action?.sourceComponentId);
    const actionName = stringValue(action?.action_name ?? action?.actionName);
    if (!sourceComponentId || !actionName) return new Set();
    actions.add(actionKey(sourceComponentId, actionName));
  }
  return actions;
}

function actionKey(componentId: string, actionName: string): string {
  return `${componentId}\u0000${actionName}`;
}

function canvasComponents(item: AgentTimelineItem, timeline: AgentTimelineItem[]): string | null {
  const payload = asRecord(item.payload) ?? item;
  const blockId = stringValue(payload.block_id ?? payload.blockId ?? item.block_id ?? item.blockId);
  if (!blockId) return null;
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const candidate = timeline[index];
    if (candidate.type !== 'canvas_updated' || candidate.eventTimeUs > item.eventTimeUs) continue;
    const candidatePayload = asRecord(candidate.payload) ?? candidate;
    const candidateBlockId = stringValue(
      candidatePayload.block_id ??
        candidatePayload.blockId ??
        candidate.block_id ??
        candidate.blockId,
    );
    if (candidateBlockId !== blockId) continue;
    const block = asRecord(candidatePayload.block ?? candidate.block);
    const content = stringValue(block?.content);
    if (content) return content;
  }
  return null;
}

function parseSurface(jsonl: string): { root: string; components: Map<string, JsonRecord> } | null {
  if (!jsonl || jsonl.length > MAX_COMPONENT_BYTES) return null;
  const lines = jsonl.split(/\r?\n/u).filter((line) => line.trim());
  if (lines.length === 0 || lines.length > MAX_RECORDS) return null;
  let surfaceId: string | null = null;
  let root: string | null = null;
  const components = new Map<string, JsonRecord>();
  for (const line of lines) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      return null;
    }
    if (!isSafeJsonTree(parsed)) return null;
    const record = asRecord(parsed);
    const begin = asRecord(record?.beginRendering);
    if (begin) {
      const nextSurfaceId = stringValue(begin.surfaceId);
      const nextRoot = stringValue(begin.root);
      if (!nextSurfaceId || !nextRoot || surfaceId !== null || root !== null) return null;
      surfaceId = nextSurfaceId;
      root = nextRoot;
    }
    const update = asRecord(record?.surfaceUpdate);
    if (!update) continue;
    const updateSurfaceId = stringValue(update.surfaceId);
    if (!updateSurfaceId || (surfaceId !== null && updateSurfaceId !== surfaceId)) return null;
    surfaceId ??= updateSurfaceId;
    const updateComponents = update.components;
    if (!Array.isArray(updateComponents)) return null;
    for (const value of updateComponents) {
      const component = asRecord(value);
      const id = stringValue(component?.id);
      if (!component || !id || components.has(id) || components.size >= MAX_COMPONENTS) return null;
      components.set(id, component);
    }
  }
  if (!surfaceId || !root || !components.has(root)) return null;
  return { root, components };
}

function reachableComponentIds(root: string, components: Map<string, JsonRecord>): Set<string> {
  const reachable = new Set<string>();
  const pending = [root];
  while (pending.length > 0 && reachable.size <= MAX_COMPONENTS) {
    const id = pending.pop();
    if (!id || reachable.has(id)) continue;
    const component = components.get(id);
    if (!component) continue;
    reachable.add(id);
    for (const child of componentChildren(component)) {
      if (!reachable.has(child)) pending.push(child);
    }
  }
  return reachable;
}

function componentChildren(component: JsonRecord): string[] {
  const definition = asRecord(component.component);
  if (!definition) return [];
  const button = asRecord(definition.Button);
  const buttonChild = stringValue(button?.child);
  if (buttonChild) return [buttonChild];
  for (const kind of ['Column', 'Row']) {
    const container = asRecord(definition[kind]);
    const children = asRecord(container?.children)?.explicitList;
    if (Array.isArray(children) && children.every((child) => typeof child === 'string')) {
      return children;
    }
  }
  return [];
}

function buttonLabel(labelId: string, components: Map<string, JsonRecord>): string | null {
  const label = components.get(labelId);
  const text = asRecord(asRecord(asRecord(label?.component)?.Text)?.text);
  const literal = stringValue(text?.literalString);
  return literal && literal.length <= 200 ? literal : null;
}

function isStatelessAction(action: JsonRecord | null): boolean {
  if (!action) return false;
  const keys = Object.keys(action);
  if (keys.some((key) => key !== 'name' && key !== 'context')) return false;
  return isEmptyRecord(action.context);
}

function isEmptyRecord(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  const record = asRecord(value);
  return Boolean(record && Object.keys(record).length === 0);
}

function isSafeJsonTree(value: unknown): boolean {
  let visited = 0;
  const pending: unknown[] = [value];
  while (pending.length > 0) {
    const current = pending.pop();
    visited += 1;
    if (visited > MAX_OBJECT_NODES) return false;
    if (Array.isArray(current)) {
      pending.push(...current);
      continue;
    }
    const record = asRecord(current);
    if (!record) continue;
    for (const [key, child] of Object.entries(record)) {
      if (DANGEROUS_KEYS.has(key)) return false;
      pending.push(child);
    }
  }
  return true;
}

function asRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null ? (value as JsonRecord) : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}
