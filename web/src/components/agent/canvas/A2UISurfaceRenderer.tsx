/**
 * A2UISurfaceRenderer - Renders A2UI surfaces from JSONL message strings.
 *
 * Parses the JSONL message envelope (beginRendering, surfaceUpdate,
 * dataModelUpdate) emitted by the backend canvas tool, then delegates
 * to CopilotKit's <A2UIViewer />.
 */
import { type ReactNode, Component, memo, useCallback, useMemo, useRef } from 'react';

import { A2UIViewer, type A2UIViewerProps } from '@copilotkit/a2ui-renderer';

import { useAgentV3Store } from '@/stores/agentV3';
import { useCanvasStore } from '@/stores/canvasStore';

import { agentService } from '@/services/agentService';

// ---------------------------------------------------------------------------
// Types (aligned with A2UI v0.8 ServerToClientMessage envelopes)
// ---------------------------------------------------------------------------

interface BeginRenderingPayload {
  surfaceId: string;
  root: string;
  styles?: Record<string, string>;
}

interface SurfaceUpdatePayload {
  surfaceId: string;
  components: A2UIViewerProps['components'];
}

interface DataModelUpdatePayload {
  surfaceId: string;
  path: string;
  contents: unknown[];
}

type A2UIEnvelope =
  | { beginRendering: BeginRenderingPayload }
  | { surfaceUpdate: SurfaceUpdatePayload }
  | { dataModelUpdate: DataModelUpdatePayload };

// ---------------------------------------------------------------------------
// JSONL parser
// ---------------------------------------------------------------------------

interface ParsedSurface {
  root: string;
  components: A2UIViewerProps['components'];
  data: Record<string, unknown>;
  styles: Record<string, string>;
}

interface ParsedSurfaceResult {
  parsed: ParsedSurface;
  resolvedSurfaceId?: string | undefined;
}

type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

type EnvelopeRecord = Record<string, unknown>;
const FORBIDDEN_DATA_KEYS = new Set(['__proto__', 'prototype', 'constructor']);
const PARSE_FAILED = Symbol('a2ui-parse-failed');
const A2UI_COMPONENT_KEYS = new Set([
  'Text',
  'Button',
  'Card',
  'Column',
  'Row',
  'TextField',
  'Divider',
]);

function isSafeDataKey(key: string): boolean {
  return !FORBIDDEN_DATA_KEYS.has(key);
}

function normalizeEnvelopePayload(payload: unknown): EnvelopeRecord | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  return payload as EnvelopeRecord;
}

function normalizeStringValue(input: unknown): { literal: string } | null {
  if (typeof input === 'string') return { literal: input };
  const record = normalizeEnvelopePayload(input);
  if (!record) return null;
  return typeof record.literal === 'string' ? { literal: record.literal } : null;
}

