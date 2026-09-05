import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import {
  freezeBrowserIntegrationConfigV2,
  prepareBrowserIntegrationInputV2,
  browserIntegrationErrorV2,
  browserIntegrationRecordV2,
  type DesktopBrowserIntegrationAuthorityV2,
  type BrowserIntegrationMethodV2,
  type BrowserIntegrationInputV2,
} from './desktopBrowserIntegrationOperationContractV2';

export function createDesktopBrowserIntegrationHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopBrowserIntegrationAuthorityV2 {
  const runtime = freezeBrowserIntegrationConfigV2(config);
  return Object.freeze({
    async execute(method: BrowserIntegrationMethodV2, input: BrowserIntegrationInputV2) {
      if (
        Object.keys(runtime).some(
          (key) =>
            runtime[key as keyof DesktopRuntimeConfig] !==
            input.config[key as keyof DesktopRuntimeConfig],
        )
      )
        throw browserIntegrationErrorV2('browser_integration_projection_config_mismatch', 409);
      const p = prepareBrowserIntegrationInputV2(method, { ...input, config: runtime });
      if (runtime.mode === 'cloud')
        throw browserIntegrationErrorV2('cloud_browser_integration_unavailable', 501);
      const args = p.args;
      const base = '/api/v1/browser-bridge';
      let path: string;
      let verb: 'GET' | 'DELETE' | 'PUT' = 'GET';
      let body: unknown;
      switch (method) {
        case 'listBrowserOriginGrants':
          path = base + '/origin-grants';
          break;
        case 'revokeBrowserOriginGrant':
          path = base + '/origin-grants/' + encodeURIComponent(args[0] as string);
          verb = 'DELETE';
          break;
        case 'listBrowserCapabilityGrants':
          path = base + '/capability-grants';
          break;
        case 'revokeBrowserCapabilityGrant':
          path = base + '/capability-grants/' + encodeURIComponent(args[0] as string);
          verb = 'DELETE';
          break;
        case 'listBrowserSiteCredentials':
          path = base + '/site-credentials';
          break;
        case 'deleteBrowserSiteCredential':
          path = base + '/site-credentials/' + encodeURIComponent(args[0] as string);
          verb = 'DELETE';
          break;
        case 'upsertBrowserSiteCredential': {
          const value: unknown = args[0];
          if (!browserIntegrationRecordV2(value))
            throw browserIntegrationErrorV2('browser_integration_credential_invalid');
          path = base + '/site-credentials';
          verb = 'PUT';
          body = {
            origin: (value.origin as string).trim(),
            username: (value.username as string).trim(),
            password: value.password,
          };
          break;
        }
        case 'listBrowserAuditEntries': {
          const options: unknown = args[0] ?? {};
          if (!browserIntegrationRecordV2(options))
            throw browserIntegrationErrorV2('browser_integration_audit_options_invalid');
          const params = new URLSearchParams();
          if (typeof options.limit === 'number')
            params.set('limit', String(Math.max(1, Math.min(500, Math.trunc(options.limit)))));
          if (typeof options.origin === 'string' && options.origin.trim())
            params.set('origin', options.origin.trim());
          path = base + '/audit' + (params.size ? '?' + params.toString() : '');
          break;
        }
      }
      return requestBrowserIntegrationJsonV2(runtime, path, {
        method: verb,
        body,
        signal: p.signal,
      });
    },
  });
}
async function requestBrowserIntegrationJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: Readonly<{
    method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
    body?: unknown;
    signal?: AbortSignal;
  }>,
): Promise<unknown> {
  if (options.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  if (!desktopApiAuthenticationAvailable(config))
    throw browserIntegrationErrorV2('desktop_trusted_session_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (config.mode === 'local' && !launch)
    throw browserIntegrationErrorV2('desktop_sidecar_launch_capability_required', 401);
  if (launch) headers.set('X-Agistack-Launch', launch);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  // Keep native Cloud broker authorization and Local application-vault provisioning unchanged.
  const response = await desktopApiFetch(config, path, {
    method: options.method ?? 'GET',
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const raw: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    const payload = safeBrowserIntegrationErrorPayloadV2(raw);
    const detail = payload?.detail;
    const message = browserIntegrationRecordV2(detail) ? detail.message : detail;
    throw new DesktopApiError(
      typeof message === 'string' ? message : `HTTP ${response.status}`,
      response.status,
      payload,
    );
  }
  if (!contentType.includes('application/json'))
    throw browserIntegrationErrorV2('browser_integration_response_not_json', 502);
  return raw;
}
function safeBrowserIntegrationErrorPayloadV2(
  raw: unknown,
): Readonly<Record<string, unknown>> | null {
  if (!browserIntegrationRecordV2(raw)) return null;
  const result: Record<string, unknown> = {};
  // These are the literal public Rust route errors. Never forward arbitrary store/vault text.
  const publicDetails = new Set([
    'browser origin grant not found',
    'browser capability grant not found',
    'browser site credential not found',
    'origin must be a bare host (no scheme, port, path, or credentials)',
    'username must contain 1 to 254 characters',
    'password must contain 1 to 4096 characters',
    'site credential vault is unavailable',
  ]);
  if (typeof raw.detail === 'string' && publicDetails.has(raw.detail)) result.detail = raw.detail;
  if (
    raw.reason_code === 'browser_site_credential_origin_invalid' ||
    raw.reason_code === 'browser_site_credential_vault_unavailable'
  )
    result.reason_code = raw.reason_code;
  return Object.freeze(result);
}
