/**
 * A2UISurfaceRenderer - Renders A2UI surfaces from JSONL message strings.
 *
 * Parses the JSONL message envelope (beginRendering, surfaceUpdate,
 * dataModelUpdate) emitted by the backend canvas tool, then delegates
 * to CopilotKit's <A2UIViewer />.
 */
import { type ReactNode, Component, memo, useCallback, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import {
  normalizeA2UIEnvelopeRecords,
  normalizeA2UIJsonLikeString,
} from '@/stores/agent/a2uiEnvelopeContract';
import type { A2UIMessageStreamSnapshot } from '@/stores/agent/a2uiMessages';
import { useAgentV3Store } from '@/stores/agentV3';
import { useCanvasStore } from '@/stores/canvasStore';

import { agentService } from '@/services/agentService';

import { applyA2UIDataModelUpdate } from '@/utils/a2uiDataModel';

import { MemStackA2UIViewer } from './MemStackA2UIViewer';

import type { A2UIViewerProps } from '@copilotkit/a2ui-renderer';
import type { TFunction } from 'i18next';

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

interface DeleteSurfacePayload {
  surfaceId: string;
}

type A2UIEnvelope =
  | { beginRendering: BeginRenderingPayload }
  | { surfaceUpdate: SurfaceUpdatePayload }
  | { dataModelUpdate: DataModelUpdatePayload }
  | { deleteSurface: DeleteSurfacePayload };

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
  errorMessage?: string;
}

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

type EnvelopeRecord = Record<string, unknown>;
const PARSE_FAILED = Symbol('a2ui-parse-failed');
const A2UI_COMPONENT_KEYS = new Set([
  'Text',
  'Button',
  'Card',
  'Column',
  'List',
  'Row',
  'TextField',
  'Divider',
  'Image',
  'CheckBox',
  'Checkbox',
  'MultipleChoice',
  'Select',
  'Radio',
  'Badge',
  'Tabs',
  'Modal',
  'Table',
  'Progress',
]);
const COMPONENT_VIEW_ALIASES: Record<string, string> = {
  Checkbox: 'CheckBox',
  Select: 'MultipleChoice',
  Badge: 'Text',
};
const BADGE_TONE_STYLES: Record<string, EnvelopeRecord> = {
  neutral: {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '0 8px',
    minHeight: '20px',
    borderRadius: '9999px',
    backgroundColor: '#ebebeb',
    color: '#171717',
    border: '1px solid #eaeaea',
    fontSize: '11px',
    fontWeight: '500',
    lineHeight: '20px',
  },
  success: {
    backgroundColor: '#e7f7ed',
    color: '#0a6b2d',
    border: '1px solid #b6e2c4',
  },
  warning: {
    backgroundColor: '#fff6e5',
    color: '#8a5b00',
    border: '1px solid #f1d08b',
  },
  error: {
    backgroundColor: '#fdecec',
    color: '#9f1c1c',
    border: '1px solid #f3b3b3',
  },
  info: {
    backgroundColor: '#ebf5ff',
    color: '#0059b3',
    border: '1px solid #b6d4fe',
  },
};

function normalizeEnvelopePayload(payload: unknown): EnvelopeRecord | null {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return null;
  return payload as EnvelopeRecord;
}

function normalizeStringValue(input: unknown): { literalString?: string; path?: string } | null {
  if (typeof input === 'string') return { literalString: input };
  const record = normalizeEnvelopePayload(input);
  if (!record) return null;
  const normalized: { literalString?: string; path?: string } = {};
  if (typeof record.literalString === 'string') {
    normalized.literalString = record.literalString;
  } else if (typeof record.literal === 'string') {
    normalized.literalString = record.literal;
  }
  if (typeof record.path === 'string' && record.path.trim().length > 0) {
    normalized.path = record.path;
  }
  return Object.keys(normalized).length > 0 ? normalized : null;
}

function normalizeBooleanValue(input: unknown): { literalBoolean?: boolean; path?: string } | null {
  if (typeof input === 'boolean') return { literalBoolean: input };
  const record = normalizeEnvelopePayload(input);
  if (!record) return null;
  const normalized: { literalBoolean?: boolean; path?: string } = {};
  if (typeof record.literalBoolean === 'boolean') {
    normalized.literalBoolean = record.literalBoolean;
  } else if (typeof record.literal === 'boolean') {
    normalized.literalBoolean = record.literal;
  }
  if (typeof record.path === 'string' && record.path.trim().length > 0) {
    normalized.path = record.path;
  }
  return Object.keys(normalized).length > 0 ? normalized : null;
}

function normalizeNumberValue(input: unknown): { literalNumber?: number; path?: string } | null {
  if (typeof input === 'number' && Number.isFinite(input)) return { literalNumber: input };
  const record = normalizeEnvelopePayload(input);
  if (!record) return null;
  const normalized: { literalNumber?: number; path?: string } = {};
  if (typeof record.literalNumber === 'number' && Number.isFinite(record.literalNumber)) {
    normalized.literalNumber = record.literalNumber;
  } else if (typeof record.literal === 'number' && Number.isFinite(record.literal)) {
    normalized.literalNumber = record.literal;
  }
  if (typeof record.path === 'string' && record.path.trim().length > 0) {
    normalized.path = record.path;
  }
  return Object.keys(normalized).length > 0 ? normalized : null;
}

function unwrapLiteralStringValue(input: unknown): unknown {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return input;
  }
  const record = input as Record<string, unknown>;
  if (typeof record.literalString === 'string') return record.literalString;
  if (typeof record.literal === 'string') return record.literal;
  return input;
}

function normalizeDataPath(input: unknown): string | undefined {
  if (typeof input === 'string' && input.trim().length > 0) {
    return input.startsWith('/') ? input : `/${input.replace(/^\/+/, '')}`;
  }
  const record = normalizeEnvelopePayload(input);
  if (!record) return undefined;

  const candidate =
    (typeof record.path === 'string' && record.path) ||
    (typeof record.name === 'string' && record.name) ||
    (typeof record.actionId === 'string' && record.actionId) ||
    undefined;
  if (!candidate) return undefined;
  return candidate.startsWith('/') ? candidate : `/${candidate.replace(/^\/+/, '')}`;
}

