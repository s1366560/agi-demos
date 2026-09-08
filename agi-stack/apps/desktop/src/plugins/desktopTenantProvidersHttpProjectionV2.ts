import { DesktopApiError, desktopApiCredential, desktopLaunchCapability } from '../api/client';
import { desktopApiAuthenticationAvailable, desktopApiFetch } from '../api/cloudRequestBroker';
import type {
  DesktopRuntimeConfig,
  LlmProviderCreateInput,
  LlmProviderMutationInput,
  LlmProviderProbeInput,
  LlmProviderRoutingPolicyMutationInput,
} from '../types';
import {
  freezeProviderConfigV2,
  prepareProviderInputV2,
  providerErrorV2,
  type DesktopTenantProvidersAuthorityV2,
  type ProviderMethodV2,
  type ProviderInputV2,
} from './desktopTenantProvidersOperationContractV2';

export function createDesktopTenantProvidersHttpProjectionV2(
  config: DesktopRuntimeConfig,
): DesktopTenantProvidersAuthorityV2 {
  const runtime = freezeProviderConfigV2(config);
  return Object.freeze({
    async execute(method: ProviderMethodV2, input: ProviderInputV2) {
      if (
        input.config.mode !== runtime.mode ||
        input.config.tenantId !== runtime.tenantId ||
        input.config.apiBaseUrl !== runtime.apiBaseUrl ||
        input.config.apiKey !== runtime.apiKey ||
        input.config.localApiToken !== runtime.localApiToken
      )
        throw providerErrorV2('tenant_provider_projection_config_mismatch', 409);
      const p = prepareProviderInputV2(method, { ...input, config: runtime });
      const args = p.args;
      let path = '/api/v1/llm-providers/';
      let verb: 'GET' | 'POST' | 'PUT' | 'DELETE' = 'GET';
      let body: unknown;
      let idempotencyKey: string | undefined;
      const item = (id: unknown) => `/api/v1/llm-providers/${encodeURIComponent(id as string)}`;
      switch (method) {
        case 'listLlmProviders':
          path += '?include_inactive=true';
          break;
        case 'listLlmProviderTypes':
          path += 'types';
          break;
        case 'listLlmProviderModels':
          path += `models/${encodeURIComponent(args[0] as string)}`;
          break;
        case 'getLlmProviderUsage':
          path = item(args[0]) + '/usage';
          break;
        case 'discoverLlmProviderModels':
          path = item(args[0]) + '/models/discover';
          verb = 'POST';
          body = { expected_revision: args[1] };
          break;
        case 'getLlmProviderRoutingPolicy':
          path += `routing-policy?${new URLSearchParams({ project_id: args[0] as string, workspace_id: args[1] as string })}`;
          break;
        case 'updateLlmProviderRoutingPolicy': {
          const i = args[0] as LlmProviderRoutingPolicyMutationInput;
          path += 'routing-policy';
          verb = 'PUT';
          body = {
            project_id: i.projectId,
            workspace_id: i.workspaceId,
            roles: i.roles,
            fallbacks: i.fallbacks,
            expected_revision: i.expectedRevision,
          };
          break;
        }
        case 'createLlmProvider':
          verb = 'POST';
          body = providerBody(args[0] as LlmProviderCreateInput);
          idempotencyKey = args[1] as string;
          break;
        case 'updateLlmProvider':
          path = item(args[0]);
          verb = 'PUT';
          body = {
            ...providerBody(args[1] as LlmProviderMutationInput),
            expected_revision: (args[1] as LlmProviderMutationInput).expectedRevision,
          };
          break;
        case 'testLlmProviderDraft':
          path += 'test-connection';
          verb = 'POST';
          body = providerBody(args[0] as LlmProviderProbeInput, false);
          break;
        case 'checkLlmProvider':
          path = item(args[0]) + '/health-check';
          verb = 'POST';
          body = runtime.mode === 'local' ? { expected_revision: args[1] } : {};
          break;
        case 'deleteLlmProvider':
          path = item(args[0]);
          verb = 'DELETE';
          idempotencyKey = args[2] as string;
          body = { expected_revision: args[1], idempotency_key: idempotencyKey };
          break;
      }
      return requestProviderJsonV2(runtime, path, {
        method: verb,
        body,
        idempotencyKey,
        signal: p.signal,
      });
    },
  });
}
function providerBody(
  input: LlmProviderCreateInput | LlmProviderMutationInput | LlmProviderProbeInput,
  includeModels = true,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: input.name,
    provider_type: input.providerType,
    base_url: input.baseUrl,
    is_active: input.active,
    auth_method: input.authMethod,
  };
  if (includeModels && 'primaryModel' in input) {
    body.llm_model = input.primaryModel;
    body.allowed_models = input.allowedModels;
    if (input.embeddingModel !== undefined) body.embedding_model = input.embeddingModel;
  }
  // Keys remain transient request data. Local sidecar stores them in ApplicationCredentialVault;
  // Cloud uses the existing vault-bound broker when no renderer session token is present.
  if (input.authMethod === 'api_key' && input.apiKey?.trim()) body.api_key = input.apiKey.trim();
  if (input.authMethod === 'environment' && input.environmentVariable?.trim())
    body.environment_variable = input.environmentVariable.trim();
  return body;
}
async function requestProviderJsonV2(
  config: DesktopRuntimeConfig,
  path: string,
  options: Readonly<{
    method: 'GET' | 'POST' | 'PUT' | 'DELETE';
    body?: unknown;
    idempotencyKey?: string;
    signal?: AbortSignal;
  }>,
): Promise<unknown> {
  if (!desktopApiAuthenticationAvailable(config))
    throw providerErrorV2('desktop_trusted_session_required', 401);
  const headers = new Headers({ Accept: 'application/json' });
  const credential = desktopApiCredential(config);
  if (credential) headers.set('Authorization', `Bearer ${credential}`);
  const launch = desktopLaunchCapability(config);
  if (config.mode === 'local' && !launch)
    throw providerErrorV2('desktop_sidecar_launch_capability_required', 401);
  if (launch) headers.set('X-Agistack-Launch', launch);
  if (options.idempotencyKey !== undefined) headers.set('Idempotency-Key', options.idempotencyKey);
  if (options.body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await desktopApiFetch(config, path, {
    method: options.method,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') ?? '';
  const payload: unknown = contentType.includes('application/json')
    ? await response.json().catch(() => null)
    : await response.text().catch(() => '');
  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? String(payload.detail)
        : `HTTP ${response.status}`;
    throw new DesktopApiError(message, response.status, payload);
  }
  if (!contentType.includes('application/json'))
    throw providerErrorV2('tenant_provider_response_not_json', 502);
  return payload;
}
