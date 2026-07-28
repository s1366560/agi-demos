export const DESKTOP_A2UI_COMPONENT_TYPES = [
  'Text',
  'Button',
  'Card',
  'Column',
  'List',
  'Row',
  'TextField',
  'Divider',
  'Image',
  'Checkbox',
  'Select',
  'Radio',
  'Badge',
  'Tabs',
  'Modal',
  'Table',
  'Progress',
] as const;

export type DesktopA2UIComponentType = (typeof DESKTOP_A2UI_COMPONENT_TYPES)[number];

export type A2UIComponentNode = {
  id: string;
  component: Record<string, unknown>;
};

export type A2UISurfaceState = {
  status: 'empty' | 'ready' | 'deleted' | 'invalid';
  surfaceId: string | null;
  rootId: string | null;
  components: Record<string, A2UIComponentNode>;
  dataModel: Record<string, unknown>;
  errorCode: A2UISurfaceErrorCode | null;
};

export type A2UISurfaceErrorCode =
  | 'a2ui_payload_empty'
  | 'a2ui_payload_too_large'
  | 'a2ui_record_limit_exceeded'
  | 'a2ui_payload_malformed'
  | 'a2ui_payload_unsafe'
  | 'a2ui_envelope_invalid'
  | 'a2ui_surface_mismatch'
  | 'a2ui_root_missing'
  | 'a2ui_component_invalid'
  | 'a2ui_component_unsupported'
  | 'a2ui_component_limit_exceeded'
  | 'a2ui_component_missing'
  | 'a2ui_tree_cycle'
  | 'a2ui_tree_depth_exceeded'
  | 'a2ui_data_path_invalid';

export type A2UIAllowedAction = {
  source_component_id?: string;
  sourceComponentId?: string;
  action_name?: string;
  actionName?: string;
};

export type A2UIActionCommand = {
  contract_version: 1;
  request_id: string;
  surface_id: string;
  source_component_id: string;
  action_name: string;
  authority_revision: number;
  idempotency_key: string;
  context?: Record<string, string | number | boolean>;
};

export type CreateA2UIActionCommandInput = {
  requestId: string;
  surfaceId: string;
  sourceComponentId: string;
  actionName: string;
  authorityRevision: number;
  idempotencyKey: string;
  allowedActions: A2UIAllowedAction[];
  context?: unknown;
};

export type CreateA2UIActionCommandResult =
  | { ok: true; command: A2UIActionCommand }
  | {
      ok: false;
      reasonCode:
        | 'a2ui_action_contract_invalid'
        | 'a2ui_action_not_allowed'
        | 'a2ui_action_context_invalid';
    };

type JsonRecord = Record<string, unknown>;

const MAX_PAYLOAD_BYTES = 128 * 1024;
const MAX_RECORDS = 128;
const MAX_COMPONENTS = 128;
const MAX_TREE_DEPTH = 32;
const MAX_JSON_NODES = 2_048;
const MAX_DATA_PATH_DEPTH = 32;
const MAX_ACTIONS = 32;
const MAX_ACTION_CONTEXT_ENTRIES = 32;
const MAX_ACTION_CONTEXT_KEY_BYTES = 128;
const MAX_ACTION_CONTEXT_STRING_BYTES = 4 * 1024;
const MAX_ACTION_CONTEXT_BYTES = 16 * 1024;
const MAX_IDENTIFIER_BYTES = 512;
const DANGEROUS_KEYS = new Set(['__proto__', 'prototype', 'constructor']);
const COMPONENT_TYPES = new Set<string>(DESKTOP_A2UI_COMPONENT_TYPES);
const COMPONENT_ALIASES = new Map<string, DesktopA2UIComponentType>([
  ['CheckBox', 'Checkbox'],
  ['MultipleChoice', 'Select'],
]);
const UTF8_ENCODER = new TextEncoder();

export function createEmptyA2UISurfaceState(): A2UISurfaceState {
  return {
    status: 'empty',
    surfaceId: null,
    rootId: null,
    components: {},
    dataModel: {},
    errorCode: null,
  };
}

