import { applyA2UIDataModelUpdate } from '@/utils/a2uiDataModel';

import {
  normalizeA2UIComponents,
  normalizeA2UIEnvelopeRecords,
  normalizeA2UIJsonLikeString,
} from './a2uiEnvelopeContract';

const FORBIDDEN_COMPONENT_KEYS = new Set(['__proto__', 'prototype', 'constructor']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isSafeComponentKey(key: string): boolean {
  return !FORBIDDEN_COMPONENT_KEYS.has(key);
}

function stripMarkdownCodeFence(input: string): string {
  const trimmed = input.trim();
  if (!trimmed.startsWith('```')) return trimmed;
  const lines = trimmed.split(/\r?\n/);
  if (lines.length < 3 || !lines[lines.length - 1]?.trim().startsWith('```')) {
    return trimmed;
  }
  return lines.slice(1, -1).join('\n').trim();
}

function collectEnvelopeRecords(input: unknown): Record<string, unknown>[] {
  if (Array.isArray(input)) {
    return input.filter((entry): entry is Record<string, unknown> => isRecord(entry));
  }
  if (!isRecord(input)) return [];
  return [input];
}

function tryParseJson(input: string): unknown {
  try {
    return JSON.parse(input) as unknown;
  } catch {
    const jsonLike = normalizeA2UIJsonLikeString(input);
    if (jsonLike === input) {
      return undefined;
    }

    try {
      return JSON.parse(jsonLike) as unknown;
    } catch {
      return undefined;
    }
  }
}

function extractJsonObjectSpans(input: string): Array<{ start: number; end: number }> {
  const spans: Array<{ start: number; end: number }> = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  let escaped = false;

  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];
    if (!char) continue;

    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === '\\') {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }

    if (char === '"') {
      inString = true;
      continue;
    }

    if (char === '{') {
      if (depth === 0) start = index;
      depth += 1;
      continue;
    }

    if (char === '}' && depth > 0) {
      depth -= 1;
      if (depth === 0 && start >= 0) {
        spans.push({ start, end: index + 1 });
        start = -1;
      }
    }
  }

  return spans;
}

function getEnvelopeSurfaceId(envelope: Record<string, unknown>): string | undefined {
  const payloads = [
    envelope.beginRendering,
    envelope.surfaceUpdate,
    envelope.dataModelUpdate,
    envelope.deleteSurface,
  ];
  for (const payload of payloads) {
    if (!isRecord(payload)) continue;
    const surfaceId = payload.surfaceId;
    if (typeof surfaceId === 'string' && surfaceId) {
      return surfaceId;
    }
  }
  return undefined;
}

function getEnvelopePayload(
  envelope: Record<string, unknown>,
  key: 'beginRendering' | 'surfaceUpdate' | 'dataModelUpdate' | 'deleteSurface'
): Record<string, unknown> | null {
  const payload = envelope[key];
  return isRecord(payload) ? payload : null;
}

function collectParsedEnvelopeRecords(messages?: string | null): Record<string, unknown>[] {
  const normalizeRecords = (records: Record<string, unknown>[]): Record<string, unknown>[] =>
    records.flatMap((record) => normalizeA2UIEnvelopeRecords(record));

  if (!messages) return [];
  const normalized = stripMarkdownCodeFence(messages);
  if (!normalized) return [];

  const parsedWhole = tryParseJson(normalized);
  if (parsedWhole !== undefined) {
    return normalizeRecords(collectEnvelopeRecords(parsedWhole));
  }

  const lines = normalized.split(/\r?\n/);
  if (lines.length > 1) {
    const lineRecords: Record<string, unknown>[] = [];
    let lineParseFailed = false;
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('```')) continue;
      const parsedLine = tryParseJson(trimmed);
      if (parsedLine === undefined) {
        lineParseFailed = true;
        break;
      }
      lineRecords.push(...collectEnvelopeRecords(parsedLine));
    }
    if (!lineParseFailed && lineRecords.length > 0) return normalizeRecords(lineRecords);
  }

  const objectRecords: Record<string, unknown>[] = [];
  const spans = extractJsonObjectSpans(normalized);
  let cursor = 0;
  for (const span of spans) {
    if (normalized.slice(cursor, span.start).trim()) return [];
    const parsedChunk = tryParseJson(normalized.slice(span.start, span.end));
    if (parsedChunk === undefined) return [];
    objectRecords.push(...collectEnvelopeRecords(parsedChunk));
    cursor = span.end;
  }
  if (normalized.slice(cursor).trim()) return [];
  return normalizeRecords(objectRecords);
}

