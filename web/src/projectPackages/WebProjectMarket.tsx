import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { PluginMarket } from '../../../agi-stack/packages/plugin-marketplace-ui/src/PluginMarket';

import { installationDestination } from '../../../agi-stack/packages/plugin-marketplace-ui/src/installationReturn';
import { SignedPackageFeature } from './SignedPackageFeature';

import type { MarketplaceTransport } from '../../../agi-stack/packages/plugin-marketplace-ui/src/client';

interface Props {
  tenantId: string;
  projectId: string | null;
  transport: MarketplaceTransport;
  canManage?: boolean;
  scopeParams: Record<string, string>;
  onChanged?: () => void;
  onOpen: (path: string) => void;
}

export function WebProjectMarket({
  tenantId,
  projectId,
  transport,
  canManage,
  onOpen,
  onChanged,
  scopeParams,
}: Props) {
  const { i18n } = useTranslation();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  return (
    <PluginMarket
      tenantId={tenantId}
      projectId={projectId}
      target="web"
      locale={i18n.language}
      transport={transport}
      {...(canManage === undefined ? {} : { canManage })}
      pluginId={params.get('marketPlugin') ?? params.get('optionalPlugin')}
      onSelect={(plugin) => {
        setParams(
          (previous) => {
            const next = new URLSearchParams(previous);
            for (const [key, value] of Object.entries(scopeParams)) next.set(key, value);
            next.delete('optionalPlugin');
            if (plugin) next.set('marketPlugin', plugin);
            else next.delete('marketPlugin');
            return next;
          },
          { preventScrollReset: true }
        );
      }}
      {...(onChanged ? { onChanged } : {})}
      declarativePage={(installation, canExecute) => (
        <SignedPackageFeature
          key={JSON.stringify([
            tenantId,
            projectId,
            installation.plugin_id,
            installation.actual_digest,
          ])}
          projectId={projectId}
          tenantId={tenantId}
          installation={installation}
          transport={transport}
          canExecute={canExecute}
        />
      )}
      onActivated={(installation) => {
        const destination = installationDestination(
          params.get('returnTo'),
          { tenantId, projectId },
          installation,
          'web'
        );
        if (destination) void navigate(destination, { replace: true });
      }}
      onOpen={onOpen}
    />
  );
}
