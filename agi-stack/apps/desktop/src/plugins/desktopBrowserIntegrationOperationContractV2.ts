import { DesktopApiError } from '../api/client';
import type {
  DesktopRuntimeConfig,
  BrowserOriginGrant,
  BrowserCapabilityGrant,
  BrowserSiteCredentialMeta,
  BrowserSiteCredentialInput,
  BrowserAuditEntry,
} from '../types';
export interface BrowserIntegrationArgumentsV2 {
  listBrowserOriginGrants: [];
  revokeBrowserOriginGrant: [grantId: string];
  listBrowserCapabilityGrants: [];
  revokeBrowserCapabilityGrant: [grantId: string];
  listBrowserSiteCredentials: [];
  upsertBrowserSiteCredential: [input: BrowserSiteCredentialInput];
  deleteBrowserSiteCredential: [credentialId: string];
  listBrowserAuditEntries: [options?: { limit?: number; origin?: string }];
}
export interface BrowserIntegrationResultsV2 {
  listBrowserOriginGrants: BrowserOriginGrant[];
  revokeBrowserOriginGrant: BrowserOriginGrant;
  listBrowserCapabilityGrants: BrowserCapabilityGrant[];
  revokeBrowserCapabilityGrant: BrowserCapabilityGrant;
  listBrowserSiteCredentials: BrowserSiteCredentialMeta[];
  upsertBrowserSiteCredential: BrowserSiteCredentialMeta;
  deleteBrowserSiteCredential: BrowserSiteCredentialMeta;
  listBrowserAuditEntries: BrowserAuditEntry[];
}
export type BrowserIntegrationMethodV2 = keyof BrowserIntegrationArgumentsV2;
export const BROWSER_INTEGRATION_METHODS_V2: readonly BrowserIntegrationMethodV2[] = Object.freeze([
  'listBrowserOriginGrants',
  'revokeBrowserOriginGrant',
  'listBrowserCapabilityGrants',
  'revokeBrowserCapabilityGrant',
  'listBrowserSiteCredentials',
  'upsertBrowserSiteCredential',
  'deleteBrowserSiteCredential',
  'listBrowserAuditEntries',
]);
export type BrowserIntegrationScopeV2 = Readonly<{ authority: DesktopRuntimeConfig['mode'] }>;
export type BrowserIntegrationInputV2<
  K extends BrowserIntegrationMethodV2 = BrowserIntegrationMethodV2,
> = Readonly<{
  config: DesktopRuntimeConfig;
  scope: BrowserIntegrationScopeV2;
  args: BrowserIntegrationArgumentsV2[K];
  signal?: AbortSignal;
}>;
export interface DesktopBrowserIntegrationAuthorityV2 {
  execute(method: BrowserIntegrationMethodV2, input: BrowserIntegrationInputV2): Promise<unknown>;
}
export function browserIntegrationErrorV2(code: string, status = 422): DesktopApiError {
  return new DesktopApiError(code, status, Object.freeze({ code, reason_code: code }));
}
export function browserIntegrationRecordV2(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
export function browserIntegrationIdentifierV2(value: unknown): string {
  if (typeof value !== 'string' || !value || value !== value.trim())
    throw browserIntegrationErrorV2('browser_integration_identifier_invalid');
  return value;
}
export function freezeBrowserIntegrationJsonV2<T>(value: T, depth = 0): T {
  if (depth > 32) throw browserIntegrationErrorV2('browser_integration_json_invalid');
  if (
    value === null ||
    typeof value === 'string' ||
    typeof value === 'boolean' ||
    (typeof value === 'number' && Number.isFinite(value))
  )
    return value;
  if (Array.isArray(value))
    return Object.freeze(value.map((v) => freezeBrowserIntegrationJsonV2(v, depth + 1))) as T;
  if (
    !browserIntegrationRecordV2(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))
  )
    throw browserIntegrationErrorV2('browser_integration_json_invalid');
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    if (['__proto__', 'constructor', 'prototype'].includes(key))
      throw browserIntegrationErrorV2('browser_integration_json_invalid');
    if (item !== undefined) result[key] = freezeBrowserIntegrationJsonV2(item, depth + 1);
  }
  return Object.freeze(result) as T;
}
export function freezeBrowserIntegrationConfigV2(
  config: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
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
    !browserIntegrationRecordV2(config) ||
    Object.keys(config).length !== keys.length ||
    keys.some((k) => typeof config[k as keyof DesktopRuntimeConfig] !== 'string') ||
    !['cloud', 'local'].includes(config.mode)
  )
    throw browserIntegrationErrorV2('browser_integration_config_invalid');
  return Object.freeze({ ...config });
}
export function prepareBrowserIntegrationInputV2<K extends BrowserIntegrationMethodV2>(
  method: K,
  input: BrowserIntegrationInputV2<K>,
): BrowserIntegrationInputV2<K> {
  if (
    !BROWSER_INTEGRATION_METHODS_V2.includes(method) ||
    !browserIntegrationRecordV2(input) ||
    !browserIntegrationRecordV2(input.scope) ||
    Object.keys(input.scope).length !== 1
  )
    throw browserIntegrationErrorV2('browser_integration_operation_invalid');
  const config = freezeBrowserIntegrationConfigV2(input.config);
  if (input.scope.authority !== config.mode)
    throw browserIntegrationErrorV2('browser_integration_scope_mismatch', 409);
  if (input.signal !== undefined && !(input.signal instanceof AbortSignal))
    throw browserIntegrationErrorV2('browser_integration_signal_invalid');
  if (input.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const args = freezeBrowserIntegrationJsonV2(input.args);
  const noArgs = [
    'listBrowserOriginGrants',
    'listBrowserCapabilityGrants',
    'listBrowserSiteCredentials',
  ].includes(method);
  if (
    !Array.isArray(args) ||
    (method === 'listBrowserAuditEntries' ? args.length > 1 : args.length !== (noArgs ? 0 : 1))
  )
    throw browserIntegrationErrorV2('browser_integration_arguments_invalid');
  if (method === 'upsertBrowserSiteCredential') {
    const body: unknown = args[0];
    if (
      !browserIntegrationRecordV2(body) ||
      Object.keys(body).some((k) => !['origin', 'username', 'password'].includes(k))
    )
      throw browserIntegrationErrorV2('browser_integration_credential_invalid');
    for (const key of ['origin', 'username', 'password'])
      if (typeof body[key] !== 'string' || !body[key])
        throw browserIntegrationErrorV2('browser_integration_credential_invalid');
    const encoder = new TextEncoder();
    if (
      !(body.origin as string).trim() ||
      !(body.username as string).trim() ||
      encoder.encode((body.username as string).trim()).length > 254 ||
      encoder.encode(body.password as string).length > 4096
    )
      throw browserIntegrationErrorV2('browser_integration_credential_invalid');
  } else if (method === 'listBrowserAuditEntries') {
    const options: unknown = args[0] ?? {};
    if (
      !browserIntegrationRecordV2(options) ||
      Object.keys(options).some((k) => !['limit', 'origin'].includes(k)) ||
      (options.limit !== undefined &&
        (typeof options.limit !== 'number' || !Number.isFinite(options.limit))) ||
      (options.origin !== undefined && typeof options.origin !== 'string')
    )
      throw browserIntegrationErrorV2('browser_integration_audit_options_invalid');
  } else if (!noArgs) browserIntegrationIdentifierV2(args[0]);
  return Object.freeze({
    config,
    scope: Object.freeze({ authority: config.mode }),
    args,
    ...(input.signal === undefined ? {} : { signal: input.signal }),
  });
}