type A2UIComponentEntry = Record<string, unknown>;
type A2UIComponents = A2UIComponentEntry[] | Record<string, A2UIComponentEntry>;
type A2UIComponentRecord = A2UIComponentEntry & { id: string };

interface A2UIMessageStreamState {
  surfaceId: string | undefined;
  root: string | undefined;
  styles: Record<string, unknown> | undefined;
  componentShape: 'array' | 'object';
  componentOrder: string[];
  componentKeysById: Map<string, string>;
  componentsById: Map<string, A2UIComponentRecord>;
  data: Record<string, unknown>;
  dataRecords: Array<Record<string, unknown>>;
}

export interface A2UIMessageStreamSnapshot {
  surfaceId?: string | undefined;
  root?: string | undefined;
  styles?: Record<string, unknown> | undefined;
  components: A2UIComponents;
  data: Record<string, unknown>;
  dataRecords: Array<Record<string, unknown>>;
}

export interface MergedA2UIMessageStream {
  messages: string;
  snapshot?: A2UIMessageStreamSnapshot | undefined;
}

function createMessageStreamState(): A2UIMessageStreamState {
  return {
    surfaceId: undefined,
    root: undefined,
    styles: undefined,
    componentShape: 'array',
    componentOrder: [],
    componentKeysById: new Map<string, string>(),
    componentsById: new Map<string, A2UIComponentRecord>(),
    data: Object.create(null) as Record<string, unknown>,
    dataRecords: [],
  };
}

function cloneValue<T>(value: T): T {
  return structuredClone(value);
}

function buildSnapshotComponents(state: A2UIMessageStreamState): A2UIComponents {
  if (state.componentShape === 'object') {
    const components = Object.create(null) as Record<string, A2UIComponentEntry>;
    let syntheticIndex = 0;
    for (const componentId of state.componentOrder) {
      const component = state.componentsById.get(componentId);
      if (!component) continue;

      const preferredKey = state.componentKeysById.get(componentId);
      const snapshotKey =
        preferredKey && isSafeComponentKey(preferredKey)
          ? preferredKey
          : isSafeComponentKey(componentId)
            ? componentId
            : `component-${String(syntheticIndex++)}`;
      components[snapshotKey] = cloneValue(component);
    }
    return components;
  }

  return state.componentOrder
    .map((componentId) => state.componentsById.get(componentId))
    .filter((component): component is A2UIComponentRecord => component !== undefined)
    .map((component) => cloneValue(component));
}

function snapshotMessageStreamState(state: A2UIMessageStreamState): A2UIMessageStreamSnapshot {
  return {
    ...(state.surfaceId ? { surfaceId: state.surfaceId } : {}),
    ...(state.root ? { root: state.root } : {}),
    ...(state.styles ? { styles: cloneValue(state.styles) } : {}),
    components: buildSnapshotComponents(state),
    data: cloneValue(state.data),
    dataRecords: cloneValue(state.dataRecords),
  };
}

function hydrateMessageStreamState(snapshot: A2UIMessageStreamSnapshot): A2UIMessageStreamState {
  const state = createMessageStreamState();
  state.surfaceId = snapshot.surfaceId;
  state.root = snapshot.root;
  state.styles = snapshot.styles ? cloneValue(snapshot.styles) : undefined;
  const normalizedComponents = normalizeA2UIComponents(snapshot.components) ?? snapshot.components;
  if (Array.isArray(normalizedComponents)) {
    state.componentShape = 'array';
    for (const rawComponent of normalizedComponents) {
      if (!isValidComponentEntry(rawComponent)) continue;
      const component = cloneValue(rawComponent);
      state.componentsById.set(component.id, component);
      if (!state.componentOrder.includes(component.id)) {
        state.componentOrder.push(component.id);
      }
    }
  } else {
    state.componentShape = 'object';
    for (const [key, rawComponent] of Object.entries(normalizedComponents)) {
      if (!isSafeComponentKey(key) || !isValidComponentEntry(rawComponent)) continue;
      const component = cloneValue(rawComponent);
      state.componentsById.set(component.id, component);
      state.componentKeysById.set(component.id, key);
      if (!state.componentOrder.includes(component.id)) {
        state.componentOrder.push(component.id);
      }
    }
  }
  state.data = cloneValue(snapshot.data);
  state.dataRecords = cloneValue(snapshot.dataRecords);
  return state;
}

