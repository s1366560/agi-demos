import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopRuntimeConfig } from '../types';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';

export type DesktopProjectPlaybooksReadOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectKnowledgeScope;
  signal?: AbortSignal;
}>;

export function prepareDesktopProjectPlaybooksReadOperationV2(
  value: DesktopProjectPlaybooksReadOperationInputV2,
): DesktopProjectPlaybooksReadOperationInputV2 {
  if (
    !isPlainRecordV2(value) ||
    !isPlainRecordV2(value.config) ||
    !isPlainRecordV2(value.scope) ||
    value.scope.authority !== 'cloud' ||
    value.scope.tenantId !== value.config.tenantId ||
    value.scope.projectId !== value.config.projectId ||
    !isCanonicalStringV2(value.scope.tenantId) ||
    !isCanonicalStringV2(value.scope.projectId) ||
    (value.signal !== undefined && !isAbortSignalV2(value.signal))
  ) {
    throw new RuntimeV2Error(
      'desktop_project_playbooks_read_operation_input_invalid',
      'desktop project playbooks read operation input is invalid',
    );
  }
  return Object.freeze({
    config: Object.freeze({ ...value.config }),
    scope: Object.freeze({ ...value.scope }),
    ...(value.signal === undefined ? {} : { signal: value.signal }),
  });
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCanonicalStringV2(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim();
}

function isAbortSignalV2(value: unknown): value is AbortSignal {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as AbortSignal).aborted === 'boolean' &&
    typeof (value as AbortSignal).addEventListener === 'function'
  );
}
