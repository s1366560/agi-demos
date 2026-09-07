import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { UnifiedRuntimesScope } from '../features/unified-runtimes/unifiedRuntimesTypes';
import type { DesktopRuntimeConfig } from '../types';

export type DesktopUnifiedRuntimesOperationInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: UnifiedRuntimesScope;
  signal?: AbortSignal;
}>;

export type PreparedDesktopUnifiedRuntimesOperationV2 =
  DesktopUnifiedRuntimesOperationInputV2;

const CONFIG_KEYS = new Set([
  'apiBaseUrl', 'deviceAuthorizationBaseUrl', 'apiKey', 'localApiToken',
  'tenantId', 'projectId', 'workspaceId', 'workspaceRoot', 'mode',
]);

export function prepareDesktopUnifiedRuntimesOperationV2(
  input: DesktopUnifiedRuntimesOperationInputV2,
): PreparedDesktopUnifiedRuntimesOperationV2 {
  if (!record(input)) throw invalid();
  const config = cloneDesktopUnifiedRuntimesConfigV2(input.config);
  const scope = input.scope;
  if (!record(scope) || Object.keys(scope).length !== 3 ||
      scope.authority !== config.mode || identifier(scope.tenantId) !== config.tenantId ||
      (config.mode === 'local' && identifier(scope.projectId) !== config.projectId) ||
      (config.mode === 'cloud' && typeof scope.projectId !== 'string')) throw invalid();
  if (input.signal !== undefined && !abortSignal(input.signal)) throw invalid();
  return Object.freeze({ config, scope: Object.freeze({ ...scope }),
    ...(input.signal === undefined ? {} : { signal: input.signal }) });
}

export function cloneDesktopUnifiedRuntimesConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (!record(config) || Object.keys(config).length !== CONFIG_KEYS.size ||
      Object.keys(config).some((key) => !CONFIG_KEYS.has(key)) ||
      Object.values(config).some((value) => typeof value !== 'string') ||
      (config.mode !== 'cloud' && config.mode !== 'local')) throw invalid();
  identifier(config.tenantId);
  if (config.mode === 'local') identifier(config.projectId);
  return Object.freeze({ ...config });
}

export function prepareDesktopUnifiedRuntimesProjectIdV2(value: string): string {
  return identifier(value);
}

function identifier(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim() || value.length > 256)
    throw invalid();
  return value;
}

function abortSignal(value: unknown): value is AbortSignal {
  return record(value) && typeof value.aborted === 'boolean' &&
    typeof value.addEventListener === 'function';
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function invalid(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_unified_runtimes_operation_input_invalid',
    'desktop unified runtimes operation input invalid',
  );
}
