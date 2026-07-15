import type { DesktopRuntimeConfig } from '../../types';

export type RuntimeConnectionField = 'apiBaseUrl' | 'apiKey' | 'mode';

export function updateRuntimeConnectionConfig<K extends RuntimeConnectionField>(
  config: DesktopRuntimeConfig,
  key: K,
  value: DesktopRuntimeConfig[K],
): DesktopRuntimeConfig {
  return { ...config, [key]: value };
}