function normalizeActionContextValue(input: unknown): EnvelopeRecord | null {
  if (typeof input === 'string') return { literalString: input };
  if (typeof input === 'number') return { literalNumber: input };
  if (typeof input === 'boolean') return { literalBoolean: input };

  const record = normalizeEnvelopePayload(input);
  if (!record) return null;
  if (typeof record.path === 'string' && record.path.trim().length > 0) {
    return { path: record.path };
  }
  if (typeof record.literalString === 'string') {
    return { literalString: record.literalString };
  }
  if (typeof record.literalNumber === 'number') {
    return { literalNumber: record.literalNumber };
  }
  if (typeof record.literalBoolean === 'boolean') {
    return { literalBoolean: record.literalBoolean };
  }
  if ('literal' in record) {
    const literal = record.literal;
    if (typeof literal === 'string') return { literalString: literal };
    if (typeof literal === 'number') return { literalNumber: literal };
    if (typeof literal === 'boolean') return { literalBoolean: literal };
  }
  return null;
}

function normalizeActionContext(
  input: unknown
): Array<{ key: string; value: Record<string, unknown> }> | undefined {
  if (Array.isArray(input)) {
    const normalizedItems = input.flatMap((item) => {
      const record = normalizeEnvelopePayload(item);
      if (!record || typeof record.key !== 'string' || !record.key) return [];
      const value = normalizeActionContextValue(record.value);
      if (!value) return [];
      return [{ key: record.key, value }];
    });
    return normalizedItems.length > 0 ? normalizedItems : undefined;
  }

  const record = normalizeEnvelopePayload(input);
  if (!record) return undefined;
  const normalizedItems = Object.entries(record).flatMap(([key, value]) => {
    if (!key) return [];
    const normalizedValue = normalizeActionContextValue(value) ?? {
      literalString: JSON.stringify(value ?? ''),
    };
    return [{ key, value: normalizedValue }];
  });
  return normalizedItems.length > 0 ? normalizedItems : undefined;
}

function canonicalizeComponentName(componentName: string): string {
  return COMPONENT_VIEW_ALIASES[componentName] ?? componentName;
}

function normalizeChoiceOptions(
  input: unknown
): Array<{ label: { literalString?: string; path?: string }; value: string }> | undefined {
  if (!Array.isArray(input)) return undefined;
  const normalizedOptions = input.flatMap((option) => {
    if (typeof option === 'string' && option.trim().length > 0) {
      return [{ label: { literalString: option }, value: option }];
    }

    const record = normalizeEnvelopePayload(option);
    if (!record) return [];

    const rawValue = record.value;
    let value: string | undefined;
    if (typeof rawValue === 'string' && rawValue.trim().length > 0) {
      value = rawValue;
    } else if (typeof rawValue === 'number' || typeof rawValue === 'boolean') {
      value = String(rawValue);
    }
    if (!value) return [];

    const label = normalizeStringValue(record.label ?? record.text ?? value);
    if (!label) return [];
    return [{ label, value }];
  });
  return normalizedOptions.length > 0 ? normalizedOptions : undefined;
}

function normalizeComponentRef(input: unknown): string | undefined {
  return typeof input === 'string' && input.trim().length > 0 ? input : undefined;
}

function normalizeChildrenRef(input: unknown): { explicitList: string[] } | undefined {
  if (Array.isArray(input)) {
    const explicitList = input.filter(
      (child): child is string => typeof child === 'string' && child.trim().length > 0
    );
    if (explicitList.length !== input.length) {
      return undefined;
    }
    return { explicitList };
  }

  const record = normalizeEnvelopePayload(input);
  if (!record || !Array.isArray(record.explicitList)) return undefined;
  const explicitList = record.explicitList.filter(
    (child): child is string => typeof child === 'string' && child.trim().length > 0
  );
  if (explicitList.length !== record.explicitList.length) {
    return undefined;
  }
  return { explicitList };
}

function normalizeGapValue(input: unknown): string | undefined {
  if (typeof input === 'number' && Number.isFinite(input)) {
    return `${String(input)}px`;
  }
  if (typeof input === 'string' && input.trim().length > 0) {
    return input;
  }
  return undefined;
}

function reserveSyntheticComponentId(baseId: string, usedIds: Set<string>): string {
  let candidate = baseId;
  let suffix = 2;
  while (usedIds.has(candidate)) {
    candidate = `${baseId}_${String(suffix)}`;
    suffix += 1;
  }
  usedIds.add(candidate);
  return candidate;
}

function normalizeInlineTextComponentPayload(input: unknown): EnvelopeRecord | null {
  const normalizedText = normalizeStringValue(input);
  if (normalizedText) {
    return { text: normalizedText };
  }

  const record = normalizeEnvelopePayload(input);
  if (!record) return null;

  const nestedComponent = normalizeEnvelopePayload(record.component);
  const nestedTextPayload =
    normalizeEnvelopePayload(nestedComponent?.Text) ?? normalizeEnvelopePayload(record.Text);
  let payload: EnvelopeRecord | null = nestedTextPayload ? { ...nestedTextPayload } : null;

  if (
    !payload &&
    ('text' in record ||
      'style' in record ||
      'usageHint' in record ||
      'literalString' in record ||
      'literal' in record ||
      'path' in record)
  ) {
    payload = {};
    const normalizedText = normalizeStringValue('text' in record ? record.text : record);
    if (normalizedText) {
      payload.text = normalizedText;
    }
    const style = normalizeEnvelopePayload(record.style);
    if (style) {
      payload.style = style;
    }
    if (typeof record.usageHint === 'string' && record.usageHint.trim().length > 0) {
      payload.usageHint = record.usageHint;
    }
  }

  if (!payload) return null;

  const textValue = normalizeStringValue(payload.text);
  if (textValue) {
    payload.text = textValue;
  }
  return payload;
}

function buildSyntheticTextComponentEntry(
  ownerId: string,
  suffix: string,
  source: unknown,
  usedIds: Set<string>
): EnvelopeRecord | null {
  const payload = normalizeInlineTextComponentPayload(source);
  if (!payload) return null;

  const id = reserveSyntheticComponentId(`${ownerId}__${suffix}`, usedIds);
  return {
    id,
    component: {
      Text: payload,
    },
  };
}

function normalizeTabsItems(
  input: unknown
): Array<{ title: { literalString?: string; path?: string }; child: string }> | undefined {
  if (!Array.isArray(input)) return undefined;
  const normalizedItems = input.flatMap((item) => {
    const record = normalizeEnvelopePayload(item);
    if (!record) return [];
    const title = normalizeStringValue(record.title);
    const child = normalizeComponentRef(record.child);
    if (!title || !child) return [];
    return [{ title, child }];
  });
  return normalizedItems.length > 0 ? normalizedItems : undefined;
}