function isValidComponentEntry(value: unknown): value is A2UIComponentRecord {
  return isRecord(value) && typeof value.id === 'string' && value.id.length > 0;
}

function mergeComponentEntry(
  state: A2UIMessageStreamState,
  rawComponent: A2UIComponentRecord,
  objectKey?: string
): void {
  const component = cloneValue(rawComponent);
  state.componentsById.set(component.id, component);
  if (!state.componentOrder.includes(component.id)) {
    state.componentOrder.push(component.id);
  }
  if (objectKey && isSafeComponentKey(objectKey)) {
    state.componentKeysById.set(component.id, objectKey);
  }
}

function buildDataRecord(
  dataModelUpdate: Record<string, unknown> | null
): Record<string, unknown> | null {
  if (!dataModelUpdate) return null;
  return { dataModelUpdate: { ...dataModelUpdate } };
}

function applyEnvelopeToState(
  state: A2UIMessageStreamState,
  envelope: Record<string, unknown>
): void {
  const beginRendering = getEnvelopePayload(envelope, 'beginRendering');
  const surfaceUpdate = getEnvelopePayload(envelope, 'surfaceUpdate');
  const dataModelUpdate = getEnvelopePayload(envelope, 'dataModelUpdate');
  const deleteSurface = getEnvelopePayload(envelope, 'deleteSurface');
  const envelopeSurfaceId = getEnvelopeSurfaceId(envelope);

  if (envelopeSurfaceId) {
    state.surfaceId = envelopeSurfaceId;
  }

  if (deleteSurface) {
    state.root = undefined;
    state.styles = undefined;
    state.componentShape = 'array';
    state.componentOrder = [];
    state.componentKeysById.clear();
    state.componentsById.clear();
    state.data = Object.create(null) as Record<string, unknown>;
    state.dataRecords = [];
    return;
  }

  if (beginRendering) {
    if (typeof beginRendering.root === 'string' && beginRendering.root) {
      state.root = beginRendering.root;
    }
    if (isRecord(beginRendering.styles)) {
      state.styles = { ...beginRendering.styles };
    }
  }

  const componentSource =
    normalizeA2UIComponents(surfaceUpdate?.components) ?? surfaceUpdate?.components;
  if (Array.isArray(componentSource)) {
    state.componentShape = 'array';
    for (const rawComponent of componentSource) {
      if (!isValidComponentEntry(rawComponent)) continue;
      mergeComponentEntry(state, rawComponent);
    }
  } else if (isRecord(componentSource)) {
    state.componentShape = 'object';
    for (const [key, rawComponent] of Object.entries(componentSource)) {
      if (!isSafeComponentKey(key) || !isValidComponentEntry(rawComponent)) continue;
      mergeComponentEntry(state, rawComponent, key);
    }
  }

  if (dataModelUpdate) {
    const path = typeof dataModelUpdate.path === 'string' ? dataModelUpdate.path : '/';
    const contents = Array.isArray(dataModelUpdate.contents) ? dataModelUpdate.contents : [];
    applyA2UIDataModelUpdate(state.data, path, contents);

    const dataRecord = buildDataRecord(dataModelUpdate);
    if (dataRecord) {
      state.dataRecords.push(dataRecord);
    }
  }
}

function serializeMessageStreamState(state: A2UIMessageStreamState): string {
  const records: Array<Record<string, unknown>> = [];
  if (state.root) {
    records.push({
      beginRendering: {
        ...(state.surfaceId ? { surfaceId: state.surfaceId } : {}),
        root: state.root,
        ...(state.styles ? { styles: state.styles } : {}),
      },
    });
  }

  if (state.componentsById.size > 0) {
    records.push({
      surfaceUpdate: {
        ...(state.surfaceId ? { surfaceId: state.surfaceId } : {}),
        components: buildSnapshotComponents(state),
      },
    });
  }

  records.push(...state.dataRecords);
  return records.map((record) => JSON.stringify(record)).join('\n');
}