function normalizeComponentEntry(rawEntry: unknown): EnvelopeRecord | null {
  const entry = normalizeEnvelopePayload(rawEntry);
  if (!entry) return null;
  if (typeof entry.id !== 'string' || !entry.id) return null;
  const component = normalizeEnvelopePayload(entry.component);
  if (!component) return null;

  const componentKeys = Object.keys(component).filter((key) => A2UI_COMPONENT_KEYS.has(key));
  if (componentKeys.length === 0) return null;
  const componentName = componentKeys[0];
  if (!componentName) return null;

  const payload = normalizeEnvelopePayload(component[componentName]) ?? {};
  const normalizedPayload: EnvelopeRecord = { ...payload };
  const siblingStyle = normalizeEnvelopePayload(component.style);
  if (siblingStyle && !normalizeEnvelopePayload(normalizedPayload.style)) {
    normalizedPayload.style = siblingStyle;
  }

  // Unwrap {literal: "..."} values in style objects — CSS properties must be plain strings
  const styleObj = normalizeEnvelopePayload(normalizedPayload.style);
  if (styleObj) {
    const unwrappedStyle: EnvelopeRecord = {};
    for (const [key, value] of Object.entries(styleObj)) {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        const inner = value as Record<string, unknown>;
        if (typeof inner.literal === 'string') {
          unwrappedStyle[key] = inner.literal;
        } else {
          unwrappedStyle[key] = value;
        }
      } else {
        unwrappedStyle[key] = value;
      }
    }
    normalizedPayload.style = unwrappedStyle;
  }

  if (componentName === 'Text') {
    const normalizedText = normalizeStringValue(normalizedPayload.text ?? normalizedPayload.literal);
    if (normalizedText) {
      normalizedPayload.text = normalizedText;
      delete normalizedPayload.literal;
    }
  }

  if (componentName === 'Button') {
    const actionRaw = normalizedPayload.action;
    if (typeof actionRaw === 'string') {
      normalizedPayload.action = { name: actionRaw };
    } else {
      const actionObj = normalizeEnvelopePayload(actionRaw);
      if (actionObj && typeof actionObj.actionId === 'string' && typeof actionObj.name !== 'string') {
        normalizedPayload.action = { ...actionObj, name: actionObj.actionId as string };
      }
    }
    // Normalize action.context: @copilotkit/a2ui-renderer expects
    // Array<{key: string, value: {literalString?: string, ...}}> but LLM
    // generates a plain object {} or omits it entirely.
    const actionForCtx = normalizeEnvelopePayload(normalizedPayload.action);
    if (actionForCtx) {
      const ctx = actionForCtx.context;
      if (ctx !== undefined && ctx !== null && !Array.isArray(ctx)) {
        if (typeof ctx === 'object') {
          actionForCtx.context = Object.entries(ctx as Record<string, unknown>).map(
            ([key, val]) => ({ key, value: { literalString: String(val ?? '') } }),
          );
        } else {
          delete actionForCtx.context;
        }
        normalizedPayload.action = actionForCtx;
      }
    }
  }

  if (componentName === 'Card' || componentName === 'Column' || componentName === 'Row') {
    const children = normalizedPayload.children;
    if (Array.isArray(children)) {
      normalizedPayload.children = {
        explicitList: children.filter((child): child is string => typeof child === 'string'),
      };
    }
  }

  return {
    ...entry,
    component: {
      [componentName]: normalizedPayload,
    },
  };
}

function normalizeViewerComponents(
  components: A2UIViewerProps['components'],
): A2UIViewerProps['components'] {
  if (!Array.isArray(components)) return components;
  const normalized: EnvelopeRecord[] = [];
  for (const entry of components) {
    const normalizedEntry = normalizeComponentEntry(entry);
    if (!normalizedEntry) continue;
    normalized.push(normalizedEntry);
  }
  return normalized as unknown as A2UIViewerProps['components'];
}

function hasValidExplicitChildren(children: unknown): boolean {
  const childrenRecord = normalizeEnvelopePayload(children);
  if (!childrenRecord || !Array.isArray(childrenRecord.explicitList)) return false;
  return childrenRecord.explicitList.every((id) => typeof id === 'string');
}

function hasLikelyInvalidComponentShape(components: A2UIViewerProps['components']): boolean {
  if (!Array.isArray(components)) return false;
  for (const entry of components) {
    const record = normalizeEnvelopePayload(entry);
    if (!record || typeof record.id !== 'string' || !record.id) return true;
    const component = normalizeEnvelopePayload(record.component);
    if (!component) return true;
    const keys = Object.keys(component).filter((key) => A2UI_COMPONENT_KEYS.has(key));
    if (keys.length !== 1) return true;
    const componentName = keys[0];
    if (!componentName) return true;
    const payload = normalizeEnvelopePayload(component[componentName]) ?? {};

    if (componentName === 'Text') {
      if (!normalizeStringValue(payload.text)) return true;
    } else if (componentName === 'Button') {
      const actionRaw = payload.action;
      const action = normalizeEnvelopePayload(actionRaw);
      const hasValidAction =
        typeof actionRaw === 'string' ||
        (action !== null &&
          (typeof action.name === 'string' || typeof action.actionId === 'string'));
      if (typeof payload.child !== 'string' || !hasValidAction) return true;
    } else if (componentName === 'Card' || componentName === 'Column' || componentName === 'Row') {
      if (!hasValidExplicitChildren(payload.children)) return true;
    } else if (componentName === 'TextField') {
      if (!normalizeStringValue(payload.label)) return true;
    }
  }
  return false;
}

function decodeJsonString(raw: string): string | null {
  try {
    return JSON.parse(`"${raw}"`) as string;
  } catch {
    return null;
  }
}

function extractLiteralTextValues(messages: string): string[] {
  const literalRegex = /"literal"\s*:\s*"((?:\\.|[^"\\])*)"/g;
  const literalTexts: string[] = [];
  let match: RegExpExecArray | null = literalRegex.exec(messages);
  while (match) {
    const rawLiteral = match[1];
    const decoded = rawLiteral ? decodeJsonString(rawLiteral) : null;
    if (decoded && decoded.trim().length > 0) {
      literalTexts.push(decoded);
    }
    match = literalRegex.exec(messages);
  }
  return literalTexts;
}

