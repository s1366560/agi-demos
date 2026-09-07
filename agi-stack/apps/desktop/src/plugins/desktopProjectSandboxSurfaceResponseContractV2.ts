import { parseSandboxRuntimeCapabilitySnapshot } from '../features/sandbox/sandboxRuntimeSurfaceClient';
import { parseKasmProxySession } from '../features/sandbox/sandboxRuntimeClient';
import { parseFileListing, parseFileContent } from './desktopProjectSandboxSurfaceFileContractV2';
import {
  sandboxSurfaceErrorV2,
  sandboxSurfaceRecordV2,
  freezeSandboxSurfaceJsonV2,
  type SandboxSurfaceMethodV2,
  type SandboxSurfaceInputV2,
  type SandboxSurfaceResultsV2,
} from './desktopProjectSandboxSurfaceOperationContractV2';
function invalid(): never {
  throw sandboxSurfaceErrorV2('project_sandbox_surface_response_invalid', 502);
}
export function requireSandboxSurfaceResultV2<K extends SandboxSurfaceMethodV2>(
  method: K,
  raw: unknown,
  input: SandboxSurfaceInputV2<K>,
): SandboxSurfaceResultsV2[K] {
  if (method === 'loadCapabilities') {
    const result = parseSandboxRuntimeCapabilitySnapshot(raw);
    if (!result) invalid();
    return freezeSandboxSurfaceJsonV2(result) as SandboxSurfaceResultsV2[K];
  }
  if (!sandboxSurfaceRecordV2(raw)) invalid();
  if (raw.status === 'unavailable') {
    if (typeof raw.reason_code !== 'string' || !raw.reason_code.trim()) invalid();
    return Object.freeze({
      status: 'unavailable',
      reason_code: raw.reason_code,
    }) as SandboxSurfaceResultsV2[K];
  }
  if (raw.status !== 'ready' || !sandboxSurfaceRecordV2(raw.value)) invalid();
  const value = raw.value;
  let result: unknown;
  const request = input.args[1] as unknown as Record<string, unknown>;
  if (method === 'openRemoteDesktop') {
    const descriptor = parseKasmProxySession(value.descriptor, input.scope.projectId);
    if (!descriptor) invalid();
    const base = new URL(input.config.apiBaseUrl);
    if (
      !['http:', 'https:'].includes(base.protocol) ||
      base.username ||
      base.password ||
      value.frame_url !== new URL(descriptor.proxy_url, base.origin).toString()
    )
      invalid();
    result = { descriptor, frame_url: value.frame_url };
  } else if (method === 'listFiles') {
    const listing = parseFileListing(value, String(request.path), input.config.mode);
    if (listing.entries.length > Number(request.limit ?? 200)) invalid();
    result = listing;
  } else if (method === 'readFile')
    result = parseFileContent(
      value,
      String(request.path),
      Number(request.max_bytes ?? 1048576),
      input.config.mode,
    );
  else {
    const max = Number(request.max_bytes ?? 16 * 1048576);
    if (
      value.contract_version !== 1 ||
      value.path !== request.path ||
      !(value.bytes instanceof Blob) ||
      value.bytes.size > max ||
      typeof value.filename !== 'string' ||
      !value.filename ||
      /[/\\\u0000-\u001f\u007f]/u.test(value.filename) ||
      typeof value.mime_type !== 'string' ||
      !/^[a-z0-9][a-z0-9!#$&^_.+-]*\/[a-z0-9][a-z0-9!#$&^_.+-]*$/iu.test(value.mime_type)
    )
      invalid();
    if (
      input.config.mode === 'cloud'
        ? value.authority !== 'sandbox' || value.isolation !== 'isolated'
        : value.authority !== 'native_workspace' || value.isolation !== 'not_applicable'
    )
      invalid();
    return Object.freeze({
      status: 'ready',
      value: Object.freeze({
        contract_version: 1,
        path: value.path,
        filename: value.filename,
        mime_type: value.mime_type,
        bytes: value.bytes,
        authority: value.authority,
        isolation: value.isolation,
      }),
    }) as SandboxSurfaceResultsV2[K];
  }
  return freezeSandboxSurfaceJsonV2({
    status: 'ready',
    value: result,
  }) as SandboxSurfaceResultsV2[K];
}