export function applyA2UISurfaceMessages(
  previous: A2UISurfaceState,
  jsonl: string,
): A2UISurfaceState {
  if (utf8Bytes(jsonl) > MAX_PAYLOAD_BYTES) {
    return invalidState('a2ui_payload_too_large');
  }

  const lines = jsonl.split(/\r?\n/u).filter((line) => line.trim());
  if (lines.length === 0) return invalidState('a2ui_payload_empty');
  if (lines.length > MAX_RECORDS) return invalidState('a2ui_record_limit_exceeded');

  let state = cloneState(previous);
  let batchSurfaceId: string | null = null;
  let beginCount = 0;
  let didDelete = false;

  for (const line of lines) {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      return invalidState('a2ui_payload_malformed');
    }
    if (!isSafeJsonTree(parsed)) return invalidState('a2ui_payload_unsafe');

    const envelope = asRecord(parsed);
    if (!envelope) return invalidState('a2ui_envelope_invalid');
    const envelopeKeys = [
      'beginRendering',
      'surfaceUpdate',
      'dataModelUpdate',
      'deleteSurface',
    ].filter((key) => Object.prototype.hasOwnProperty.call(envelope, key));
    if (envelopeKeys.length !== 1) return invalidState('a2ui_envelope_invalid');

    const envelopeKey = envelopeKeys[0];
    const payload = envelopeKey ? asRecord(envelope[envelopeKey]) : null;
    if (!envelopeKey || !payload) return invalidState('a2ui_envelope_invalid');
    const surfaceId = identifier(payload.surfaceId ?? payload.surface_id);
    if (!surfaceId) return invalidState('a2ui_envelope_invalid');
    if (batchSurfaceId !== null && batchSurfaceId !== surfaceId) {
      return invalidState('a2ui_surface_mismatch');
    }
    batchSurfaceId ??= surfaceId;

    if (envelopeKey === 'beginRendering') {
      beginCount += 1;
      const rootId = identifier(payload.root ?? payload.rootId ?? payload.root_id);
      if (
        beginCount !== 1 ||
        !rootId ||
        (state.status === 'ready' && state.surfaceId !== surfaceId)
      ) {
        return invalidState(
          beginCount !== 1 || !rootId ? 'a2ui_envelope_invalid' : 'a2ui_surface_mismatch',
        );
      }
      state = {
        status: 'empty',
        surfaceId,
        rootId,
        components: {},
        dataModel: {},
        errorCode: null,
      };
      didDelete = false;
      continue;
    }

    if (state.surfaceId !== null && state.surfaceId !== surfaceId) {
      return invalidState('a2ui_surface_mismatch');
    }
    if (state.surfaceId === null) state.surfaceId = surfaceId;

    if (envelopeKey === 'surfaceUpdate') {
      if (didDelete) return invalidState('a2ui_envelope_invalid');
      const updateComponents = payload.components;
      if (!Array.isArray(updateComponents)) return invalidState('a2ui_component_invalid');
      for (const candidate of updateComponents) {
        const normalized = normalizeComponent(candidate);
        if ('errorCode' in normalized) return invalidState(normalized.errorCode);
        if (
          !Object.prototype.hasOwnProperty.call(state.components, normalized.component.id) &&
          Object.keys(state.components).length >= MAX_COMPONENTS
        ) {
          return invalidState('a2ui_component_limit_exceeded');
        }
        defineOwn(state.components, normalized.component.id, normalized.component);
      }
      continue;
    }

    if (envelopeKey === 'dataModelUpdate') {
      if (didDelete) return invalidState('a2ui_envelope_invalid');
      const path = typeof payload.path === 'string' ? payload.path : null;
      if (!path || !Object.prototype.hasOwnProperty.call(payload, 'contents')) {
        return invalidState('a2ui_data_path_invalid');
      }
      const nextData = applyDataModelUpdate(state.dataModel, path, payload.contents);
      if (!nextData) return invalidState('a2ui_data_path_invalid');
      state.dataModel = nextData;
      continue;
    }

    if (envelopeKey === 'deleteSurface') {
      if (state.surfaceId !== surfaceId) return invalidState('a2ui_surface_mismatch');
      state = {
        status: 'deleted',
        surfaceId,
        rootId: null,
        components: {},
        dataModel: {},
        errorCode: null,
      };
      didDelete = true;
    }
  }

  if (didDelete) return state;
  if (!state.surfaceId || !state.rootId) return invalidState('a2ui_root_missing');
  if (!Object.prototype.hasOwnProperty.call(state.components, state.rootId)) {
    return invalidState('a2ui_root_missing');
  }
  const treeError = validateRenderTree(state.rootId, state.components);
  if (treeError) return invalidState(treeError);
  return { ...state, status: 'ready', errorCode: null };
}