function buildTextFallbackSurface(messages: string): ParsedSurface | null {
  const literalTexts = extractLiteralTextValues(messages);
  if (literalTexts.length === 0) return null;

  const textValues = literalTexts.slice(0, 50);
  const textComponents = textValues.map((text, index) => ({
    id: `__a2ui_fallback_text_${String(index)}`,
    component: {
      Text: {
        text: { literal: text },
      },
    },
  }));
  const childIds = textComponents.map((c) => c.id);
  const rootId = '__a2ui_text_fallback_root';
  return {
    root: rootId,
    components: [
      {
        id: rootId,
        component: {
          Column: {
            gap: '8px',
            children: { explicitList: childIds },
          },
        },
      },
      ...textComponents,
    ] as A2UIViewerProps['components'],
    data: Object.create(null) as Record<string, unknown>,
    styles: {},
  };
}

function ensureViewerSafeSurface(parsed: ParsedSurface, messages: string): ParsedSurface {
  if (!hasLikelyInvalidComponentShape(parsed.components)) return parsed;
  return buildTextFallbackSurface(messages) ?? parsed;
}

function normalizeEnvelopes(raw: unknown): unknown[] {
  if (Array.isArray(raw)) return raw;
  if (!raw || typeof raw !== 'object') return [];
  const record = raw as EnvelopeRecord;
  const messages = record.messages;
  if (Array.isArray(messages)) return messages;
  const nestedData = normalizeEnvelopePayload(record.data);
  if (nestedData && Array.isArray(nestedData.messages)) {
    return nestedData.messages;
  }
  return [record];
}

function stripMarkdownCodeFence(input: string): string {
  const trimmed = input.trim();
  if (!trimmed.startsWith('```')) return trimmed;
  const lines = trimmed.split(/\r?\n/);
  if (lines.length < 3) return trimmed;
  const firstLine = lines[0]?.trim() ?? '';
  const lastLine = lines[lines.length - 1]?.trim() ?? '';
  if (!firstLine.startsWith('```') || !lastLine.startsWith('```')) return trimmed;
  return lines.slice(1, -1).join('\n').trim();
}

function extractJsonObjects(input: string): string[] {
  const objects: string[] = [];
  let depth = 0;
  let start = -1;
  let inString = false;
  let escaped = false;

  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    if (!ch) continue;
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === '\\') {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }

    if (ch === '"') {
      inString = true;
      continue;
    }

    if (ch === '{') {
      if (depth === 0) start = i;
      depth += 1;
      continue;
    }

    if (ch === '}' && depth > 0) {
      depth -= 1;
      if (depth === 0 && start >= 0) {
        objects.push(input.slice(start, i + 1));
        start = -1;
      }
    }
  }

  return objects;
}

