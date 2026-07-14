import type { ManagedLlmProvider, RuntimeMode } from '../../types';
import { useI18n } from '../../i18n';
import { providerConnectionStatus } from './providerManagementModel';

type ProviderStatusBadgeProps = {
  provider: ManagedLlmProvider;
  mode: RuntimeMode;
};

function providerStatusKey(provider: ManagedLlmProvider, mode: RuntimeMode): string {
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
  if (
    status === 'unhealthy' ||
    status === 'failed' ||
    status === 'error' ||
    status === 'offline'
  ) {
    return 'providers.status.unhealthy';
  }
  if (status === 'configuration_valid') return 'providers.status.configured';
  if (status === 'healthy' || status === 'connected' || status === 'ready') {
    return mode === 'local' ? 'providers.status.configured' : 'providers.status.connected';
  }
  if (status) return 'providers.status.attention';
  return 'providers.status.notChecked';
}

export function ProviderStatusBadge({ provider, mode }: ProviderStatusBadgeProps) {
  const { t } = useI18n();
  const connectionStatus = providerConnectionStatus(provider);
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
      {t(providerStatusKey(provider, mode))}
    </span>
  );
}
