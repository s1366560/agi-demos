import { DesktopApiError } from '../../../api/desktopApiError';

export function projectKnowledgeError(reasonCode: string, status = 502): DesktopApiError {
  return new DesktopApiError(reasonCode, status, { reason_code: reasonCode });
}

export function requireIdentifier(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string' || !value || value !== value.trim()) {
    throw projectKnowledgeError(reasonCode, 422);
  }
  return value;
}

export function requireText(value: unknown, reasonCode: string): string {
  if (typeof value !== 'string') throw projectKnowledgeError(reasonCode);
  return value;
}

export function optionalText(value: unknown, reasonCode: string): string | null {
  if (value === undefined || value === null) return null;
  return requireText(value, reasonCode);
}

export function requireNonnegativeInteger(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw projectKnowledgeError(reasonCode);
  }
  return value;
}

export function requireFiniteNumber(value: unknown, reasonCode: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw projectKnowledgeError(reasonCode);
  }
  return value;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
