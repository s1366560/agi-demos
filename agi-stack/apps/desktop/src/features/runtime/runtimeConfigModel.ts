import type { DesktopRuntimeConfig, RuntimeMode } from '../../types';

export type RuntimeConnectionField = 'apiBaseUrl' | 'apiKey' | 'mode';

function runtimeOrigin(apiBaseUrl: string): string | null {
  try {
    const url = new URL(apiBaseUrl);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    const origin = url.origin.toLowerCase();
    return origin === 'null' ? null : origin;
  } catch {
    return null;
  }
}

export function runtimeTransportIdentityChanged(
  previous: Pick<DesktopRuntimeConfig, 'apiBaseUrl' | 'mode'>,
  next: Pick<DesktopRuntimeConfig, 'apiBaseUrl' | 'mode'>,
): boolean {
  if (previous.mode !== next.mode) return true;
  const previousUrl = previous.apiBaseUrl.trim();
  const nextUrl = next.apiBaseUrl.trim();
  if (previousUrl === nextUrl) return false;
  const previousOrigin = runtimeOrigin(previous.apiBaseUrl);
  const nextOrigin = runtimeOrigin(next.apiBaseUrl);
  if (!previousOrigin || !nextOrigin) return true;
  return previousOrigin !== nextOrigin;
}

export function updateRuntimeConnectionConfig<K extends RuntimeConnectionField>(
  config: DesktopRuntimeConfig,
  key: K,
  value: DesktopRuntimeConfig[K],
): DesktopRuntimeConfig {
  const next = { ...config, [key]: value };
  return runtimeTransportIdentityChanged(config, next)
    ? { ...next, apiKey: '', localApiToken: '' }
    : next;
}

export function applyRuntimeServerPreset(
  config: DesktopRuntimeConfig,
  preset: { apiBaseUrl: string; mode: RuntimeMode },
): DesktopRuntimeConfig {
  const next = {
    ...config,
    apiBaseUrl: preset.apiBaseUrl,
    mode: preset.mode,
  };
  return runtimeTransportIdentityChanged(config, next)
    ? { ...next, apiKey: '', localApiToken: '' }
    : next;
}
