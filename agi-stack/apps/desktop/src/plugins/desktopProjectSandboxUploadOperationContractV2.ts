import { DesktopApiError } from '../api/client';
import type { DesktopRuntimeConfig } from '../types';
export const MAX_SANDBOX_UPLOAD_BYTES_V2 = 16 * 1_048_576;
export type DesktopSandboxUploadFileV2 = Pick<File, 'name' | 'type' | 'size' | 'arrayBuffer'>;
export type ProjectSandboxUploadScopeV2 = Readonly<{
  authority: DesktopRuntimeConfig['mode'];
  tenantId: string;
  projectId: string;
}>;
export type ProjectSandboxUploadInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  scope: ProjectSandboxUploadScopeV2;
  file: DesktopSandboxUploadFileV2;
  signal?: AbortSignal;
}>;
export interface DesktopProjectSandboxUploadAuthorityV2 {
  uploadSandboxFile(input: ProjectSandboxUploadInputV2): Promise<unknown>;
}
export function sandboxUploadErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function sandboxUploadRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function freezeSandboxUploadConfigV2(config: DesktopRuntimeConfig): DesktopRuntimeConfig {
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
    !sandboxUploadRecordV2(config) ||
    Object.keys(config).length !== keys.length ||
    keys.some((key) => typeof config[key as keyof DesktopRuntimeConfig] !== 'string') ||
    !['cloud', 'local'].includes(config.mode)
  )
    throw sandboxUploadErrorV2('project_sandbox_upload_config_invalid');
  return Object.freeze({ ...config });
}
export function checkSandboxUploadAbortV2(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
}
export function prepareSandboxUploadInputV2(
  input: ProjectSandboxUploadInputV2,
): ProjectSandboxUploadInputV2 {
  if (
    !sandboxUploadRecordV2(input) ||
    !sandboxUploadRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 3
  )
    throw sandboxUploadErrorV2('project_sandbox_upload_input_invalid');
  const config = freezeSandboxUploadConfigV2(input.config);
  const { tenantId, projectId, authority } = input.scope;
  if (
    ![tenantId, projectId].every(
      (value) => typeof value === 'string' && value.length > 0 && value.trim() === value,
    )
  )
    throw sandboxUploadErrorV2('project_sandbox_upload_scope_invalid');
  if (config.mode !== authority || config.tenantId !== tenantId || config.projectId !== projectId)
    throw sandboxUploadErrorV2('project_sandbox_upload_scope_mismatch', 409);
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw sandboxUploadErrorV2('project_sandbox_upload_signal_invalid');
  checkSandboxUploadAbortV2(input.signal);
  const source = input.file;
  if (
    !sandboxUploadRecordV2(source) ||
    typeof source.name !== 'string' ||
    typeof source.type !== 'string' ||
    !Number.isSafeInteger(source.size) ||
    Number(source.size) < 0 ||
    typeof source.arrayBuffer !== 'function'
  )
    throw sandboxUploadErrorV2('project_sandbox_upload_file_invalid');
  if (source.size > MAX_SANDBOX_UPLOAD_BYTES_V2)
    throw sandboxUploadErrorV2('project_sandbox_upload_file_too_large', 413);
  const name = source.name.trim();
  if (!name || name === '.' || name === '..' || /[/\\\u0000-\u001f\u007f]/u.test(name))
    throw sandboxUploadErrorV2('project_sandbox_upload_filename_invalid');
  // A File is a read capability, not JSON. Capture metadata and its original receiver before admission.
  const read = source.arrayBuffer.bind(source);
  const file = Object.freeze({ name, type: source.type, size: source.size, arrayBuffer: read });
  return Object.freeze({
    config,
    scope: Object.freeze({ authority, tenantId, projectId }),
    file,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
