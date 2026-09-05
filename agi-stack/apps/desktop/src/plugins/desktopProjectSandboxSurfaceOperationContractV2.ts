import { DesktopApiError } from '../api/client';
import type { DesktopRuntimeConfig } from '../types';
import type {
  SandboxFileListing,
  SandboxFileContent,
  SandboxFileDownload,
  SandboxRuntimeResult,
  SandboxFileListRequest,
  SandboxFileReadRequest,
  SandboxFileDownloadRequest,
} from '../features/sandbox/sandboxRuntimeClient';
import {
  parseSandboxRuntimeCapabilitySnapshot,
  type SandboxRuntimeCapabilitySnapshot,
  type RemoteDesktopSession,
  type RemoteDesktopResolution,
} from '../features/sandbox/sandboxRuntimeSurfaceClient';
import {
  requireSandboxPath,
  requireBoundedInteger,
} from './desktopProjectSandboxSurfaceFileContractV2';
export interface SandboxSurfaceArgumentsV2 {
  loadCapabilities: [];
  openRemoteDesktop: [
    capabilities: SandboxRuntimeCapabilitySnapshot,
    request: { resolution: RemoteDesktopResolution },
  ];
  listFiles: [capabilities: SandboxRuntimeCapabilitySnapshot, request: SandboxFileListRequest];
  readFile: [capabilities: SandboxRuntimeCapabilitySnapshot, request: SandboxFileReadRequest];
  downloadFile: [
    capabilities: SandboxRuntimeCapabilitySnapshot,
    request: SandboxFileDownloadRequest,
  ];
}
export type DesktopSandboxSurfaceRemoteSessionV2 = RemoteDesktopSession & {
  release(): Promise<void>;
};
export interface SandboxSurfaceResultsV2 {
  loadCapabilities: SandboxRuntimeCapabilitySnapshot;
  openRemoteDesktop: SandboxRuntimeResult<DesktopSandboxSurfaceRemoteSessionV2>;
  listFiles: SandboxRuntimeResult<SandboxFileListing>;
  readFile: SandboxRuntimeResult<SandboxFileContent>;
  downloadFile: SandboxRuntimeResult<SandboxFileDownload>;
}
export type SandboxSurfaceMethodV2 = keyof SandboxSurfaceArgumentsV2;
export const SANDBOX_SURFACE_METHODS_V2: readonly SandboxSurfaceMethodV2[] = Object.freeze([
  'loadCapabilities',
  'openRemoteDesktop',
  'listFiles',
  'readFile',
  'downloadFile',
]);
export type SandboxSurfaceInputV2<K extends SandboxSurfaceMethodV2 = SandboxSurfaceMethodV2> =
  Readonly<{
    config: DesktopRuntimeConfig;
    scope: Readonly<{
      authority: DesktopRuntimeConfig['mode'];
      tenantId: string;
      projectId: string;
    }>;
    args: SandboxSurfaceArgumentsV2[K];
    signal?: AbortSignal;
  }>;