export function createA2UIActionCommand(
  input: CreateA2UIActionCommandInput,
): CreateA2UIActionCommandResult {
  const requestId = identifier(input.requestId);
  const surfaceId = identifier(input.surfaceId);
  const componentId = identifier(input.sourceComponentId);
  const actionName = identifier(input.actionName);
  const idempotencyKey = identifier(input.idempotencyKey);
  if (
    !requestId ||
    !surfaceId ||
    !componentId ||
    !actionName ||
    !idempotencyKey ||
    idempotencyKey.length < 8 ||
    !Number.isSafeInteger(input.authorityRevision) ||
    input.authorityRevision < 0 ||
    !Array.isArray(input.allowedActions) ||
    input.allowedActions.length === 0 ||
    input.allowedActions.length > MAX_ACTIONS
  ) {
    return { ok: false, reasonCode: 'a2ui_action_contract_invalid' };
  }

  const allowed = input.allowedActions.some((candidate) => {
    const source = identifier(candidate.source_component_id ?? candidate.sourceComponentId);
    const name = identifier(candidate.action_name ?? candidate.actionName);
    return source === componentId && name === actionName;
  });
  if (!allowed) return { ok: false, reasonCode: 'a2ui_action_not_allowed' };

  const context = normalizeActionContext(input.context);
  if (context === null) return { ok: false, reasonCode: 'a2ui_action_context_invalid' };
  const command: A2UIActionCommand = {
    contract_version: 1,
    request_id: requestId,
    surface_id: surfaceId,
    source_component_id: componentId,
    action_name: actionName,
    authority_revision: input.authorityRevision,
    idempotency_key: idempotencyKey,
    ...(Object.keys(context).length > 0 ? { context } : {}),
  };
  return { ok: true, command };
}

function invalidState(errorCode: A2UISurfaceErrorCode): A2UISurfaceState {
  return {
    status: 'invalid',
    surfaceId: null,
    rootId: null,
    components: {},
    dataModel: {},
    errorCode,
  };
}

function cloneState(state: A2UISurfaceState): A2UISurfaceState {
  const components: Record<string, A2UIComponentNode> = {};
  for (const [id, component] of Object.entries(state.components)) {
    defineOwn(components, id, cloneJson(component) as A2UIComponentNode);
  }
  return {
    ...state,
    components,
    dataModel: cloneJson(state.dataModel) as Record<string, unknown>,
  };
}

function normalizeComponent(
  value: unknown,
):
  | { component: A2UIComponentNode }
  | {
      errorCode:
        | 'a2ui_payload_unsafe'
        | 'a2ui_component_invalid'
        | 'a2ui_component_unsupported';
    } {
  if (!isSafeJsonTree(value)) return { errorCode: 'a2ui_payload_unsafe' };
  const record = asRecord(value);
  const id = identifier(record?.id);
  const definition = asRecord(record?.component);
  if (!record || !id || DANGEROUS_KEYS.has(id) || !definition) {
    return { errorCode: 'a2ui_component_invalid' };
  }
  const kinds = Object.keys(definition);
  if (kinds.length !== 1) return { errorCode: 'a2ui_component_invalid' };
  const rawKind = kinds[0];
  if (!rawKind) return { errorCode: 'a2ui_component_invalid' };
  const kind = COMPONENT_ALIASES.get(rawKind) ?? rawKind;
  if (!COMPONENT_TYPES.has(kind)) return { errorCode: 'a2ui_component_unsupported' };
  const props = definition[rawKind];
  if (!asRecord(props)) return { errorCode: 'a2ui_component_invalid' };
  return {
    component: {
      id,
      component: { [kind]: cloneJson(props) },
    },
  };
}

function validateRenderTree(
  rootId: string,
  components: Record<string, A2UIComponentNode>,
): A2UISurfaceErrorCode | null {
  const walk = (componentId: string, depth: number, path: Set<string>): A2UISurfaceErrorCode | null => {
    if (depth > MAX_TREE_DEPTH) return 'a2ui_tree_depth_exceeded';
    if (path.has(componentId)) return 'a2ui_tree_cycle';
    const node = components[componentId];
    if (!node) return 'a2ui_component_missing';
    const nextPath = new Set(path);
    nextPath.add(componentId);
    for (const childId of componentChildren(node)) {
      const error = walk(childId, depth + 1, nextPath);
      if (error) return error;
    }
    return null;
  };
  return walk(rootId, 1, new Set());
}

function componentChildren(node: A2UIComponentNode): string[] {
  const definition = asRecord(node.component);
  if (!definition) return [];
  const kind = Object.keys(definition)[0];
  const props = kind ? asRecord(definition[kind]) : null;
  if (!props) return [];
  const childIds: string[] = [];
  for (const key of ['child', 'content', 'trigger']) {
    const childId = identifier(props[key]);
    if (childId) childIds.push(childId);
  }
  for (const key of ['children', 'items', 'tabs']) {
    appendChildIds(childIds, props[key]);
  }
  return [...new Set(childIds)];
}

function appendChildIds(target: string[], value: unknown): void {
  if (Array.isArray(value)) {
    for (const candidate of value) {
      const direct = identifier(candidate);
      if (direct) {
        target.push(direct);
        continue;
      }
      const record = asRecord(candidate);
      if (!record) continue;
      for (const key of ['child', 'content']) {
        const childId = identifier(record[key]);
        if (childId) target.push(childId);
      }
    }
    return;
  }
  const record = asRecord(value);
  if (!record) return;
  const explicit = record.explicitList ?? record.explicit_list;
  if (!Array.isArray(explicit)) return;
  for (const candidate of explicit) {
    const childId = identifier(candidate);
    if (childId) target.push(childId);
  }
}

