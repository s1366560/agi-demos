import { useI18n } from '@desktop/i18n';
import type { TenantBillingController } from './tenantBillingController';
import type { TenantBillingPlan } from './tenantBillingClient';
import type { TenantBillingViewModel } from './tenantBillingPresentationModel';
import { TenantAdminDegradedNotice, TenantAdminRouteState } from '@desktop/features/tenant-admin/TenantAdminRouteState';

import { InvoiceTable } from '../../shared/InvoiceTable';

const PLANS: readonly TenantBillingPlan[] = ['free', 'pro', 'enterprise'];

export function TenantBillingPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantBillingViewModel;
  controller: TenantBillingController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  if (
    !['ready', 'degraded', 'empty', 'stale'].includes(model.state) ||
    !model.tenant ||
    !model.usage
  ) {
    return (
      <TenantAdminRouteState
        state={model.state}
        reasonCode={model.reasonCode}
        retryVisible={model.retryVisible}
        onRetry={onRetry}
      />
    );
  }
  return (
    <section data-tenant-admin-route="billing" data-state={model.state}>
      <header>
        <h1>{t('tenantAdmin.billing.title')}</h1>
        <p>{t('tenantAdmin.billing.subtitle')}</p>
      </header>
      <TenantAdminDegradedNotice reasonCode={model.reasonCode} />
      <dl>
        <dt>{t('tenantAdmin.scope')}</dt>
        <dd>
          <code>{model.scope.tenantId}</code>
        </dd>
        <dt>{t('tenantAdmin.billing.plan')}</dt>
        <dd>{model.tenant.plan}</dd>
      </dl>
      <section>
        <h2>{t('tenantAdmin.billing.usage')}</h2>
        <dl>
          <dt>{t('tenantAdmin.billing.projects')}</dt>
          <dd>{model.usage.projects}</dd>
          <dt>{t('tenantAdmin.billing.memories')}</dt>
          <dd>{model.usage.memories}</dd>
          <dt>{t('tenantAdmin.billing.users')}</dt>
          <dd>{model.usage.users}</dd>
          <dt>{t('tenantAdmin.billing.storage')}</dt>
          <dd>{model.usage.storage}</dd>
        </dl>
      </section>
      {controller && model.allowedActions.includes('upgrade-plan') ? (
        <section>
          <h2>{t('tenantAdmin.billing.upgrade')}</h2>
          {PLANS.map((plan) => (
            <button
              key={plan}
              type="button"
              disabled={Boolean(model.busyAction) || plan === model.tenant?.plan}
              onClick={() => void controller.upgradePlan(plan).catch(() => undefined)}
            >
              {plan}
            </button>
          ))}
        </section>
      ) : null}
      <section>
        <h2>{t('tenantAdmin.billing.invoices')}</h2>
        <InvoiceTable invoices={model.invoices} />
      </section>
    </section>
  );
}