export interface DesktopProjectSandboxSurfaceAuthorityV2 {
  execute(method: SandboxSurfaceMethodV2, input: SandboxSurfaceInputV2): Promise<unknown>;
}
export function sandboxSurfaceErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function sandboxSurfaceRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function sandboxSurfaceIdentifierV2(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim())
    throw sandboxSurfaceErrorV2('project_sandbox_surface_identifier_invalid');
  return value;
}
export function freezeSandboxSurfaceJsonV2<T>(value: T, depth = 0): T {
  if (depth > 32) throw sandboxSurfaceErrorV2('project_sandbox_surface_json_invalid');
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  )
    return value;
  if (Array.isArray(value))
    return Object.freeze(value.map((v) => freezeSandboxSurfaceJsonV2(v, depth + 1))) as T;
  if (
    !sandboxSurfaceRecordV2(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw sandboxSurfaceErrorV2('project_sandbox_surface_json_invalid');
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (['__proto__', 'constructor', 'prototype'].includes(key))
      throw sandboxSurfaceErrorV2('project_sandbox_surface_json_invalid');
    if (item !== undefined) result[key] = freezeSandboxSurfaceJsonV2(item, depth + 1);
  }
  return Object.freeze(result) as T;
}
export function freezeSandboxSurfaceConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
  const keys = [
    'apiBaseUrl',
    'deviceAuthorizationBaseUrl',
    'apiKey',
    'localApiToken',
    'tenantId',
    'projectId',
    'workspaceId',
    'mode',
    'workspaceRoot',
  ];
  if (
    !sandboxSurfaceRecordV2(config) ||
    Object.keys(config).length !== keys.length ||
    keys.some((k) => typeof config[k as keyof DesktopRuntimeConfig] !== 'string') ||
    !['cloud', 'local'].includes(config.mode)
  )
    throw sandboxSurfaceErrorV2('project_sandbox_surface_config_invalid');
  return Object.freeze({ ...config });
}
export function prepareSandboxSurfaceInputV2<K extends SandboxSurfaceMethodV2>(
  method: K,
  input: SandboxSurfaceInputV2<K>,
): SandboxSurfaceInputV2<K> {
  if (
    !SANDBOX_SURFACE_METHODS_V2.includes(method) ||
    !sandboxSurfaceRecordV2(input) ||
    !sandboxSurfaceRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 3
  )
    throw sandboxSurfaceErrorV2('project_sandbox_surface_input_invalid');
  const config = freezeSandboxSurfaceConfigV2(input.config);
  const tenantId = sandboxSurfaceIdentifierV2(input.scope.tenantId);
  const projectId = sandboxSurfaceIdentifierV2(input.scope.projectId);
  if (
    config.mode !== input.scope.authority ||
    config.tenantId !== tenantId ||
    config.projectId !== projectId
  )
    throw sandboxSurfaceErrorV2('project_sandbox_surface_scope_mismatch', 409);
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw sandboxSurfaceErrorV2('project_sandbox_surface_signal_invalid');
  if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const args = freezeSandboxSurfaceJsonV2(input.args);
  if (!Array.isArray(args) || args.length !== (method === 'loadCapabilities' ? 0 : 2))
    throw sandboxSurfaceErrorV2('project_sandbox_surface_args_invalid');
  if (method !== 'loadCapabilities') {
    if (!parseSandboxRuntimeCapabilitySnapshot(args[0]))
      throw sandboxSurfaceErrorV2('project_sandbox_surface_capabilities_invalid');
    const request: unknown = args[1];
    if (!sandboxSurfaceRecordV2(request))
      throw sandboxSurfaceErrorV2('project_sandbox_surface_request_invalid');
    if (method === 'openRemoteDesktop') {
      if (
        Object.keys(request).length !== 1 ||
        !['1280x720', '1600x900', '1920x1080', '2560x1440'].includes(String(request.resolution))
      )
        throw sandboxSurfaceErrorV2('project_sandbox_surface_resolution_invalid');
    } else {
      if (typeof request.path !== 'string' || request.path.length > 4096)
        throw sandboxSurfaceErrorV2('project_sandbox_surface_path_invalid');
      requireSandboxPath(request.path);
      if (
        (request.limit !== undefined && typeof request.limit !== 'number') ||
        (request.max_bytes !== undefined && typeof request.max_bytes !== 'number')
      )
        throw sandboxSurfaceErrorV2('project_sandbox_surface_request_invalid');
      const keys = method === 'listFiles' ? ['path', 'limit', 'cursor'] : ['path', 'max_bytes'];
      if (Object.keys(request).some((key) => !keys.includes(key)))
        throw sandboxSurfaceErrorV2('project_sandbox_surface_request_invalid');
      if (method === 'listFiles') {
        requireBoundedInteger(Number(request.limit ?? 200), 1, 500, 'limit');
        if (
          request.cursor !== undefined &&
          (typeof request.cursor !== 'string' || request.cursor.length > 256)
        )
          throw sandboxSurfaceErrorV2('project_sandbox_surface_cursor_invalid');
      } else
        requireBoundedInteger(
          Number(request.max_bytes ?? (method === 'readFile' ? 1048576 : 16 * 1048576)),
          1,
          method === 'readFile' ? 1048576 : 16 * 1048576,
          'max_bytes',
        );
    }
  }
  return Object.freeze({
    config,
    scope: Object.freeze({ authority: config.mode, tenantId, projectId }),
    args,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