function applyDataModelUpdate(
  current: Record<string, unknown>,
  path: string,
  contents: unknown,
): Record<string, unknown> | null {
  if (!isSafeJsonTree(contents)) return null;
  const segments = jsonPointerSegments(path);
  if (!segments || segments.length > MAX_DATA_PATH_DEPTH) return null;
  const next = cloneJson(current) as Record<string, unknown>;
  if (segments.length === 0) {
    const replacement = asRecord(contents);
    return replacement ? (cloneJson(replacement) as Record<string, unknown>) : null;
  }

  let cursor = next;
  for (const segment of segments.slice(0, -1)) {
    const existing = asRecord(cursor[segment]);
    const child = existing ? (cloneJson(existing) as Record<string, unknown>) : {};
    defineOwn(cursor, segment, child);
    cursor = child;
  }
  const leaf = segments.at(-1);
  if (!leaf) return null;
  defineOwn(cursor, leaf, cloneJson(contents));
  return next;
}

function jsonPointerSegments(path: string): string[] | null {
  if (path === '' || path === '/') return [];
  if (!path.startsWith('/')) return null;
  const segments = path
    .slice(1)
    .split('/')
    .map((segment) => segment.replace(/~1/gu, '/').replace(/~0/gu, '~'));
  return segments.every(
    (segment) =>
      segment.length > 0 &&
      !DANGEROUS_KEYS.has(segment) &&
      utf8Bytes(segment) <= MAX_IDENTIFIER_BYTES,
  )
    ? segments
    : null;
}

function normalizeActionContext(
  value: unknown,
): Record<string, string | number | boolean> | null {
  if (value === undefined || value === null) return {};
  if (!isSafeJsonTree(value)) return null;
  const entries = actionContextEntries(value);
  if (!entries || entries.length > MAX_ACTION_CONTEXT_ENTRIES) return null;
  const context: Record<string, string | number | boolean> = {};
  for (const [key, candidate] of entries) {
    if (
      !key.trim() ||
      DANGEROUS_KEYS.has(key) ||
      utf8Bytes(key) > MAX_ACTION_CONTEXT_KEY_BYTES ||
      Object.prototype.hasOwnProperty.call(context, key)
    ) {
      return null;
    }
    const primitive = actionContextPrimitive(candidate);
    if (primitive === null) return null;
    defineOwn(context, key, primitive);
  }
  let serialized: string;
  try {
    serialized = JSON.stringify(context);
  } catch {
    return null;
  }
  return utf8Bytes(serialized) <= MAX_ACTION_CONTEXT_BYTES ? context : null;
}

function actionContextEntries(value: unknown): Array<[string, unknown]> | null {
  if (Array.isArray(value)) {
    const entries: Array<[string, unknown]> = [];
    for (const candidate of value) {
      const entry = asRecord(candidate);
      const key = identifier(entry?.key);
      if (!entry || !key || !Object.prototype.hasOwnProperty.call(entry, 'value')) return null;
      entries.push([key, entry.value]);
    }
    return entries;
  }
  const record = asRecord(value);
  return record ? Object.entries(record) : null;
}

function actionContextPrimitive(value: unknown): string | number | boolean | null {
  if (typeof value === 'string') {
    return utf8Bytes(value) <= MAX_ACTION_CONTEXT_STRING_BYTES ? value : null;
  }
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'boolean') return value;
  const literal = asRecord(value);
  if (!literal || Object.prototype.hasOwnProperty.call(literal, 'path')) return null;
  const candidates = [
    literal.literalString,
    literal.literalNumber,
    literal.literalBoolean,
    literal.literal,
  ].filter((candidate) => candidate !== undefined);
  return candidates.length === 1 ? actionContextPrimitive(candidates[0]) : null;
}

function isSafeJsonTree(value: unknown): boolean {
  let visited = 0;
  const pending = [value];
  while (pending.length > 0) {
    const current = pending.pop();
    visited += 1;
    if (visited > MAX_JSON_NODES) return false;
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

function cloneJson<T>(value: T): T {
  return structuredClone(value);
}

function asRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null ? (value as JsonRecord) : null;
}

function identifier(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  return normalized && utf8Bytes(normalized) <= MAX_IDENTIFIER_BYTES ? normalized : null;
}

function defineOwn<T>(record: Record<string, T>, key: string, value: T): void {
  Object.defineProperty(record, key, {
    configurable: true,
    enumerable: true,
    writable: true,
    value,
  });
}

function utf8Bytes(value: string): number {
  return UTF8_ENCODER.encode(value).byteLength;
}