function normalizeTableCellValue(
  input: unknown
):
  | { literalString?: string; literalNumber?: number; literalBoolean?: boolean; path?: string }
  | undefined {
  if (typeof input === 'string' && input.trim().length > 0) {
    return { literalString: input };
  }
  if (typeof input === 'number' && Number.isFinite(input)) {
    return { literalNumber: input };
  }
  if (typeof input === 'boolean') {
    return { literalBoolean: input };
  }

  const normalizedString = normalizeStringValue(input);
  if (normalizedString) {
    return normalizedString;
  }

  const normalizedNumber = normalizeNumberValue(input);
  if (normalizedNumber) {
    return normalizedNumber;
  }

  const record = normalizeEnvelopePayload(input);
  if (!record) return undefined;
  if (typeof record.literalBoolean === 'boolean') {
    return { literalBoolean: record.literalBoolean };
  }
  if (typeof record.literal === 'boolean') {
    return { literalBoolean: record.literal };
  }
  return undefined;
}

function normalizeTableColumns(
  input: unknown
):
  | Array<{ header: { literalString?: string; path?: string }; align?: string; width?: string }>
  | undefined {
  if (!Array.isArray(input)) return undefined;
  const normalizedColumns = input.flatMap((column) => {
    if (typeof column === 'string' && column.trim().length > 0) {
      return [{ header: { literalString: column } }];
    }
    const record = normalizeEnvelopePayload(column);
    if (!record) return [];
    const header = normalizeStringValue(record.header);
    if (!header) return [];
    const normalizedColumn: {
      header: { literalString?: string; path?: string };
      align?: string;
      width?: string;
    } = { header };
    if (typeof record.align === 'string' && ['left', 'center', 'right'].includes(record.align)) {
      normalizedColumn.align = record.align;
    }
    if (typeof record.width === 'string' && record.width.trim().length > 0) {
      normalizedColumn.width = record.width;
    }
    return [normalizedColumn];
  });
  return normalizedColumns.length > 0 ? normalizedColumns : undefined;
}

function normalizeTableRows(
  input: unknown
): Array<{ key?: string; cells: Array<Record<string, unknown>> }> | undefined {
  if (!Array.isArray(input)) return undefined;
  const normalizedRows = input.flatMap((row, rowIndex) => {
    const record = normalizeEnvelopePayload(row);
    const rawCells = Array.isArray(row)
      ? row
      : Array.isArray(record?.cells)
        ? record.cells
        : undefined;
    if (!Array.isArray(rawCells)) return [];
    const cells = rawCells.flatMap((cell) => {
      const normalizedCell = normalizeTableCellValue(cell);
      return normalizedCell ? [normalizedCell] : [];
    });
    const normalizedRow: { key?: string; cells: Array<Record<string, unknown>> } = {
      cells,
    };
    if (typeof record?.key === 'string' && record.key.trim().length > 0) {
      normalizedRow.key = record.key;
    } else {
      normalizedRow.key = `row-${String(rowIndex)}`;
    }
    return [normalizedRow];
  });
  return normalizedRows.length > 0 || input.length === 0 ? normalizedRows : undefined;
}

function resolveBadgeStyle(tone: unknown, style: EnvelopeRecord | null): EnvelopeRecord {
  const toneKey = typeof tone === 'string' && BADGE_TONE_STYLES[tone] ? tone : ('neutral' as const);
  return {
    ...BADGE_TONE_STYLES.neutral,
    ...(toneKey === 'neutral' ? {} : BADGE_TONE_STYLES[toneKey]),
    ...(style ?? {}),
  };
}

