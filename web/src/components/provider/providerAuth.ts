import type {
  DetectedEnvironmentProvider,
  ProviderAuthMethod,
  ProviderConfig,
  ProviderCreate,
  ProviderType,
  ProviderTypeDescriptor,
  ProviderUpdate,
} from '../../types/memory';

export interface ProviderAuthDraft {
  auth_method: ProviderAuthMethod;
  api_key: string;
  base_url: string;
  environment_variable: string;
}

type ProviderAuthPayload = Pick<
  ProviderCreate,
  'auth_method' | 'api_key' | 'environment_variable'
> &
  Pick<ProviderUpdate, 'auth_method' | 'api_key' | 'environment_variable'>;

export const indexProviderCapabilities = (
  descriptors: ProviderTypeDescriptor[]
): Partial<Record<ProviderType, ProviderTypeDescriptor>> =>
  Object.fromEntries(descriptors.map((descriptor) => [descriptor.provider_type, descriptor]));

export const getProviderAuthMethods = (
  capabilities: Partial<Record<ProviderType, ProviderTypeDescriptor>>,
  providerType: ProviderType,
  _currentMethod?: ProviderAuthMethod
): ProviderAuthMethod[] => {
  const descriptor = capabilities[providerType];
  const methods: ProviderAuthMethod[] = descriptor ? [...descriptor.auth_methods] : [];

  return methods;
};

export const getDefaultProviderAuthMethod = (
  capabilities: Partial<Record<ProviderType, ProviderTypeDescriptor>>,
  providerType: ProviderType
): ProviderAuthMethod => getProviderAuthMethods(capabilities, providerType)[0] ?? 'api_key';

export const getDetectedEnvironmentVariable = (
  detected: DetectedEnvironmentProvider | undefined,
  authMethods: ProviderAuthMethod[]
): string | null => {
  const environmentVariable = detected?.environment_variable?.trim();
  if (
    detected?.credential_source !== 'environment' ||
    !detected.credential_configured ||
    !authMethods.includes('environment') ||
    !environmentVariable
  ) {
    return null;
  }

  return environmentVariable;
};

export const canReuseConfiguredCredential = (
  provider: ProviderConfig | null | undefined,
  providerType: ProviderType,
  draft: ProviderAuthDraft
): boolean =>
  provider?.provider_type === providerType &&
  provider.auth_method === draft.auth_method &&
  provider.credential_configured &&
  (provider.base_url?.trim() || null) === (draft.base_url.trim() || null) &&
  (draft.auth_method !== 'environment' ||
    (provider.environment_variable ?? '') === draft.environment_variable.trim());

export const isProviderCredentialReady = (
  draft: ProviderAuthDraft,
  provider: ProviderConfig | null | undefined,
  providerType: ProviderType
): boolean => {
  if (draft.auth_method === 'none') return true;
  if (draft.auth_method === 'environment') {
    if (draft.environment_variable.trim().length === 0) return false;
    if (provider?.auth_method === 'environment' && provider.credential_configured) {
      return canReuseConfiguredCredential(provider, providerType, draft);
    }
    return true;
  }
  if (draft.auth_method === 'api_key') {
    return (
      draft.api_key.trim().length > 0 || canReuseConfiguredCredential(provider, providerType, draft)
    );
  }
  return false;
};

export const buildProviderAuthPayload = (draft: ProviderAuthDraft): ProviderAuthPayload => {
  if (draft.auth_method === 'environment') {
    return {
      auth_method: 'environment',
      environment_variable: draft.environment_variable.trim(),
    };
  }
  if (draft.auth_method === 'none') {
    return { auth_method: 'none' };
  }
  if (draft.auth_method === 'oauth') {
    return { auth_method: 'oauth' };
  }

  const apiKey = draft.api_key.trim();
  return {
    auth_method: 'api_key',
    ...(apiKey ? { api_key: apiKey } : {}),
  };
};
