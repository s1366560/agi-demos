import type { ManagedLlmProvider } from '../../types';

/**
 * Local-runtime LLM readiness.
 *
 * The sidecar starts an agent turn only when a provider passes its runtime
 * admission (`selected_provider_route` + `llm_from_runtime_binding`): the
 * provider record is active, declares a routing binding (provider type, base
 * URL, model), and satisfies the credential gate (`credential_configured` is
 * already true for `auth_method: none`). When no provider passes, the turn
 * fails with `model_unconfigured`. These predicates mirror that admission so
 * the composer can fail fast with an actionable state instead of launching a
 * run that can only die.
 */

export type LocalLlmProviderLike = Pick<
  ManagedLlmProvider,
  'is_active' | 'credential_configured' | 'provider_type' | 'base_url' | 'llm_model'
>;

const MODEL_UNCONFIGURED_TOKEN = 'model_unconfigured';

export function localLlmProviderUsable(provider: LocalLlmProviderLike): boolean {
  if (provider.is_active !== true) return false;
  if (provider.credential_configured === false) return false;
  return (
    nonEmpty(provider.provider_type) &&
    nonEmpty(provider.base_url) &&
    nonEmpty(provider.llm_model)
  );
}

export function localLlmUnconfiguredFromProviders(
  providers: readonly LocalLlmProviderLike[] | null | undefined,
): boolean {
  if (!Array.isArray(providers)) return false;
  return !providers.some((provider) => localLlmProviderUsable(provider));
}

/**
 * The sidecar's stable failure token for "no usable LLM routing target".
 * Matched as a protocol constant (never natural-language text) so persisted
 * `error` timeline events can be presented with the localized, actionable
 * explanation.
 */
export function isModelUnconfiguredError(detail: string | null | undefined): boolean {
  return typeof detail === 'string' && detail.includes(MODEL_UNCONFIGURED_TOKEN);
}

function nonEmpty(value: string | null | undefined): boolean {
  return typeof value === 'string' && value.trim().length > 0;
}
