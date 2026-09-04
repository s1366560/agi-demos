import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type {
  ProjectSupportCreateInput,
  ProjectSupportListQuery,
  ProjectSupportScope,
} from '../features/project-support/projectSupportTypes';

export type DesktopProjectSupportOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectSupportScope;
  signal?: AbortSignal;
}>;
export type DesktopProjectSupportListInputV2 = DesktopProjectSupportOperationInputV2 &
  Readonly<{ query?: ProjectSupportListQuery }>;
export type DesktopProjectSupportCreateInputV2 = DesktopProjectSupportOperationInputV2 &
  Readonly<{ input: ProjectSupportCreateInput }>;
export type DesktopProjectSupportCloseInputV2 = DesktopProjectSupportOperationInputV2 &
  Readonly<{ ticketId: string }>;
export type PreparedDesktopProjectSupportOperationV2 = DesktopProjectSupportOperationInputV2;

export function prepareDesktopProjectSupportOperationV2<
  T extends DesktopProjectSupportOperationInputV2,
>(value: T): T {
  if (
    !plainV2(value) ||
    !plainV2(value.config) ||
    !plainV2(value.scope) ||
    value.scope.authority !== value.config.mode ||
    value.scope.tenantId !== value.config.tenantId ||
    value.scope.projectId !== value.config.projectId ||
    !canonicalV2(value.scope.tenantId) ||
    !canonicalV2(value.scope.projectId) ||
    (value.signal !== undefined && !abortSignalV2(value.signal))
  )
    throw invalidV2();
  const config = Object.freeze({ ...value.config });
  const scope = Object.freeze({ ...value.scope });
  const copy: Record<string, unknown> = { ...value, config, scope };
  if ('query' in value && value.query !== undefined) copy.query = Object.freeze({ ...value.query });
  if ('input' in value) {
    if (!plainV2(value.input)) throw invalidV2();
    copy.input = Object.freeze({ ...value.input });
  }
  if ('ticketId' in value && !canonicalV2(value.ticketId)) throw invalidV2();
  return Object.freeze(copy) as T;
}

function invalidV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_support_operation_input_invalid',
    'desktop project support operation input is invalid',
  );
}
function plainV2(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value))
  );
}
function canonicalV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value;
}
function abortSignalV2(value: unknown): value is AbortSignal {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as AbortSignal).aborted === 'boolean' &&
    typeof (value as AbortSignal).addEventListener === 'function'
  );
}
