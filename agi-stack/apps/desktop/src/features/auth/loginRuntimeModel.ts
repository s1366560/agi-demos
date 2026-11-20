import { DEFAULT_CONFIG, LOCAL_DEV_SERVER_PRESETS, type DesktopRuntimeConfig } from '../../types';

export const LEGACY_LOGIN_MODE_PREFERENCE_KEY = 'agistack.desktop.login-mode';

type LegacyLoginModeStorage = Pick<Storage, 'getItem' | 'removeItem'>;

function browserStorage(): LegacyLoginModeStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function runsInElectronShell(): boolean {
  if (typeof window === 'undefined') return false;
  return (
    window.__MEMSTACK_DESKTOP__?.runtime === 'electron' &&
    typeof window.__MEMSTACK_DESKTOP__.core?.invoke === 'function'
  );
}

function legacyPreferenceWasLocalSession(rawValue: string): boolean {
  try {
    const preference: unknown = JSON.parse(rawValue);
    if (!preference || typeof preference !== 'object' || Array.isArray(preference)) return true;
    return (preference as { mode?: unknown }).mode === 'local';
  } catch {
    return true;
  }
}

/** Removes the retired login-mode preference. Returns true when it recorded a local session. */
export function purgeLegacyLoginModePreference(
  storage: LegacyLoginModeStorage | null = browserStorage(),
): boolean {
  if (!storage) return false;
  try {
    const rawValue = storage.getItem(LEGACY_LOGIN_MODE_PREFERENCE_KEY);
    if (!rawValue) return false;
    storage.removeItem(LEGACY_LOGIN_MODE_PREFERENCE_KEY);
    return legacyPreferenceWasLocalSession(rawValue);
  } catch {
    return false;
  }
}

export function initialDesktopRuntimeConfig(): DesktopRuntimeConfig {
  const cloudPreset = LOCAL_DEV_SERVER_PRESETS.find((preset) => preset.mode === 'cloud');
  return {
    ...DEFAULT_CONFIG,
    apiBaseUrl: cloudPreset?.apiBaseUrl ?? DEFAULT_CONFIG.apiBaseUrl,
    apiKey: '',
    localApiToken: '',
    tenantId: 'default',
    projectId: '',
    workspaceId: '',
    mode: 'cloud',
  };
}

export function runtimeConfigForLoginAvailability(
  current: DesktopRuntimeConfig,
): DesktopRuntimeConfig {
  if (
    current.mode === 'cloud' &&
    current.tenantId !== 'local' &&
    current.projectId !== 'local-project'
  ) {
    return current;
  }
  const cloud = initialDesktopRuntimeConfig();
  return {
    ...cloud,
    apiBaseUrl: current.mode === 'cloud' ? current.apiBaseUrl : cloud.apiBaseUrl,
    deviceAuthorizationBaseUrl: current.deviceAuthorizationBaseUrl,
    workspaceRoot: current.workspaceRoot,
  };
}
