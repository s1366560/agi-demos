import type { CSSProperties } from 'react';

import type { A2UIActions, A2UINodeLike } from './a2uiInternals';

export interface StringValue {
  literalString?: string;
  literal?: string;
  path?: string;
}

export interface NumberValue {
  literalNumber?: number;
  literal?: number;
  path?: string;
}

export function normalizeStringValue(input: unknown): StringValue | null {
  if (typeof input === 'string') {
    return { literalString: input };
  }
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return null;
  }
  const record = input as Record<string, unknown>;
  const normalized: StringValue = {};
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

export function normalizeNumberValue(input: unknown): NumberValue | null {
  if (typeof input === 'number' && Number.isFinite(input)) {
    return { literalNumber: input };
  }
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return null;
  }
  const record = input as Record<string, unknown>;
  const normalized: NumberValue = {};
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

export function normalizeStyle(input: unknown): CSSProperties {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return {};
  }
  const style = input as Record<string, unknown>;
  const normalizedStyle: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(style)) {
    if (typeof value === 'string' || typeof value === 'number') {
      normalizedStyle[key] = value;
    }
  }
  return normalizedStyle as CSSProperties;
}

function toDisplayString(value: unknown): string | undefined {
  if (value == null) {
    return undefined;
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return undefined;
  }
}

export function resolveBindingPath(
  input: unknown,
  node: A2UINodeLike,
  actions: A2UIActions
): string | undefined {
  const normalizedString = normalizeStringValue(input);
  if (normalizedString?.path) {
    return actions.resolvePath(normalizedString.path, node.dataContextPath);
  }
  const normalizedNumber = normalizeNumberValue(input);
  if (normalizedNumber?.path) {
    return actions.resolvePath(normalizedNumber.path, node.dataContextPath);
  }
  return undefined;
}

export function resolveBoundStringValue(
  input: unknown,
  node: A2UINodeLike,
  surfaceId: string,
  actions: A2UIActions
): string | undefined {
  const normalized = normalizeStringValue(input);
  if (!normalized) {
    return undefined;
  }

  if (normalized.path) {
    const resolvedPath = actions.resolvePath(normalized.path, node.dataContextPath);
    const currentValue = actions.getData(node, resolvedPath, surfaceId);
    if (Array.isArray(currentValue) && currentValue.length > 0 && currentValue[0] != null) {
      return toDisplayString(currentValue[0]);
    }
    const boundValue = toDisplayString(currentValue);
    return boundValue ?? normalized.literalString;
  }

  if (typeof normalized.literalString === 'string') {
    return normalized.literalString;
  }
  return undefined;
}

export function resolveBoundNumberValue(
  input: unknown,
  node: A2UINodeLike,
  surfaceId: string,
  actions: A2UIActions
): number | undefined {
  const normalized = normalizeNumberValue(input);
  if (!normalized) {
    return undefined;
  }

  if (normalized.path) {
    const resolvedPath = actions.resolvePath(normalized.path, node.dataContextPath);
    const currentValue = actions.getData(node, resolvedPath, surfaceId);
    const scalarValue: unknown = Array.isArray(currentValue) ? currentValue[0] : currentValue;
    const parsedValue =
      typeof scalarValue === 'number'
        ? scalarValue
        : typeof scalarValue === 'string' && scalarValue.trim().length > 0
          ? Number(scalarValue)
          : undefined;
    if (typeof parsedValue === 'number' && Number.isFinite(parsedValue)) {
      return parsedValue;
    }
  }

  if (typeof normalized.literalNumber === 'number') {
    return normalized.literalNumber;
  }
  return undefined;
}
