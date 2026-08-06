import { ReloadIcon } from '@radix-ui/react-icons';
import { Button } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { NativeSettingsRouteState } from './nativeSettingsRoutePresentation';

export type NativeSettingsRoutePageModel = Readonly<{
  capability: string;
  scope: Readonly<{ authority: 'cloud' | 'local' }>;
  state: NativeSettingsRouteState;
  reasonCode: string | null;
  retryVisible: boolean;
}>;

export function NativeSettingsRoutePage({
  model,
  onRetry,
}: Readonly<{
  model: NativeSettingsRoutePageModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const busy = model.state === 'loading' || model.state === 'scope_switch';
  return (
    <section
      className="desktop-production-route-boundary"
      data-authority={model.scope.authority}
      data-state={model.state}
      aria-busy={busy || undefined}
      role={busy ? 'status' : 'alert'}
    >
      <span className="desktop-production-route-eyebrow">
        {t('desktopProductionRouter.eyebrow')}
      </span>
      <h1>
        <code>{model.capability}</code>
      </h1>
      <p>{busy ? t('settings.loading') : t('settings.unavailable')}</p>
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
