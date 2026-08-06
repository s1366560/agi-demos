import {
  ExclamationTriangleIcon,
  LockClosedIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { ManagementRoutePresentationModel } from './managementRoutePresentationModel';

export function ManagementRoutePage({
  model,
  onRetry,
}: Readonly<{
  model: ManagementRoutePresentationModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const busy = model.state === 'loading' || model.state === 'scope_switch';
  const forbidden = model.state === 'forbidden';
  const Icon = forbidden ? LockClosedIcon : ExclamationTriangleIcon;
  return (
    <section
      className="desktop-production-route-boundary"
      data-authority={model.scope.authority}
      data-state={model.state}
      aria-busy={busy || undefined}
      role={busy ? 'status' : 'alert'}
    >
      <span className="desktop-production-route-boundary-icon">
        <Icon aria-hidden="true" />
      </span>
      <span className="desktop-production-route-eyebrow">
        {t('desktopProductionRouter.eyebrow')}
      </span>
      <h1>{t(sectionLabel(model.capability))}</h1>
      <p>
        {busy ? t('settings.loading') : t('settings.unavailable')}
      </p>
      <code className="desktop-production-route-identity">
        {model.capability}
      </code>
      {model.reasonCode ? (
        <dl className="desktop-production-route-details">
          <div>
            <dt>{t('desktopProductionRouter.reasonCode')}</dt>
            <dd>
              <code>{model.reasonCode}</code>
            </dd>
          </div>
        </dl>
      ) : null}
      {model.retryVisible ? (
        <Button type="button" variant="surface" color="gray" onClick={onRetry}>
          <ReloadIcon aria-hidden="true" />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}

function sectionLabel(
  capability: ManagementRoutePresentationModel['capability'],
): string {
  switch (capability) {
    case 'tenant-tenant-providers':
      return 'settings.models';
    case 'tenant-tenant-agent-definitions':
      return 'settings.agents';
    case 'tenant-tenant-skills':
      return 'settings.skills';
    case 'tenant-tenant-plugins':
      return 'settings.plugins';
    case 'tenant-tenant-mcp-servers':
      return 'settings.mcp';
  }
}