function normalizeComponentEntry(rawEntry: unknown): EnvelopeRecord | null {
  const entry = normalizeEnvelopePayload(rawEntry);
  if (!entry) return null;
  if (typeof entry.id !== 'string' || !entry.id) return null;
  const component = normalizeEnvelopePayload(entry.component);
  if (!component) return null;
  const componentKeys = Object.keys(component).filter((key) => A2UI_COMPONENT_KEYS.has(key));
  if (componentKeys.length === 0) return null;
  let componentName: string | undefined = componentKeys[0];
  if (!componentName) return null;
  const payload: EnvelopeRecord = normalizeEnvelopePayload(component[componentName]) ?? {};
  const siblingStyle = normalizeEnvelopePayload(component.style);

  if (!componentName) return null;

  const normalizedPayload: EnvelopeRecord = { ...payload };
  const sourceComponentName = componentName;
  componentName = canonicalizeComponentName(componentName);
  if (siblingStyle && !normalizeEnvelopePayload(normalizedPayload.style)) {
    normalizedPayload.style = siblingStyle;
  }

  // Unwrap string literal wrappers — CSS properties must be plain strings
  const styleObj = normalizeEnvelopePayload(normalizedPayload.style);
  if (styleObj) {
    const unwrappedStyle: EnvelopeRecord = {};
    for (const [key, value] of Object.entries(styleObj)) {
      unwrappedStyle[key] = unwrapLiteralStringValue(value);
    }
    normalizedPayload.style = unwrappedStyle;
  }

  if (sourceComponentName === 'Badge') {
    const normalizedText = normalizeStringValue(
      normalizedPayload.text ??
        normalizedPayload.label ??
        normalizedPayload.literal ??
        normalizedPayload.literalString
    );
    if (normalizedText) {
      normalizedPayload.text = normalizedText;
    }
    normalizedPayload.style = resolveBadgeStyle(
      normalizedPayload.tone,
      normalizeEnvelopePayload(normalizedPayload.style)
    );
    delete normalizedPayload.label;
    delete normalizedPayload.literal;
    delete normalizedPayload.literalString;
    delete normalizedPayload.tone;
  } else if (componentName === 'Text') {
    const normalizedText = normalizeStringValue(
      normalizedPayload.text ?? normalizedPayload.literal ?? normalizedPayload.literalString
    );
    if (normalizedText) {
      normalizedPayload.text = normalizedText;
      delete normalizedPayload.literal;
      delete normalizedPayload.literalString;
    }
  }

  if (componentName === 'Button') {
    const actionRaw = normalizedPayload.action;
    if (typeof actionRaw === 'string') {
      normalizedPayload.action = { name: actionRaw };
    } else {
      const actionObj = normalizeEnvelopePayload(actionRaw);
      if (
        actionObj &&
        typeof actionObj.actionId === 'string' &&
        typeof actionObj.name !== 'string'
      ) {
        normalizedPayload.action = { ...actionObj, name: actionObj.actionId };
      }
    }
    // Normalize action.context: @copilotkit/a2ui-renderer expects
    // Array<{key: string, value: {literalString?: string, ...}}> but LLM
    // generates a plain object {} or omits it entirely.
    const actionForCtx = normalizeEnvelopePayload(normalizedPayload.action);
    if (actionForCtx) {
      const normalizedContext = normalizeActionContext(actionForCtx.context);
      if (normalizedContext) {
        actionForCtx.context = normalizedContext;
      } else {
        delete actionForCtx.context;
      }
      normalizedPayload.action = actionForCtx;
    }
  }

  if (componentName === 'TextField') {
    const normalizedLabel = normalizeStringValue(normalizedPayload.label);
    if (normalizedLabel) {
      normalizedPayload.label = normalizedLabel;
    }

    const normalizedText = normalizeStringValue(normalizedPayload.text);
    if (normalizedText) {
      normalizedPayload.text = normalizedText;
    } else {
      const legacyTextPath = normalizeDataPath(
        normalizedPayload.onChange ?? normalizedPayload.action ?? normalizedPayload.path
      );
      const legacyTextValue = normalizeStringValue(normalizedPayload.value);
      if (legacyTextPath || legacyTextValue) {
        normalizedPayload.text = {
          ...(legacyTextPath ? { path: legacyTextPath } : {}),
          ...(legacyTextValue ?? {}),
        };
      }
    }
    delete normalizedPayload.value;
    delete normalizedPayload.onChange;
  }

  if (componentName === 'Image') {
    const normalizedUrl = normalizeStringValue(normalizedPayload.url ?? normalizedPayload.src);
    if (normalizedUrl) {
      normalizedPayload.url = normalizedUrl;
    }
    delete normalizedPayload.src;
  }

  if (componentName === 'CheckBox') {
    const normalizedLabel = normalizeStringValue(normalizedPayload.label ?? normalizedPayload.text);
    if (normalizedLabel) {
      normalizedPayload.label = normalizedLabel;
    }
    const normalizedValue = normalizeBooleanValue(
      normalizedPayload.value ?? normalizedPayload.checked ?? normalizedPayload.selected
    );
    if (normalizedValue) {
      normalizedPayload.value = normalizedValue;
    }
    const legacyValuePath = normalizeDataPath(normalizedPayload.onChange ?? normalizedPayload.path);
    if (legacyValuePath) {
      normalizedPayload.value = {
        ...(normalizeEnvelopePayload(normalizedPayload.value) ?? {}),
        path: legacyValuePath,
      };
    }
    delete normalizedPayload.checked;
    delete normalizedPayload.selected;
    delete normalizedPayload.onChange;
    delete normalizedPayload.path;
  }

  if (componentName === 'MultipleChoice') {
    const normalizedDescription = normalizeStringValue(
      normalizedPayload.description ?? normalizedPayload.label
    );
    if (normalizedDescription) {
      normalizedPayload.description = normalizedDescription;
    }
    const normalizedOptions = normalizeChoiceOptions(normalizedPayload.options);
    if (normalizedOptions) {
      normalizedPayload.options = normalizedOptions;
    }
    const legacySelectionPath = normalizeDataPath(
      normalizeEnvelopePayload(normalizedPayload.selections)?.path ??
        normalizedPayload.selection ??
        normalizedPayload.selected ??
        normalizedPayload.value ??
        normalizedPayload.path
    );
    if (legacySelectionPath) {
      normalizedPayload.selections = { path: legacySelectionPath };
    }
    delete normalizedPayload.label;
    delete normalizedPayload.selection;
    delete normalizedPayload.selected;
    delete normalizedPayload.value;
    delete normalizedPayload.path;
  }

  if (componentName === 'Radio') {
    const normalizedDescription = normalizeStringValue(
      normalizedPayload.description ?? normalizedPayload.label
    );
    if (normalizedDescription) {
      normalizedPayload.description = normalizedDescription;
    }
    const normalizedOptions = normalizeChoiceOptions(normalizedPayload.options);
    if (normalizedOptions) {
      normalizedPayload.options = normalizedOptions;
    }
    const normalizedValue = normalizeStringValue(
      normalizedPayload.value ?? normalizedPayload.selection ?? normalizedPayload.selected
    );
    const legacyValuePath = normalizeDataPath(
      normalizeEnvelopePayload(normalizedPayload.selections)?.path ?? normalizedPayload.path
    );
    if (normalizedValue || legacyValuePath) {
      normalizedPayload.value = {
        ...(normalizedValue ?? {}),
        ...(legacyValuePath ? { path: legacyValuePath } : {}),
      };
    }
    delete normalizedPayload.label;
    delete normalizedPayload.selection;
    delete normalizedPayload.selected;
    delete normalizedPayload.selections;
    delete normalizedPayload.path;
  }

  if (componentName === 'Tabs') {
    const normalizedTabItems = normalizeTabsItems(normalizedPayload.tabItems);
    if (normalizedTabItems) {
      normalizedPayload.tabItems = normalizedTabItems;
    }
  }

  if (componentName === 'Modal') {
    const entryPointChild = normalizeComponentRef(normalizedPayload.entryPointChild);
    const contentChild = normalizeComponentRef(normalizedPayload.contentChild);
    if (entryPointChild) {
      normalizedPayload.entryPointChild = entryPointChild;
    }
    if (contentChild) {
      normalizedPayload.contentChild = contentChild;
    }
  }

  if (componentName === 'Table') {
    const normalizedCaption = normalizeStringValue(normalizedPayload.caption);
    if (normalizedCaption) {
      normalizedPayload.caption = normalizedCaption;
    }
    const normalizedEmptyText = normalizeStringValue(normalizedPayload.emptyText);
    if (normalizedEmptyText) {
      normalizedPayload.emptyText = normalizedEmptyText;
    }
    const normalizedColumns = normalizeTableColumns(normalizedPayload.columns);
    if (normalizedColumns) {
      normalizedPayload.columns = normalizedColumns;
    }
    const normalizedRows = normalizeTableRows(normalizedPayload.rows);
    if (normalizedRows) {
      normalizedPayload.rows = normalizedRows;
    }
  }

  if (componentName === 'Progress') {
    const normalizedLabel = normalizeStringValue(normalizedPayload.label);
    if (normalizedLabel) {
      normalizedPayload.label = normalizedLabel;
    }
    const normalizedValue = normalizeNumberValue(normalizedPayload.value);
    if (normalizedValue) {
      normalizedPayload.value = normalizedValue;
    }
    const normalizedMax = normalizeNumberValue(normalizedPayload.max);
    if (normalizedMax) {
      normalizedPayload.max = normalizedMax;
    }
  }

  if (
    componentName === 'Card' ||
    componentName === 'Column' ||
    componentName === 'List' ||
    componentName === 'Row'
  ) {
    const children = normalizedPayload.children;
    if (Array.isArray(children)) {
      normalizedPayload.children = {
        explicitList: children.filter((child): child is string => typeof child === 'string'),
      };
    }
  }

  return {
    id: entry.id,
    component: {
      [componentName]: normalizedPayload,
    },
  };
}

