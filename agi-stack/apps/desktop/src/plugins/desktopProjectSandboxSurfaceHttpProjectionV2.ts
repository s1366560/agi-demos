import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiFetch, desktopApiAuthenticationAvailable } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import { parseKasmProxySession } from '../features/sandbox/sandboxRuntimeClient';
import { parseSandboxRuntimeCapabilitySnapshot } from '../features/sandbox/sandboxRuntimeSurfaceClient';
import {
  freezeSandboxSurfaceConfigV2,
  prepareSandboxSurfaceInputV2,
  sandboxSurfaceErrorV2,
  sandboxSurfaceRecordV2,
  type DesktopProjectSandboxSurfaceAuthorityV2,
  type SandboxSurfaceMethodV2,
  type SandboxSurfaceInputV2,
} from './desktopProjectSandboxSurfaceOperationContractV2';
import {
  parseFileListing,
  parseFileContent,
  parseDownloadAuthority,
  parseContentLength,
  downloadFilename,
  normalizedMimeType,
} from './desktopProjectSandboxSurfaceFileContractV2';
export function createDesktopProjectSandboxSurfaceHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopProjectSandboxSurfaceAuthorityV2 {
  const runtime = freezeSandboxSurfaceConfigV2(config);
  return Object.freeze({
    async execute(method: SandboxSurfaceMethodV2, input: SandboxSurfaceInputV2) {
      if (
        Object.keys(runtime).some(
          (key) =>
            runtime[key as keyof DesktopRuntimeConfig] !==
            input.config[key as keyof DesktopRuntimeConfig],
        )
      )
        throw sandboxSurfaceErrorV2('project_sandbox_surface_projection_config_mismatch', 409);
      const p = prepareSandboxSurfaceInputV2(method, { ...input, config: runtime });
      const projectPath = `/api/v1/projects/${encodeURIComponent(p.scope.projectId)}`;
      if (method !== 'loadCapabilities') {
        const caps = parseSandboxRuntimeCapabilitySnapshot(p.args[0])!;
        const capability = method === 'openRemoteDesktop' ? caps.kasm_vnc : caps.files;
        if (capability.availability !== 'available')
          return {
            status: 'unavailable',
            reason_code: capability.reason_code ?? 'sandbox_runtime_capability_unavailable',
          };
        if (method === 'openRemoteDesktop' && runtime.mode === 'local')
          return { status: 'unavailable', reason_code: 'local_kasm_vnc_not_applicable' };
      }
      if (runtime.mode === 'cloud') {
        const project = await requestJson(
          runtime,
          projectPath + '?' + new URLSearchParams({ tenant_id: p.scope.tenantId }),
          p.signal,
          65536,
        );
        if (
          !sandboxSurfaceRecordV2(project) ||
          project.id !== p.scope.projectId ||
          project.tenant_id !== p.scope.tenantId
        )
          throw sandboxSurfaceErrorV2('project_sandbox_surface_project_mismatch', 409);
      }
      if (method === 'loadCapabilities') {
        const caps = parseSandboxRuntimeCapabilitySnapshot(
          await requestJson(runtime, projectPath + '/sandbox/capabilities', p.signal, 65536),
        );
        if (!caps) throw sandboxSurfaceErrorV2('sandbox_runtime_capability_contract_invalid', 502);
        return caps;
      }
      const request = p.args[1] as unknown as Record<string, unknown>;
      if (method === 'openRemoteDesktop') {
        const raw = await requestJson(
          runtime,
          projectPath +
            '/sandbox/desktop/session?' +
            new URLSearchParams({ resolution: String(request.resolution) }),
          p.signal,
          65536,
          'POST',
        );
        const descriptor = parseKasmProxySession(raw, p.scope.projectId);
        if (!descriptor)
          throw sandboxSurfaceErrorV2('sandbox_remote_desktop_descriptor_invalid', 502);
        const base = new URL(runtime.apiBaseUrl);
        if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password)
          throw sandboxSurfaceErrorV2('sandbox_api_origin_invalid');
        return {
          status: 'ready',
          value: { descriptor, frame_url: new URL(descriptor.proxy_url, base.origin).toString() },
        };
      }
      const path = request.path as string;
      if (method === 'listFiles') {
        const query = new URLSearchParams({ path, limit: String(request.limit ?? 200) });
        if (request.cursor) query.set('cursor', String(request.cursor));
        return {
          status: 'ready',
          value: parseFileListing(
            await requestJson(
              runtime,
              projectPath + '/sandbox/files?' + query,
              p.signal,
              2 * 1048576,
            ),
            path,
            runtime.mode,
          ),
        };
      }
      const max = Number(request.max_bytes ?? (method === 'readFile' ? 1048576 : 16 * 1048576));
      const query = new URLSearchParams({ path, max_bytes: String(max) });
      if (method === 'readFile')
        return {
          status: 'ready',
          value: parseFileContent(
            await requestJson(
              runtime,
              projectPath + '/sandbox/files/content?' + query,
              p.signal,
              2 * 1048576,
            ),
            path,
            max,
            runtime.mode,
          ),
        };
      const response = await requestResponse(
        runtime,
        projectPath + '/sandbox/files/download?' + query,
        p.signal,
        'GET',
        max,
      );
      const declared = parseContentLength(response.headers.get('content-length'));
      if (declared !== null && declared > max)
        throw sandboxSurfaceErrorV2('sandbox_file_download_too_large', 502);
      const bytes = await response.blob();
      check(p.signal);
      if (bytes.size > max) throw sandboxSurfaceErrorV2('sandbox_file_download_too_large', 502);
      return {
        status: 'ready',
        value: {
          contract_version: 1,
          ...parseDownloadAuthority(response, runtime.mode),
          path,
          filename: downloadFilename(response.headers.get('content-disposition'), path),
          mime_type:
            normalizedMimeType(response.headers.get('content-type')) ?? 'application/octet-stream',
          bytes,
        },
      };
    },
  });
}
function check(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
}
async function requestResponse(
  config: DesktopRuntimeConfig,
  path: string,
  signal?: AbortSignal,
  method: 'GET' | 'POST' = 'GET',
  maxBytes?: number,
): Promise<Response> {
  check(signal);
  if (!desktopApiAuthenticationAvailable(config))
    throw sandboxSurfaceErrorV2('desktop_trusted_session_required', 401);
  const headers = new Headers({ Accept: maxBytes ? '*/*' : 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (launch) headers.set('X-Agistack-Launch', launch);
  const response = await desktopApiFetch(
    config,
    path,
    { method, headers, signal, credentials: config.mode === 'cloud' ? 'include' : 'omit' },
    maxBytes ? { responseType: 'binary', maxBytes } : undefined,
  );
  check(signal);
  if (!response.ok)
    throw new DesktopApiError(`HTTP ${response.status}`, response.status, {
      reason_code: 'project_sandbox_surface_request_failed',
    });
  return response;
}
async function requestJson(
  config: DesktopRuntimeConfig,
  path: string,
  signal: AbortSignal | undefined,
  maxBytes: number,
  method: 'GET' | 'POST' = 'GET',
): Promise<unknown> {
  const response = await requestResponse(config, path, signal, method);
  if (!response.headers.get('content-type')?.toLowerCase().includes('application/json'))
    throw sandboxSurfaceErrorV2('sandbox_response_not_json', 502);
  const declared = parseContentLength(response.headers.get('content-length'));
  if (declared !== null && declared > maxBytes)
    throw sandboxSurfaceErrorV2('sandbox_response_too_large', 502);
  const text = await response.text();
  check(signal);
  if (new TextEncoder().encode(text).byteLength > maxBytes)
    throw sandboxSurfaceErrorV2('sandbox_response_too_large', 502);
  try {
    return JSON.parse(text);
  } catch {
    throw sandboxSurfaceErrorV2('sandbox_response_malformed', 502);
  }
}
