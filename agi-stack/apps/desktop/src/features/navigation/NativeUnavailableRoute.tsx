import { ExclamationTriangleIcon, LockClosedIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { DesktopRouteSurfaceProps } from './desktopRouteModule';
import './NativeUnavailableRoute.css';

export function NativeUnavailableRoute({ module }: DesktopRouteSurfaceProps) {
  const { t } = useI18n();
  return (
    <section
      className="native-unavailable-route"
      data-route-id={module.routeId}
      data-local-policy={module.localPolicy}
      data-reason-code={module.reasonCode ?? 'desktop_route_module_reason_missing'}
    >
      <div className="native-unavailable-route-card" role="status">
        <span className="native-unavailable-route-icon">
          {module.localPolicy === 'blocked_by_web_contract' ? (
            <LockClosedIcon aria-hidden="true" />
          ) : (
            <ExclamationTriangleIcon aria-hidden="true" />
          )}
        </span>
        <span className="native-unavailable-route-eyebrow">
          {t('nativeUnavailableRoute.eyebrow')}
        </span>
        <h1>{t('nativeUnavailableRoute.title')}</h1>
        <p>{t('nativeUnavailableRoute.description')}</p>
        <dl className="native-unavailable-route-contract">
          <ContractField
            label={t('nativeUnavailableRoute.routeId')}
            value={module.routeId}
          />
          <ContractField
            label={t('nativeUnavailableRoute.capability')}
            value={module.capability}
          />
          <ContractField
            label={t('nativeUnavailableRoute.localPolicy')}
            value={module.localPolicy}
          />
          <ContractField
            label={t('nativeUnavailableRoute.reasonCode')}
            value={module.reasonCode ?? 'desktop_route_module_reason_missing'}
          />
          <ContractField
            label={t('nativeUnavailableRoute.availability')}
            value={t('nativeUnavailableRoute.unavailable')}
          />
        </dl>
      </div>
    </section>
  );
}

function ContractField({
  label,
  value,
}: Readonly<{
  label: string;
  value: string;
}>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <code tabIndex={0}>{value}</code>
      </dd>
    </div>
  );
}