function normalizeViewerComponents(
  components: A2UIViewerProps['components']
): A2UIViewerProps['components'] {
  const componentList = Array.isArray(components) ? components : Object.values(components);
  const normalized: EnvelopeRecord[] = [];
  const usedIds = new Set<string>();
  for (const entry of componentList) {
    const record = normalizeEnvelopePayload(entry);
    if (record && typeof record.id === 'string' && record.id) {
      usedIds.add(record.id);
    }
  }
  for (const entry of componentList) {
    const normalizedEntry = normalizeComponentEntry(entry);
    if (!normalizedEntry) continue;

    const component = normalizeEnvelopePayload(normalizedEntry.component);
    const [componentName] = component ? Object.keys(component) : [];
    const payload =
      componentName && component ? normalizeEnvelopePayload(component[componentName]) : null;

    if (!componentName || !payload) {
      normalized.push(normalizedEntry);
      continue;
    }

    const expandedPayload: EnvelopeRecord = { ...payload };
    const syntheticEntries: EnvelopeRecord[] = [];

    if (componentName === 'Button') {
      if (!normalizeComponentRef(expandedPayload.child)) {
        const labelEntry = buildSyntheticTextComponentEntry(
          normalizedEntry.id as string,
          'label',
          expandedPayload.label,
          usedIds
        );
        if (labelEntry) {
          syntheticEntries.push(labelEntry);
          expandedPayload.child = labelEntry.id;
        }
      }
      delete expandedPayload.label;
    }

    if (
      componentName === 'Card' ||
      componentName === 'Column' ||
      componentName === 'List' ||
      componentName === 'Row'
    ) {
      const normalizedChildren = normalizeChildrenRef(expandedPayload.children);
      if (normalizedChildren) {
        expandedPayload.children = normalizedChildren;
      }
    }

    if (componentName === 'Card' || componentName === 'Column' || componentName === 'Row') {
      const normalizedGap = normalizeGapValue(expandedPayload.gap);
      if (normalizedGap) {
        expandedPayload.gap = normalizedGap;
      }

      if (
        componentName === 'Card' &&
        expandedPayload.title &&
        typeof expandedPayload.title !== 'string'
      ) {
        const titleEntry = buildSyntheticTextComponentEntry(
          normalizedEntry.id as string,
          'title',
          expandedPayload.title,
          usedIds
        );
        if (titleEntry) {
          const children = normalizeChildrenRef(expandedPayload.children) ?? { explicitList: [] };
          expandedPayload.children = {
            explicitList: [titleEntry.id as string, ...children.explicitList],
          };
          syntheticEntries.push(titleEntry);
          delete expandedPayload.title;
        }
      }
    }

    normalized.push(...syntheticEntries);
    normalized.push({
      ...normalizedEntry,
      component: {
        [componentName]: expandedPayload,
      },
    });
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
    const sourceComponentName = keys[0];
    if (!sourceComponentName) return true;
    const componentName = canonicalizeComponentName(sourceComponentName);
    const payload =
      normalizeEnvelopePayload(component[sourceComponentName]) ??
      normalizeEnvelopePayload(component[componentName]) ??
      {};

    if (sourceComponentName === 'Badge') {
      if (
        !normalizeStringValue(
          payload.text ?? payload.label ?? payload.literal ?? payload.literalString
        )
      ) {
        return true;
      }
    } else if (componentName === 'Text') {
      if (!normalizeStringValue(payload.text)) return true;
    } else if (componentName === 'Button') {
      const actionRaw = payload.action;
      const action = normalizeEnvelopePayload(actionRaw);
      const hasValidAction =
        typeof actionRaw === 'string' ||
        (action !== null &&
          (typeof action.name === 'string' || typeof action.actionId === 'string'));
      if (typeof payload.child !== 'string' || !hasValidAction) return true;
    } else if (
      componentName === 'Card' ||
      componentName === 'Column' ||
      componentName === 'List' ||
      componentName === 'Row'
    ) {
      if (!hasValidExplicitChildren(payload.children)) return true;
    } else if (componentName === 'Image') {
      if (!normalizeStringValue(payload.url ?? payload.src)) return true;
    } else if (componentName === 'CheckBox') {
      const hasValue =
        normalizeBooleanValue(payload.value ?? payload.checked ?? payload.selected) !== null ||
        normalizeDataPath(payload.onChange ?? payload.path) !== undefined;
      if (!normalizeStringValue(payload.label ?? payload.text) || !hasValue) return true;
    } else if (componentName === 'MultipleChoice') {
      const hasSelectionPath =
        normalizeDataPath(
          normalizeEnvelopePayload(payload.selections)?.path ??
            payload.selection ??
            payload.selected ??
            payload.value ??
            payload.path
        ) !== undefined;
      if (!normalizeChoiceOptions(payload.options) || !hasSelectionPath) return true;
    } else if (componentName === 'Radio') {
      const hasValue =
        normalizeStringValue(payload.value ?? payload.selection ?? payload.selected) !== null ||
        normalizeDataPath(normalizeEnvelopePayload(payload.selections)?.path ?? payload.path) !==
          undefined;
      if (!normalizeChoiceOptions(payload.options) || !hasValue) return true;
    } else if (componentName === 'Tabs') {
      if (!normalizeTabsItems(payload.tabItems)) return true;
    } else if (componentName === 'Modal') {
      if (
        !normalizeComponentRef(payload.entryPointChild) ||
        !normalizeComponentRef(payload.contentChild)
      ) {
        return true;
      }
    } else if (componentName === 'Table') {
      if (!normalizeTableColumns(payload.columns) || !normalizeTableRows(payload.rows)) return true;
    } else if (componentName === 'Progress') {
      if (normalizeNumberValue(payload.value) === null) return true;
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
  const literalRegex = /"(?:literal|literalString)"\s*:\s*"((?:\\.|[^"\\])*)"/g;
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

function extractJsonObjectSpans(input: string): Array<{ start: number; end: number }> {
  const spans: Array<{ start: number; end: number }> = [];
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
        spans.push({ start, end: i + 1 });
        start = -1;
      }
    }
  }

  return spans;
}

function parseJsonStrict(input: string): JsonValue | typeof PARSE_FAILED {
  try {
    return JSON.parse(input) as JsonValue;
  } catch {
    const jsonLike = normalizeA2UIJsonLikeString(input);
    if (jsonLike === input) {
      return PARSE_FAILED;
    }

    try {
      return JSON.parse(jsonLike) as JsonValue;
    } catch {
      return PARSE_FAILED;
    }
  }
}

