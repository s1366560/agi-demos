import {
  DEFAULT_CONFIG,
  LOCAL_DEV_SERVER_PRESETS,
  type DesktopRuntimeConfig,
  type RuntimeMode,
} from '../../types';

export const LOGIN_MODE_PREFERENCE_KEY = 'agistack.desktop.login-mode';

type LoginModePreference = {
  version: 1;
  mode: RuntimeMode;
};

type LoginModeStorage = Pick<Storage, 'getItem' | 'setItem'>;

function browserStorage(): LoginModeStorage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isLoginModePreference(value: unknown): value is LoginModePreference {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    Object.keys(record).length === 2 &&
    record.version === 1 &&
    (record.mode === 'local' || record.mode === 'cloud')
  );
}

export function readLoginModePreference(storage = browserStorage()): RuntimeMode {
  if (!storage) return 'local';
  try {
    const rawValue = storage.getItem(LOGIN_MODE_PREFERENCE_KEY);
    if (!rawValue) return 'local';
    const preference: unknown = JSON.parse(rawValue);
    return isLoginModePreference(preference) ? preference.mode : 'local';
  } catch {
    return 'local';
  }
}

export function writeLoginModePreference(
  mode: RuntimeMode,
  storage = browserStorage(),
): void {
  if (!storage) return;
  try {
    storage.setItem(LOGIN_MODE_PREFERENCE_KEY, JSON.stringify({ version: 1, mode }));
  } catch {
    // The preference is non-essential. An inaccessible store safely falls back to local next time.
  }
}

export function runtimeConfigForLoginMode(
  current: DesktopRuntimeConfig,
  mode: RuntimeMode,
): DesktopRuntimeConfig {
  const preset = mode === 'local' ? LOCAL_DEV_SERVER_PRESETS[0] : LOCAL_DEV_SERVER_PRESETS[1];
  return {
    ...current,
    apiBaseUrl: preset.apiBaseUrl,
    apiKey: '',
    localApiToken: '',
    tenantId: mode === 'local' ? 'local' : 'default',
    projectId: mode === 'local' ? 'local-project' : '',
    workspaceId: '',
    mode,
  };
}

export function initialDesktopRuntimeConfig(
  storage = browserStorage(),
): DesktopRuntimeConfig {
  return runtimeConfigForLoginMode(DEFAULT_CONFIG, readLoginModePreference(storage));
}
