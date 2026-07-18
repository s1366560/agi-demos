import type { ManagedLlmProvider } from '../../types';
import { useI18n } from '../../i18n';
import { providerConnectionStatus, providerEnabledModelIds } from './providerManagementModel';

type ProviderStatusBadgeProps = {
  provider: ManagedLlmProvider;
  probeSupported?: boolean;
};

function providerStatusKey(provider: ManagedLlmProvider, probeSupported: boolean): string {
  if (provider.is_active === false || provider.is_enabled === false) {
    return 'providers.status.disabled';
  }
  const status = provider.health_status?.trim().toLowerCase();
  if (
    status === 'needs_credentials' ||
    (provider.credential_configured === false && provider.auth_method !== 'none')
  ) {
    return 'providers.status.needsCredentials';
  }
  if (status === 'unhealthy' || status === 'failed' || status === 'error' || status === 'offline') {
    return 'providers.status.unhealthy';
  }
  if (
    (status === 'healthy' || status === 'connected' || status === 'ready') &&
    providerEnabledModelIds(provider).length === 0
  ) {
    return 'providers.status.needsModels';
  }
  if (status === 'configuration_valid') return 'providers.status.configured';
  if (
    !status &&
    !probeSupported &&
    (provider.auth_method === 'none' || provider.credential_configured === true) &&
    providerEnabledModelIds(provider).length > 0
  ) {
    return 'providers.status.configured';
  }
  if (status === 'healthy' || status === 'connected' || status === 'ready') {
    return 'providers.status.connected';
  }
  if (status) return 'providers.status.attention';
  if (provider.auth_method !== 'none' && provider.credential_configured === undefined) {
    return 'providers.status.credentialUnknown';
  }
  return 'providers.status.notChecked';
}

export function ProviderStatusBadge({ provider, probeSupported = true }: ProviderStatusBadgeProps) {
  const { t } = useI18n();
  const connectionStatus = providerConnectionStatus(provider, probeSupported);
  const healthStatus = provider.health_status?.trim().toLowerCase();
  const visualStatus =
    healthStatus === 'unhealthy' ||
    healthStatus === 'failed' ||
    healthStatus === 'error' ||
    healthStatus === 'offline'
      ? 'offline'
      : connectionStatus;
  return (
    <span className={`provider-status ${visualStatus}`}>
      <i />
      {t(providerStatusKey(provider, probeSupported))}
    </span>
  );
}