function normalizeEnvelopeList(rawEnvelopes: unknown[]): EnvelopeRecord[] {
  return rawEnvelopes.flatMap((rawEnvelope) => normalizeA2UIEnvelopeRecords(rawEnvelope));
}

function extractEnvelopeList(raw: string): EnvelopeRecord[] {
  const normalized = stripMarkdownCodeFence(raw);
  if (!normalized) return [];

  const parsedWhole = parseJsonStrict(normalized);
  if (parsedWhole !== PARSE_FAILED) {
    return normalizeEnvelopeList(normalizeEnvelopes(parsedWhole));
  }

  const lines = normalized.split(/\r?\n/);
  if (lines.length > 1) {
    const lineParsed: unknown[] = [];
    let lineParseFailed = false;
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('```')) continue;
      const parsedLine = parseJsonStrict(trimmed);
      if (parsedLine === PARSE_FAILED) {
        lineParseFailed = true;
        break;
      }
      lineParsed.push(...normalizeEnvelopes(parsedLine));
    }
    if (!lineParseFailed && lineParsed.length > 0) {
      return normalizeEnvelopeList(lineParsed);
    }
  }

  const objectParsed: unknown[] = [];
  const objectSpans = extractJsonObjectSpans(normalized);
  let cursor = 0;
  for (const span of objectSpans) {
    if (normalized.slice(cursor, span.start).trim()) return [];
    const parsedChunk = parseJsonStrict(normalized.slice(span.start, span.end));
    if (parsedChunk === PARSE_FAILED) return [];
    objectParsed.push(...normalizeEnvelopes(parsedChunk));
    cursor = span.end;
  }
  if (normalized.slice(cursor).trim()) return [];
  return normalizeEnvelopeList(objectParsed);
}

function getSurfaceId(payload: EnvelopeRecord | null): string | null {
  if (!payload) return null;
  const surfaceId = payload.surfaceId;
  return typeof surfaceId === 'string' ? surfaceId : null;
}

function hasParsedComponents(parsed: ParsedSurface): boolean {
  if (Array.isArray(parsed.components)) {
    return parsed.components.length > 0;
  }
  return Object.keys(parsed.components as Record<string, unknown>).length > 0;
}

function hasRenderableRoot(parsed: ParsedSurface): boolean {
  if (!parsed.root) return false;
  if (!Array.isArray(parsed.components)) return true;
  return parsed.components.some((entry) => normalizeEnvelopePayload(entry)?.id === parsed.root);
}

function buildEmptyParsedSurface(): ParsedSurface {
  return {
    root: '',
    components: [],
    data: Object.create(null) as Record<string, unknown>,
    styles: {},
  };
}

function ensureRenderableRoot(parsed: ParsedSurface): ParsedSurface {
  return parsed;
}

function getEnvelopeSurfaceId(rawEnvelope: unknown): string | null {
  const envelope = normalizeEnvelopePayload(rawEnvelope);
  if (!envelope) return null;
  const begin = normalizeEnvelopePayload(envelope.beginRendering);
  const update = normalizeEnvelopePayload(envelope.surfaceUpdate);
  const dataUpdate = normalizeEnvelopePayload(envelope.dataModelUpdate);
  const deleteUpdate = normalizeEnvelopePayload(envelope.deleteSurface);
  return (
    getSurfaceId(begin) ??
    getSurfaceId(update) ??
    getSurfaceId(dataUpdate) ??
    getSurfaceId(deleteUpdate)
  );
}

function getEnvelopeComponentSource(
  update: EnvelopeRecord | null
): A2UIViewerProps['components'] | null {
  const updateComponents = update?.components;
  if (
    Array.isArray(updateComponents) ||
    (updateComponents && typeof updateComponents === 'object')
  ) {
    return updateComponents as A2UIViewerProps['components'];
  }
  return null;
}

function consumeEnvelope(result: ParsedSurface, rawEnvelope: unknown): void {
  const envelope = normalizeEnvelopePayload(rawEnvelope);
  if (!envelope) return;
  const begin = normalizeEnvelopePayload(envelope.beginRendering);
  const update = normalizeEnvelopePayload(envelope.surfaceUpdate);
  const dataUpdate = normalizeEnvelopePayload(envelope.dataModelUpdate);
  const deleteUpdate = normalizeEnvelopePayload(envelope.deleteSurface);

  if (begin) {
    if (typeof begin.root === 'string') {
      result.root = begin.root;
    }
    if (begin.styles && typeof begin.styles === 'object' && !Array.isArray(begin.styles)) {
      result.styles = begin.styles as Record<string, string>;
    }
  }

  const componentSource = getEnvelopeComponentSource(update);
  if (componentSource) {
    result.components = normalizeViewerComponents(componentSource);
  }

  if (deleteUpdate) {
    result.root = '';
    result.components = [];
    result.data = Object.create(null) as Record<string, unknown>;
    result.styles = {};
    return;
  }

  if (dataUpdate) {
    const path = typeof dataUpdate.path === 'string' ? dataUpdate.path : '/';
    const contents = Array.isArray(dataUpdate.contents) ? dataUpdate.contents : [];
    applyA2UIDataModelUpdate(result.data, path, contents);
    return;
  }
}

function parseA2UISnapshot(
  snapshot: A2UIMessageStreamSnapshot,
  targetSurfaceId?: string
): ParsedSurfaceResult {
  const parsed = buildEmptyParsedSurface();
  const hasSnapshotComponents = Array.isArray(snapshot.components)
    ? snapshot.components.length > 0
    : Object.keys(snapshot.components).length > 0;
  const discoveredSurfaceId = snapshot.surfaceId;
  if (!discoveredSurfaceId) {
    return {
      parsed,
      resolvedSurfaceId: targetSurfaceId,
      errorMessage: 'This A2UI payload did not declare exactly one surfaceId.',
    };
  }
  if (targetSurfaceId && discoveredSurfaceId !== targetSurfaceId) {
    return {
      parsed,
      resolvedSurfaceId: targetSurfaceId,
      errorMessage: 'This A2UI payload targets a different surfaceId than the current canvas tab.',
    };
  }

  parsed.root = snapshot.root ?? '';
  if (snapshot.styles && typeof snapshot.styles === 'object' && !Array.isArray(snapshot.styles)) {
    parsed.styles = snapshot.styles as Record<string, string>;
  }
  if (hasSnapshotComponents) {
    parsed.components = normalizeViewerComponents(
      snapshot.components as unknown as A2UIViewerProps['components']
    );
  }
  if (Object.keys(snapshot.data).length > 0) {
    parsed.data = structuredClone(snapshot.data);
  }

  const hasDeleteSurface =
    !snapshot.root && !hasSnapshotComponents && snapshot.dataRecords.length === 0;
  if (hasLikelyInvalidComponentShape(parsed.components)) {
    return {
      parsed: buildEmptyParsedSurface(),
      resolvedSurfaceId: targetSurfaceId ?? discoveredSurfaceId,
      errorMessage:
        'This A2UI payload includes one or more invalid component definitions for the current renderer.',
    };
  }
  if (!targetSurfaceId || (hasRenderableRoot(parsed) && hasParsedComponents(parsed))) {
    return {
      parsed,
      resolvedSurfaceId: targetSurfaceId ?? discoveredSurfaceId,
      ...(hasRenderableRoot(parsed) || !hasParsedComponents(parsed) || hasDeleteSurface
        ? {}
        : {
            errorMessage:
              'This A2UI payload is missing a renderable root component or surfaceUpdate snapshot.',
          }),
    };
  }

  return {
    parsed,
    resolvedSurfaceId: targetSurfaceId,
    ...(hasDeleteSurface
      ? {}
      : {
          errorMessage:
            'This A2UI payload did not produce a renderable surface for the expected surfaceId.',
        }),
  };
}