function repairMalformedSurfaceUpdateJson(input: string): string {
  // Pre-pass: fix empty-string-in-object corruption from LLM.
  // Pattern 1: {""} (empty string key with no value) should be {} (empty object).
  // Pattern 2: {"} (lone orphan quote in object) should be {} (empty object).
  // Also handles whitespace variants like {" "} or {""  } etc.
  let cleaned = input
    .replace(/\{\s*"\s*"\s*\}/g, '{}')
    .replace(/\{\s*"\s*\}/g, '{}');

  // Depth-aware repair: remove any '}' that would drive depth negative or
  // any '}' / ']' that would prematurely close a container.
  let result = '';
  let depth = 0;       // tracks { } nesting
  let bracketDepth = 0; // tracks [ ] nesting
  let inString = false;
  let escaped = false;
  for (let i = 0; i < cleaned.length; i += 1) {
    const ch = cleaned[i];
    if (!ch) continue;

    if (inString) {
      result += ch;
      if (escaped) {
        escaped = false;
      } else if (ch === '\\') {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }

    if (ch === '"') {
      inString = true;
      result += ch;
      continue;
    }

    if (ch === '{') {
      depth += 1;
      result += ch;
      continue;
    }
    if (ch === '[') {
      bracketDepth += 1;
      result += ch;
      continue;
    }
    if (ch === ']') {
      if (bracketDepth <= 0) continue; // skip excess ']'
      bracketDepth -= 1;
      result += ch;
      continue;
    }
    if (ch === '}') {
      if (depth <= 0) continue; // skip excess '}'
      depth -= 1;
      result += ch;
      continue;
    }
    result += ch;
  }

  // Append any missing closing braces/brackets
  while (bracketDepth > 0) {
    result += ']';
    bracketDepth -= 1;
  }
  while (depth > 0) {
    result += '}';
    depth -= 1;
  }

  return result;
}

function parseJsonRelaxed(input: string): JsonValue | typeof PARSE_FAILED {
  try {
    return JSON.parse(input) as JsonValue;
  } catch {
    // Try fixing excess braces
    const repaired = repairMalformedSurfaceUpdateJson(input);
    if (repaired !== input) {
      try {
        return JSON.parse(repaired) as JsonValue;
      } catch {
        // fall through
      }
    }
    // Try appending missing closing braces (1-4)
    for (const suffix of ['}', '}}', '}}}', '}}}}']) {
      try {
        return JSON.parse(input + suffix) as JsonValue;
      } catch {
        continue;
      }
    }
    return PARSE_FAILED;
  }
}

function extractBracketSection(
  input: string,
  startIndex: number,
  openChar: '[' | '{',
  closeChar: ']' | '}',
): string | null {
  if (startIndex < 0 || startIndex >= input.length || input[startIndex] !== openChar) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = startIndex; i < input.length; i += 1) {
    const ch = input[i];
    if (!ch) continue;
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (ch === '\\') {
        escaped = true;
      } else if (ch === '"') {
        inString = false;
      }
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === openChar) {
      depth += 1;
      continue;
    }
    if (ch === closeChar && depth > 0) {
      depth -= 1;
      if (depth === 0) {
        return input.slice(startIndex, i + 1);
      }
    }
  }
  return null;
}

function repairJsonChunk(chunk: string): string | null {
  try {
    JSON.parse(chunk);
    return chunk;
  } catch {
    for (const suffix of ['}', '}}', '}}}', '}}}}']) {
      try {
        JSON.parse(chunk + suffix);
        return chunk + suffix;
      } catch {
        continue;
      }
    }
    return null;
  }
}

function splitComponentsByIdPattern(arrayContent: string): string[] {
  const parts = arrayContent.split(/},\s*\{"id":/);
  if (parts.length <= 1) return [];
  return parts.map((part, idx) => {
    let chunk = part.trim();
    if (idx > 0) chunk = '{"id":' + chunk;
    if (!chunk.endsWith('}')) {
      for (const suffix of ['}', '}}', '}}}', '}}}}']) {
        try {
          JSON.parse(chunk + suffix);
          return chunk + suffix;
        } catch {
          continue;
        }
      }
    }
    return chunk;
  });
}

function salvageSurfaceUpdateEnvelope(line: string): EnvelopeRecord | null {
  if (!line.includes('"surfaceUpdate"') && !line.includes('"surface_update"')) return null;
  const componentsKeyIndex = line.search(/"components"\s*:/);
  if (componentsKeyIndex < 0) return null;
  const arrayStart = line.indexOf('[', componentsKeyIndex);
  if (arrayStart < 0) return null;
  const arraySection = extractBracketSection(line, arrayStart, '[', ']');
  if (!arraySection) return null;

  const arrayContent = arraySection.slice(1, -1);
  const componentObjects = extractJsonObjects(arrayContent);

  const parsedComponents: Record<string, unknown>[] = [];
  for (const chunk of componentObjects) {
    const repaired = repairJsonChunk(chunk);
    if (repaired) {
      const parsed = parseJsonRelaxed(repaired);
      if (
        parsed !== PARSE_FAILED &&
        parsed &&
        typeof parsed === 'object' &&
        !Array.isArray(parsed)
      ) {
        parsedComponents.push(parsed as Record<string, unknown>);
      }
    }
  }

  // Fallback: if we got very few components, try splitting on },{ pattern
  if (parsedComponents.length < 3 && arrayContent.includes('{"id":')) {
    const fallbackChunks = splitComponentsByIdPattern(arrayContent);
    if (fallbackChunks.length > parsedComponents.length) {
      const fallbackParsed: Record<string, unknown>[] = [];
      for (const chunk of fallbackChunks) {
        const repaired = repairJsonChunk(chunk);
        if (repaired) {
          const parsed = parseJsonRelaxed(repaired);
          if (
            parsed !== PARSE_FAILED &&
            parsed &&
            typeof parsed === 'object' &&
            !Array.isArray(parsed)
          ) {
            fallbackParsed.push(parsed as Record<string, unknown>);
          }
        }
      }
      if (fallbackParsed.length > parsedComponents.length) {
        parsedComponents.length = 0;
        parsedComponents.push(...fallbackParsed);
      }
    }
  }

  if (parsedComponents.length === 0) return null;

  const surfaceIdMatch =
    line.match(/"surfaceId"\s*:\s*"([^"]+)"/) ??
    line.match(/"surface_id"\s*:\s*"([^"]+)"/);
  const surfaceId = surfaceIdMatch?.[1];
  return surfaceId
    ? { surfaceUpdate: { surfaceId, components: parsedComponents } }
    : { surfaceUpdate: { components: parsedComponents } };
}

