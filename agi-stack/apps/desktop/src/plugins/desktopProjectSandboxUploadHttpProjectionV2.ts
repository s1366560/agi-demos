import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import {
  checkSandboxUploadAbortV2,
  freezeSandboxUploadConfigV2,
  prepareSandboxUploadInputV2,
  sandboxUploadErrorV2,
  sandboxUploadRecordV2,
  type DesktopProjectSandboxUploadAuthorityV2,
  type ProjectSandboxUploadInputV2,
} from './desktopProjectSandboxUploadOperationContractV2';
export function createDesktopProjectSandboxUploadHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopProjectSandboxUploadAuthorityV2 {
  const runtime = freezeSandboxUploadConfigV2(config);
  return Object.freeze({
    async uploadSandboxFile(input: ProjectSandboxUploadInputV2) {
      if (
        Object.keys(runtime).some(
          (key) =>
            runtime[key as keyof DesktopRuntimeConfig] !==
            input.config[key as keyof DesktopRuntimeConfig],
        )
      )
        throw sandboxUploadErrorV2('project_sandbox_upload_projection_config_mismatch', 409);
      const p = prepareSandboxUploadInputV2({ ...input, config: runtime });
      if (runtime.mode === 'local')
        throw sandboxUploadErrorV2('local_sandbox_upload_unavailable', 501);
      const projectPath = `/api/v1/projects/${encodeURIComponent(p.scope.projectId)}`;
      const project = await requestSandboxUploadJsonV2(
        runtime,
        projectPath + '?' + new URLSearchParams({ tenant_id: p.scope.tenantId }),
        undefined,
        p.signal,
      );
      if (
        !sandboxUploadRecordV2(project) ||
        project.id !== p.scope.projectId ||
        project.tenant_id !== p.scope.tenantId
      )
        throw sandboxUploadErrorV2('project_sandbox_upload_project_mismatch', 409);
      checkSandboxUploadAbortV2(p.signal);
      const bytes = await readSandboxUploadBytesV2(p);
      checkSandboxUploadAbortV2(p.signal);
      if (!(bytes instanceof ArrayBuffer) || bytes.byteLength !== p.file.size)
        throw sandboxUploadErrorV2('project_sandbox_upload_size_mismatch');
      const contentBase64 = encodeSandboxUploadBytesV2(bytes);
      checkSandboxUploadAbortV2(p.signal);
      return requestSandboxUploadJsonV2(
        runtime,
        projectPath + '/sandbox/execute',
        {
          tool_name: 'import_file',
          arguments: {
            filename: p.file.name,
            content_base64: contentBase64,
            destination: '/workspace/input',
            overwrite: true,
          },
          timeout: Math.min(300, Math.max(60, Math.ceil(p.file.size / (1024 * 1024)) * 2)),
        },
        p.signal,
      );
    },
  });
}
async function readSandboxUploadBytesV2(input: ProjectSandboxUploadInputV2): Promise<ArrayBuffer> {
  checkSandboxUploadAbortV2(input.signal);
  // File.arrayBuffer has no cancellation API. Abort ends this operation; late data is never uploaded.
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException('Aborted', 'AbortError'));
    input.signal?.addEventListener('abort', abort, { once: true });
    const finish = () => input.signal?.removeEventListener('abort', abort);
    Promise.resolve()
      .then(() => {
        checkSandboxUploadAbortV2(input.signal);
        return input.file.arrayBuffer();
      })
      .then(
        (value) => {
          finish();
          if (input.signal?.aborted) abort();
          else resolve(value);
        },
        () => {
          finish();
          if (input.signal?.aborted) abort();
          else reject(sandboxUploadErrorV2('project_sandbox_upload_file_read_failed'));
        },
      );
  });
}
function encodeSandboxUploadBytesV2(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const chunks: string[] = [];
  for (let offset = 0; offset < bytes.length; offset += 0x8000)
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + 0x8000)));
  return btoa(chunks.join(''));
}
async function requestSandboxUploadJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<unknown> {
  checkSandboxUploadAbortV2(signal);
  if (!desktopApiAuthenticationAvailable(config))
    throw sandboxUploadErrorV2('desktop_trusted_session_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (launch) headers.set('X-Agistack-Launch', launch);
  if (body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await desktopApiFetch(config, path, {
    method: body === undefined ? 'GET' : 'POST',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  checkSandboxUploadAbortV2(signal);
  const json = response.headers.get('content-type')?.includes('application/json');
  const raw: unknown = json ? await response.json().catch(() => null) : null;
  checkSandboxUploadAbortV2(signal);
  if (!response.ok) {
    // Backend errors can contain tool arguments or file content. Never attach raw payloads.
    throw new DesktopApiError(
      `HTTP ${response.status}`,
      response.status,
      Object.freeze({ reason_code: 'project_sandbox_upload_request_failed' }),
    );
  }
  if (!json) throw sandboxUploadErrorV2('project_sandbox_upload_response_not_json', 502);
  return raw;
}