function isUsableA2UISnapshot(snapshot: unknown): snapshot is A2UIMessageStreamSnapshot {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) {
    return false;
  }

  const candidate = snapshot as Record<string, unknown>;
  const components = candidate.components;
  const data = candidate.data;
  const dataRecords = candidate.dataRecords;
  const styles = candidate.styles;

  const hasValidComponents =
    Array.isArray(components) || (components !== null && typeof components === 'object');
  const hasValidData = data !== null && typeof data === 'object' && !Array.isArray(data);
  const hasValidStyles =
    styles === undefined ||
    (styles !== null && typeof styles === 'object' && !Array.isArray(styles));

  return (
    (candidate.surfaceId === undefined || typeof candidate.surfaceId === 'string') &&
    (candidate.root === undefined || typeof candidate.root === 'string') &&
    hasValidComponents &&
    hasValidData &&
    Array.isArray(dataRecords) &&
    hasValidStyles
  );
}

function parseA2UIMessages(jsonl: string, targetSurfaceId?: string): ParsedSurfaceResult {
  const parseEnvelopes = (envelopes: unknown[]): ParsedSurface => {
    const parsed = buildEmptyParsedSurface();
    for (const envelope of envelopes) {
      consumeEnvelope(parsed, envelope as A2UIEnvelope);
    }
    return ensureRenderableRoot(parsed);
  };
  if (!jsonl) {
    return {
      parsed: buildEmptyParsedSurface(),
      resolvedSurfaceId: targetSurfaceId,
    };
  }

  const envelopes = extractEnvelopeList(jsonl);
  const hasDeleteSurface = envelopes.some((envelope) => {
    const record = normalizeEnvelopePayload(envelope);
    if (!record) return false;
    return normalizeEnvelopePayload(record.deleteSurface) !== null;
  });
  if (envelopes.length === 0) {
    return {
      parsed: buildEmptyParsedSurface(),
      resolvedSurfaceId: targetSurfaceId,
      errorMessage: 'Could not parse any A2UI envelopes from this payload.',
    };
  }

  const discoveredSurfaceIds = new Set<string>();
  for (const envelope of envelopes) {
    const surfaceId = getEnvelopeSurfaceId(envelope);
    if (surfaceId) discoveredSurfaceIds.add(surfaceId);
  }
  if (discoveredSurfaceIds.size !== 1) {
    return {
      parsed: buildEmptyParsedSurface(),
      resolvedSurfaceId: targetSurfaceId,
      errorMessage:
        discoveredSurfaceIds.size === 0
          ? 'This A2UI payload did not declare exactly one surfaceId.'
          : 'This A2UI payload mixes multiple surfaceIds.',
    };
  }

  const [discoveredSurfaceId] = [...discoveredSurfaceIds];
  if (targetSurfaceId && discoveredSurfaceId !== targetSurfaceId) {
    return {
      parsed: buildEmptyParsedSurface(),
      resolvedSurfaceId: targetSurfaceId,
      errorMessage: 'This A2UI payload targets a different surfaceId than the current canvas tab.',
    };
  }

  const parsed = parseEnvelopes(envelopes);
  if (hasLikelyInvalidComponentShape(parsed.components)) {
    return {
      parsed: buildEmptyParsedSurface(),
      resolvedSurfaceId: targetSurfaceId ?? discoveredSurfaceId,
      errorMessage:
        'This A2UI payload includes one or more invalid component definitions for the current renderer.',
    };
  }
  if (!targetSurfaceId || (hasRenderableRoot(parsed) && hasParsedComponents(parsed))) {
    return {
      parsed,
      resolvedSurfaceId: targetSurfaceId ?? discoveredSurfaceId,
      ...(hasRenderableRoot(parsed) || !hasParsedComponents(parsed) || hasDeleteSurface
        ? {}
        : {
            errorMessage:
              'This A2UI payload is missing a renderable root component or surfaceUpdate snapshot.',
          }),
    };
  }

  return {
    parsed,
    resolvedSurfaceId: targetSurfaceId,
    ...(hasDeleteSurface
      ? {}
      : {
          errorMessage:
            'This A2UI payload did not produce a renderable surface for the expected surfaceId.',
        }),
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

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

function A2UIRenderError({ message }: { message?: string | undefined }) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-center justify-center gap-2 p-6 text-sm text-red-500 dark:text-red-400">
      <span className="font-medium">
        {tFallback(t, 'components.a2uiRenderer.errorTitle', 'A2UI render error')}
      </span>
      <span className="text-xs text-slate-500 dark:text-slate-400">
        {message ?? tFallback(t, 'components.a2uiRenderer.unknownError', 'Unknown error')}
      </span>
    </div>
  );
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
      return <A2UIRenderError message={this.state.error?.message} />;
    }
    return this.props.children;
  }
}

interface A2UIRenderFallbackProps {
  messages: string;
}

interface A2UIParseErrorProps {
  message: string;
  messages: string;
}

const SURFACE_SHELL_CLASS =
  'h-full overflow-auto rounded-b-lg bg-white px-4 py-6 sm:px-6 sm:py-8 dark:bg-black';
const SURFACE_CARD_CLASS =
  'mx-auto w-full max-w-5xl rounded-[6px] border border-black/10 bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)] dark:border-white/10 dark:bg-[#111111]';
const A2UI_VIEWER_CLASS = 'a2ui-surface-theme';