function extractEnvelopeList(raw: string): unknown[] {
  const normalized = stripMarkdownCodeFence(raw);
  if (!normalized) return [];

  const parsedWhole = parseJsonRelaxed(normalized);
  if (parsedWhole !== PARSE_FAILED) return normalizeEnvelopes(parsedWhole);

  const lineParsed: unknown[] = [];
  for (const line of normalized.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('```')) continue;
    // Pre-repair orphan quotes in empty objects before any parsing path
    const preRepaired = trimmed
      .replace(/\{\s*"\s*"\s*\}/g, '{}')
      .replace(/\{\s*"\s*\}/g, '{}');
    const parsedLine = parseJsonRelaxed(preRepaired);
    if (parsedLine !== PARSE_FAILED) {
      lineParsed.push(...normalizeEnvelopes(parsedLine));
      continue;
    }
    const salvagedSurfaceUpdate = salvageSurfaceUpdateEnvelope(preRepaired);
    if (salvagedSurfaceUpdate) {
      lineParsed.push(salvagedSurfaceUpdate);
    }
  }
  if (lineParsed.length > 0) return lineParsed;

  const objectParsed: unknown[] = [];
  for (const chunk of extractJsonObjects(normalized)) {
    const parsedChunk = parseJsonRelaxed(chunk);
    if (parsedChunk !== PARSE_FAILED) {
      objectParsed.push(...normalizeEnvelopes(parsedChunk));
    }
  }
  return objectParsed;
}

function getSurfaceId(payload: EnvelopeRecord | null): string | null {
  if (!payload) return null;
  const surfaceId = payload.surfaceId ?? payload.surface_id;
  return typeof surfaceId === 'string' ? surfaceId : null;
}

function hasParsedComponents(parsed: ParsedSurface): boolean {
  if (Array.isArray(parsed.components)) {
    return parsed.components.length > 0;
  }
  return Object.keys(parsed.components as Record<string, unknown>).length > 0;
}

function inferRootFromComponents(
  components: A2UIViewerProps['components'],
): { root: string; components: A2UIViewerProps['components'] } | null {
  if (!Array.isArray(components) || components.length === 0) return null;

  const componentIds: string[] = [];
  const referencedIds = new Set<string>();
  for (const entry of components) {
    if (Array.isArray(entry)) continue;
    const entryRecord = entry as unknown as Record<string, unknown>;
    const id = entryRecord.id;
    if (typeof id !== 'string' || !id) continue;
    componentIds.push(id);

    const componentPayload = entryRecord.component;
    if (!componentPayload || typeof componentPayload !== 'object' || Array.isArray(componentPayload)) {
      continue;
    }
    for (const componentDef of Object.values(componentPayload as Record<string, unknown>)) {
      if (!componentDef || typeof componentDef !== 'object' || Array.isArray(componentDef)) continue;
      const componentProps = componentDef as Record<string, unknown>;
      if (typeof componentProps.child === 'string') {
        referencedIds.add(componentProps.child);
      }
      const children = componentProps.children;
      if (!children || typeof children !== 'object' || Array.isArray(children)) continue;
      const explicitList = (children as Record<string, unknown>).explicitList;
      if (!Array.isArray(explicitList)) continue;
      for (const childId of explicitList) {
        if (typeof childId === 'string' && childId) referencedIds.add(childId);
      }
    }
  }

  if (componentIds.length === 0) return null;
  const rootCandidates = componentIds.filter((id) => !referencedIds.has(id));
  if (rootCandidates.length === 1) {
    const root = rootCandidates[0];
    if (!root) return null;
    return { root, components };
  }

  const childIds = rootCandidates.length > 0 ? rootCandidates : componentIds;
  let syntheticRootId = '__a2ui_auto_root';
  while (componentIds.includes(syntheticRootId)) {
    syntheticRootId = `${syntheticRootId}_`;
  }
  const synthesizedRoot = {
    id: syntheticRootId,
    component: {
      Column: {
        gap: '8px',
        children: { explicitList: childIds },
      },
    },
  };
  const synthesizedComponents = [...components, synthesizedRoot] as A2UIViewerProps['components'];
  return { root: syntheticRootId, components: synthesizedComponents };
}

function ensureRenderableRoot(parsed: ParsedSurface): ParsedSurface {
  if (!hasParsedComponents(parsed)) return parsed;
  if (parsed.root && Array.isArray(parsed.components)) {
    const hasRootComponent = parsed.components.some((entry) => {
      const record = normalizeEnvelopePayload(entry);
      return record?.id === parsed.root;
    });
    if (hasRootComponent) return parsed;
  } else if (parsed.root) {
    return parsed;
  }
  const inferred = inferRootFromComponents(parsed.components);
  if (!inferred) return parsed;
  return {
    ...parsed,
    root: inferred.root,
    components: inferred.components,
  };
}

function getEnvelopeSurfaceId(rawEnvelope: unknown): string | null {
  const envelope = normalizeEnvelopePayload(rawEnvelope);
  if (!envelope) return null;

  const typedPayload = typeof envelope.type === 'string'
    ? normalizeEnvelopePayload(envelope.payload)
    : null;
  const begin = normalizeEnvelopePayload(envelope.beginRendering)
    ?? normalizeEnvelopePayload(envelope.begin_rendering)
    ?? ((envelope.type === 'beginRendering' || envelope.type === 'begin_rendering')
      ? typedPayload
      : null);
  const update = normalizeEnvelopePayload(envelope.surfaceUpdate)
    ?? normalizeEnvelopePayload(envelope.surface_update)
    ?? ((envelope.type === 'surfaceUpdate' || envelope.type === 'surface_update')
      ? typedPayload
      : null);
  const dataUpdate = normalizeEnvelopePayload(envelope.dataModelUpdate)
    ?? normalizeEnvelopePayload(envelope.data_model_update)
    ?? ((envelope.type === 'dataModelUpdate' || envelope.type === 'data_model_update')
      ? typedPayload
      : null);
  return getSurfaceId(begin) ?? getSurfaceId(update) ?? getSurfaceId(dataUpdate);
}

function consumeEnvelope(result: ParsedSurface, rawEnvelope: unknown, targetSurfaceId?: string): void {
  const envelope = normalizeEnvelopePayload(rawEnvelope);
  if (!envelope) return;

  const typedPayload = typeof envelope.type === 'string'
    ? normalizeEnvelopePayload(envelope.payload)
    : null;
  const begin = normalizeEnvelopePayload(envelope.beginRendering)
    ?? normalizeEnvelopePayload(envelope.begin_rendering)
    ?? ((envelope.type === 'beginRendering' || envelope.type === 'begin_rendering')
      ? typedPayload
      : null);
  const update = normalizeEnvelopePayload(envelope.surfaceUpdate)
    ?? normalizeEnvelopePayload(envelope.surface_update)
    ?? ((envelope.type === 'surfaceUpdate' || envelope.type === 'surface_update')
      ? typedPayload
      : null);
  const dataUpdate = normalizeEnvelopePayload(envelope.dataModelUpdate)
    ?? normalizeEnvelopePayload(envelope.data_model_update)
    ?? ((envelope.type === 'dataModelUpdate' || envelope.type === 'data_model_update')
      ? typedPayload
      : null);
  const envelopeSurfaceId = getSurfaceId(begin) ?? getSurfaceId(update) ?? getSurfaceId(dataUpdate);
  if (targetSurfaceId && envelopeSurfaceId && envelopeSurfaceId !== targetSurfaceId) {
    return;
  }

  if (begin) {
    if (typeof begin.root === 'string') {
      result.root = begin.root;
    }
    if (begin.styles && typeof begin.styles === 'object' && !Array.isArray(begin.styles)) {
      result.styles = begin.styles as Record<string, string>;
    }
  } else if (typeof envelope.root === 'string') {
    result.root = envelope.root;
  }

  if (update) {
    const components = normalizeViewerComponents(update.components as A2UIViewerProps['components']);
    result.components = components;
  } else if (
    (Array.isArray(envelope.components) || (envelope.components && typeof envelope.components === 'object'))
  ) {
    result.components = normalizeViewerComponents(envelope.components as A2UIViewerProps['components']);
  }

  if (!dataUpdate) return;
  const path = typeof dataUpdate.path === 'string' ? dataUpdate.path : '/';
  const contents = Array.isArray(dataUpdate.contents) ? dataUpdate.contents : [];
  if (path === '/' || path === '') {
    for (const item of contents) {
      if (item && typeof item === 'object' && !Array.isArray(item)) {
        for (const [key, value] of Object.entries(item as Record<string, unknown>)) {
          if (!isSafeDataKey(key)) continue;
          result.data[key] = value;
        }
      }
    }
    return;
  }
  const key = path.startsWith('/') ? path.slice(1) : path;
  if (!isSafeDataKey(key)) return;
  result.data[key] = contents;
}

function parseA2UIMessages(jsonl: string, targetSurfaceId?: string): ParsedSurfaceResult {
  const buildEmptyResult = (): ParsedSurface => ({
    root: '',
    components: [],
    data: Object.create(null) as Record<string, unknown>,
    styles: {},
  });
  const parseWithTarget = (envelopes: unknown[], surfaceId?: string): ParsedSurface => {
    const parsed = buildEmptyResult();
    for (const envelope of envelopes) {
      consumeEnvelope(parsed, envelope as A2UIEnvelope, surfaceId);
    }
    return ensureRenderableRoot(parsed);
  };
  if (!jsonl) {
    return {
      parsed: buildEmptyResult(),
      resolvedSurfaceId: targetSurfaceId,
    };
  }

  const envelopes = extractEnvelopeList(jsonl);
  const parsedForTarget = ensureViewerSafeSurface(parseWithTarget(envelopes, targetSurfaceId), jsonl);
  if (!targetSurfaceId || (parsedForTarget.root && hasParsedComponents(parsedForTarget))) {
    return {
      parsed: parsedForTarget,
      resolvedSurfaceId: targetSurfaceId,
    };
  }

  const discoveredSurfaceIds = new Set<string>();
  for (const envelope of envelopes) {
    const surfaceId = getEnvelopeSurfaceId(envelope);
    if (surfaceId) discoveredSurfaceIds.add(surfaceId);
  }
  if (discoveredSurfaceIds.size === 1) {
    const [fallbackSurfaceId] = [...discoveredSurfaceIds];
    if (fallbackSurfaceId && fallbackSurfaceId !== targetSurfaceId) {
      const fallbackParsed = ensureViewerSafeSurface(
        parseWithTarget(envelopes, fallbackSurfaceId),
        jsonl,
      );
      if (fallbackParsed.root && hasParsedComponents(fallbackParsed)) {
        return {
          parsed: fallbackParsed,
          resolvedSurfaceId: fallbackSurfaceId,
        };
      }
    }
  }

  return {
    parsed: parsedForTarget,
    resolvedSurfaceId: targetSurfaceId,
  };
}

// ---------------------------------------------------------------------------
// Error Boundary -- catches renderer crashes gracefully
// ---------------------------------------------------------------------------

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class A2UIErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error('[A2UI] Renderer error:', error, info.componentStack);
  }

  override render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div className="flex flex-col items-center justify-center gap-2 p-6 text-sm text-red-500 dark:text-red-400">
          <span className="font-medium">A2UI render error</span>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {this.state.error?.message ?? 'Unknown error'}
          </span>
        </div>
      );
    }
    return this.props.children;
  }
}

