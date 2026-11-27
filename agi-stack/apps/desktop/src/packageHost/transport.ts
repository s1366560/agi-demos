import type { MarketplaceTransport } from '../../../../packages/plugin-marketplace-ui/src/client';
import { desktopVaultBoundCloudRequestBroker } from '../api/cloudRequestBroker';

export const transport: MarketplaceTransport = async <T>(
  path: string,
  options: Parameters<MarketplaceTransport>[1],
) => {
  const broker = desktopVaultBoundCloudRequestBroker();
  if (!broker) throw new Error('native_cloud_broker_unavailable');
  return (await broker.requestJson({
    path,
    method: options.method ?? 'GET',
    body: options.body as Record<string, unknown> | undefined,
    signal: options.signal,
  })) as T;
};

export async function streamCommand(
  path: string,
  body: Record<string, unknown>,
  signal: AbortSignal,
  onPackageProgress: (event: unknown) => void,
) {
  const broker = desktopVaultBoundCloudRequestBroker();
  if (!broker) throw new Error('native_cloud_broker_unavailable');
  return broker.requestJson({
    path,
    method: 'POST',
    body,
    signal,
    onPackageProgress,
  });
}