const A2UIRenderFallback = memo<A2UIRenderFallbackProps>(({ messages }) => {
  const { t } = useTranslation();
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
              {tFallback(
                t,
                'components.a2uiRenderer.unableToRender',
                'Unable to render A2UI content preview.'
              )}
            </p>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {tFallback(
                t,
                'components.a2uiRenderer.plainOutputUnavailable',
                'Showing plain message output is not available for this surface.'
              )}
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
          {tFallback(t, 'components.a2uiRenderer.textPreview', 'A2UI Text Preview')}
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

const A2UIParseError = memo<A2UIParseErrorProps>(({ message, messages }) => {
  const { t } = useTranslation();
  const textValues = useMemo(() => extractLiteralTextValues(messages).slice(0, 8), [messages]);
  return (
    <div className={SURFACE_SHELL_CLASS}>
      <div className={`${SURFACE_CARD_CLASS} p-4 sm:p-5`} role="alert" aria-live="polite">
        <div className="mb-2 text-sm font-semibold text-red-600 dark:text-red-300">
          {tFallback(t, 'components.a2uiRenderer.invalidPayload', 'Invalid A2UI payload')}
        </div>
        <p className="text-sm text-slate-700 dark:text-slate-200">{message}</p>
        {textValues.length > 0 ? (
          <div className="mt-4">
            <div className="mb-2 text-xs font-medium tracking-wide text-slate-500 dark:text-slate-400">
              {tFallback(t, 'components.a2uiRenderer.recoveredPreview', 'Recovered text preview')}
            </div>
            <div className="flex min-w-0 flex-col gap-2">
              {textValues.map((line, index) => (
                <div
                  key={`a2ui-parse-error-${String(index)}`}
                  className="rounded-md bg-slate-50 px-3 py-2 text-sm leading-6 text-slate-700 whitespace-pre-wrap break-words dark:bg-slate-800/60 dark:text-slate-300"
                >
                  {line}
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
});

A2UIParseError.displayName = 'A2UIParseError';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface A2UISurfaceRendererProps {
  /** Surface ID for this A2UI surface */
  surfaceId: string;
  /** JSONL string containing A2UI v0.8 message envelopes */
  messages: string;
  /** Structured stream snapshot used for incremental runtime rendering */
  snapshot?: A2UIMessageStreamSnapshot | undefined;
}

interface ActionErrorState {
  message: string;
  requestId: string | null;
  surfaceId: string;
  messages: string;
}

export const A2UISurfaceRenderer = memo<A2UISurfaceRendererProps>(
  ({ surfaceId, messages, snapshot }) => {
    const { t } = useTranslation();
    const { parsed, resolvedSurfaceId, errorMessage } = useMemo(() => {
      if (snapshot && isUsableA2UISnapshot(snapshot)) {
        const snapshotResult = parseA2UISnapshot(snapshot, surfaceId);
        if (!snapshotResult.errorMessage) {
          return snapshotResult;
        }
      }

      return parseA2UIMessages(messages, surfaceId);
    }, [messages, snapshot, surfaceId]);
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
      const tab = s.tabs.find((t) => t.a2uiSurfaceId === effectiveSurfaceId);
      return tab?.a2uiHitlRequestId;
    });
    const [actionError, setActionError] = useState<ActionErrorState | null>(null);
    const visibleActionError =
      actionError &&
      actionError.requestId === (hitlRequestId ?? null) &&
      actionError.surfaceId === effectiveSurfaceId &&
      actionError.messages === messages
        ? actionError.message
        : null;

    const handleAction = useCallback(
      (action: {
        actionName: string;
        sourceComponentId: string;
        timestamp: string;
        context: Record<string, unknown>;
      }) => {
        const setScopedError = (message: string) => {
          setActionError({
            message,
            requestId: hitlRequestId ?? null,
            surfaceId: effectiveSurfaceId,
            messages,
          });
        };
        if (!conversationId) {
          setScopedError(
            tFallback(
              t,
              'components.a2uiRenderer.actionDisconnected',
              'This canvas action is no longer connected to an active conversation.'
            )
          );
          console.warn('[A2UI] No active conversation -- cannot dispatch action');
          return;
        }
        if (!hitlRequestId) {
          setScopedError(
            tFallback(
              t,
              'components.a2uiRenderer.actionNotAwaiting',
              'This interactive surface is no longer awaiting input.'
            )
          );
          console.warn('[A2UI] Missing HITL request_id -- refusing to dispatch action');
          return;
        }
        setActionError(null);
        agentService
          .respondToA2UIAction(
            hitlRequestId,
            action.actionName ||
              ((action as Record<string, unknown>).actionId as string) ||
              'unknown',
            action.sourceComponentId,
            action.context
          )
          .catch((err: unknown) => {
            setScopedError(
              tFallback(
                t,
                'components.a2uiRenderer.actionSendFailed',
                'Failed to send the canvas action. Please try again.'
              )
            );
            console.error('[A2UI] Failed to dispatch action:', err);
          });
      },
      [conversationId, effectiveSurfaceId, hitlRequestId, messages, t]
    );

    if (errorMessage) {
      return <A2UIParseError message={errorMessage} messages={messages} />;
    }

    // Guard: need at least a root and components to render
    if (!parsed.root || !hasComponents) {
      return (
        <div className={SURFACE_SHELL_CLASS}>
          <div
            className={`${SURFACE_CARD_CLASS} overflow-hidden flex min-h-[280px] items-center justify-center px-6 py-8`}
            aria-live="polite"
          >
            <div className="text-center">
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {tFallback(
                  t,
                  'components.a2uiRenderer.waitingForData',
                  'Waiting for A2UI surface data…'
                )}
              </p>
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {tFallback(
                  t,
                  'components.a2uiRenderer.preparingPanel',
                  'The agent is still preparing this canvas panel.'
                )}
              </p>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className={SURFACE_SHELL_CLASS}>
        <div className={`${SURFACE_CARD_CLASS} overflow-hidden p-2 sm:p-4`}>
          <A2UIErrorBoundary fallback={<A2UIRenderFallback messages={messages} />}>
            <div className="min-w-0 bg-transparent p-2 sm:p-4">
              <MemStackA2UIViewer
                root={parsed.root}
                components={parsed.components}
                className={A2UI_VIEWER_CLASS}
                {...(Object.keys(parsed.data).length > 0 ? { data: parsed.data } : {})}
                onAction={handleAction}
                {...(Object.keys(parsed.styles).length > 0 ? { styles: parsed.styles } : {})}
              />
              {visibleActionError ? (
                <p className="mt-3 text-sm text-amber-700 dark:text-amber-300" role="alert">
                  {visibleActionError}
                </p>
              ) : null}
            </div>
          </A2UIErrorBoundary>
        </div>
      </div>
    );
  }
);

A2UISurfaceRenderer.displayName = 'A2UISurfaceRenderer';