interface A2UIRenderFallbackProps {
  messages: string;
}

const SURFACE_SHELL_CLASS =
  'h-full overflow-auto rounded-b-lg bg-gradient-to-b from-white to-slate-50 px-4 py-4 dark:from-slate-900 dark:to-slate-900';
const SURFACE_CARD_CLASS =
  'mx-auto w-full max-w-6xl rounded-xl border border-slate-200/80 bg-white shadow-sm ring-1 ring-slate-950/5 dark:border-slate-700/70 dark:bg-slate-900 dark:ring-white/10';

const A2UIRenderFallback = memo<A2UIRenderFallbackProps>(({ messages }) => {
  const textValues = useMemo(() => extractLiteralTextValues(messages).slice(0, 40), [messages]);
  if (textValues.length === 0) {
    return (
      <div className={SURFACE_SHELL_CLASS}>
        <div
          className={`${SURFACE_CARD_CLASS} flex min-h-[280px] items-center justify-center px-6 py-8`}
          aria-live="polite"
        >
          <div className="text-center">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Unable to render A2UI content preview.
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Showing plain message output is not available for this surface.
            </p>
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className={SURFACE_SHELL_CLASS}>
      <div className={`${SURFACE_CARD_CLASS} p-4 sm:p-5`}>
        <div className="mb-3 text-xs font-medium tracking-wide text-slate-500 dark:text-slate-400">
          A2UI Text Preview
        </div>
        <div className="flex min-w-0 flex-col gap-2">
          {textValues.map((line, index) => (
            <div
              key={`a2ui-fallback-${String(index)}`}
              className="rounded-md bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700 whitespace-pre-wrap break-words dark:bg-slate-800/60 dark:text-slate-300"
            >
              {line}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});

A2UIRenderFallback.displayName = 'A2UIRenderFallback';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface A2UISurfaceRendererProps {
  /** Surface ID for this A2UI surface */
  surfaceId: string;
  /** JSONL string containing A2UI v0.8 message envelopes */
  messages: string;
}

export const A2UISurfaceRenderer = memo<A2UISurfaceRendererProps>(({ surfaceId, messages }) => {
  const { parsed, resolvedSurfaceId } = useMemo(
    () => parseA2UIMessages(messages, surfaceId),
    [messages, surfaceId],
  );
  const effectiveSurfaceId = resolvedSurfaceId ?? surfaceId;
  const hasComponents = useMemo(() => {
    if (Array.isArray(parsed.components)) {
      return parsed.components.length > 0;
    }
    return Object.keys(parsed.components as Record<string, unknown>).length > 0;
  }, [parsed.components]);

  // Resolve conversationId from the agent store (same pattern as other agent components)
  const conversationId = useAgentV3Store((s) => s.activeConversationId);

  // Read the server-assigned HITL request_id from the canvas tab (set by
  // onA2UIActionAsked handler when the agent emits an interactive A2UI surface).
  const hitlRequestId = useCanvasStore((s) => {
    const tab =
      s.tabs.find((t) => t.a2uiSurfaceId === effectiveSurfaceId) ??
      s.tabs.find((t) => t.a2uiSurfaceId === surfaceId);
    return tab?.a2uiHitlRequestId;
  });

  // Track a sequence counter for the fallback client-generated request ID
  // (used when no server-assigned HITL request_id is available).
  const seqRef = useRef(0);

  const handleAction = useCallback(
    (action: {
      actionName: string;
      sourceComponentId: string;
      timestamp: string;
      context: Record<string, unknown>;
    }) => {
      if (!conversationId) {
        console.warn('[A2UI] No active conversation -- cannot dispatch action');
        return;
      }
      seqRef.current += 1;
      // Use the server-assigned HITL request_id if available (enables the
      // HITL coordinator Future to resolve). Fall back to a client-generated
      // sequential ID for non-interactive surfaces.
      const requestId =
        hitlRequestId ?? `a2ui_${effectiveSurfaceId}_${String(seqRef.current)}`;
      agentService
        .respondToA2UIAction(
          requestId,
          action.actionName || ((action as Record<string, unknown>).actionId as string) || 'unknown',
          action.sourceComponentId,
          action.context,
        )
        .catch((err: unknown) => {
          console.error('[A2UI] Failed to dispatch action:', err);
        });
    },
    [conversationId, effectiveSurfaceId, hitlRequestId],
  );

  // Guard: need at least a root and components to render
  if (!parsed.root || !hasComponents) {
    return (
      <div className={SURFACE_SHELL_CLASS}>
        <div
          className={`${SURFACE_CARD_CLASS} flex min-h-[280px] items-center justify-center px-6 py-8`}
          aria-live="polite"
        >
          <div className="text-center">
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Waiting for A2UI surface data...
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              The agent is still preparing this canvas panel.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={SURFACE_SHELL_CLASS}>
      <div className={`${SURFACE_CARD_CLASS} p-2 sm:p-3`}>
        <A2UIErrorBoundary fallback={<A2UIRenderFallback messages={messages} />}>
          <div className="min-w-0 rounded-lg bg-white p-2 dark:bg-slate-900">
            <A2UIViewer
              root={parsed.root}
              components={parsed.components}
              {...(Object.keys(parsed.data).length > 0 ? { data: parsed.data } : {})}
              onAction={handleAction}
              {...(Object.keys(parsed.styles).length > 0 ? { styles: parsed.styles } : {})}
            />
          </div>
        </A2UIErrorBoundary>
      </div>
    </div>
  );
});

A2UISurfaceRenderer.displayName = 'A2UISurfaceRenderer';