function extractSingleSurfaceId(records: Record<string, unknown>[]): string | undefined {
  const surfaceIds = new Set<string>();
  for (const envelope of records) {
    const surfaceId = getEnvelopeSurfaceId(envelope);
    if (!surfaceId) continue;
    surfaceIds.add(surfaceId);
    if (surfaceIds.size > 1) return undefined;
  }
  return surfaceIds.size === 1 ? [...surfaceIds][0] : undefined;
}

export function extractA2UISurfaceId(messages?: string | null): string | undefined {
  return extractSingleSurfaceId(collectParsedEnvelopeRecords(messages));
}

export function buildA2UIMessageStreamSnapshot(
  messages?: string | null
): A2UIMessageStreamSnapshot | undefined {
  const records = collectParsedEnvelopeRecords(messages);
  if (records.length === 0) return undefined;
  if (!extractSingleSurfaceId(records)) return undefined;

  const state = createMessageStreamState();
  for (const record of records) {
    applyEnvelopeToState(state, record);
  }
  return snapshotMessageStreamState(state);
}

export function mergeA2UIMessageStreamWithSnapshot(
  previousSnapshot: A2UIMessageStreamSnapshot | undefined,
  previousMessages: string | undefined,
  incomingMessages: string
): MergedA2UIMessageStream {
  const buildIncomingResult = (): MergedA2UIMessageStream => {
    const snapshot = buildA2UIMessageStreamSnapshot(incomingMessages);
    if (!snapshot) {
      return {
        messages: incomingMessages,
        snapshot: undefined,
      };
    }

    const canonicalMessages = serializeMessageStreamState(hydrateMessageStreamState(snapshot));
    return {
      messages: canonicalMessages || incomingMessages,
      snapshot,
    };
  };

  if (!incomingMessages) {
    return {
      messages: previousMessages ?? '',
      snapshot: previousSnapshot,
    };
  }
  if (!previousMessages && !previousSnapshot) {
    return buildIncomingResult();
  }

  const incomingRecords = collectParsedEnvelopeRecords(incomingMessages);
  if (incomingRecords.length === 0) {
    return buildIncomingResult();
  }

  const hasBeginRendering = incomingRecords.some(
    (record) => getEnvelopePayload(record, 'beginRendering') !== null
  );
  const hasDeleteSurface = incomingRecords.some(
    (record) => getEnvelopePayload(record, 'deleteSurface') !== null
  );
  const hasIncrementalUpdate = incomingRecords.some(
    (record) =>
      getEnvelopePayload(record, 'surfaceUpdate') !== null ||
      getEnvelopePayload(record, 'dataModelUpdate') !== null
  );
  if (hasBeginRendering || hasDeleteSurface || !hasIncrementalUpdate) {
    return buildIncomingResult();
  }

  let state: A2UIMessageStreamState | undefined;
  if (previousSnapshot) {
    state = hydrateMessageStreamState(previousSnapshot);
  } else if (previousMessages) {
    const previousRecords = collectParsedEnvelopeRecords(previousMessages);
    if (previousRecords.length > 0) {
      state = createMessageStreamState();
      for (const record of previousRecords) {
        applyEnvelopeToState(state, record);
      }
    }
  }

  if (!state) {
    return buildIncomingResult();
  }

  const previousSurfaceId = state.surfaceId;
  const incomingSurfaceId = extractSingleSurfaceId(incomingRecords);
  if (!previousSurfaceId || !incomingSurfaceId || previousSurfaceId !== incomingSurfaceId) {
    return buildIncomingResult();
  }

  for (const record of incomingRecords) {
    applyEnvelopeToState(state, record);
  }

  const messages = serializeMessageStreamState(state);
  return {
    messages: messages || incomingMessages,
    snapshot: snapshotMessageStreamState(state),
  };
}

export function mergeA2UIMessageStream(
  previousMessages: string | undefined,
  incomingMessages: string
): string {
  return mergeA2UIMessageStreamWithSnapshot(undefined, previousMessages, incomingMessages).messages;
}
