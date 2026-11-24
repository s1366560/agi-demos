import { ProjectInvoiceActions } from './ProjectInvoiceActions';
import { createRoot } from 'react-dom/client';
import { I18nContext } from '@desktop/i18nContext';
import { useTenantAdminController } from '@desktop/features/tenant-admin/useTenantAdminController';
import { tenantAdminEnUS, tenantAdminZhCN } from '@desktop/features/tenant-admin/locales/tenantAdminMessages';
import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { createTenantBillingController } from '../desktop/tenant-admin/tenantBillingController';
import { TenantBillingPage } from '../desktop/tenant-admin/TenantBillingPage';
import { TENANT_BILLING_FILE_REASON, type TenantBillingClient, type TenantBillingTenant } from '../desktop/tenant-admin/tenantBillingClient';
import type { BillingInfo, UpgradePlanResponse } from '../web/billingTypes';
import '@desktop/styles/tokens.css';

type Account = BillingInfo & { membership_role: 'owner' | 'admin' };

function readTenant(tenant: BillingInfo['tenant'], expected: string): TenantBillingTenant {
  if (tenant.id !== expected || !['free', 'pro', 'enterprise'].includes(tenant.plan))
    throw new Error('tenant_billing_contract_invalid');
  return { id: expected, name: tenant.name, plan: tenant.plan as TenantBillingTenant['plan'], storageLimit: tenant.storage_limit };
}

async function mount() {
  const host = window.memstack;
  const page = await host.getContext();
  const scope = { authority: 'cloud', tenantId: page.tenantId } as const;
  const client: TenantBillingClient = {
    async load(scope, options) {
      const account = await host.invoke('billing-details', undefined, options) as Account;
      const data = {
        membershipRole: account.membership_role, tenant: readTenant(account.tenant, scope.tenantId),
        usage: account.usage, invoices: account.invoices.map(row => ({
          ...row, periodStart: row.period_start, periodEnd: row.period_end, createdAt: row.created_at,
          paidAt: row.paid_at, invoiceUrl: row.invoice_url,
        })),
      };
      return { scope, authority: 'cloud', availability: 'degraded', reasonCode: TENANT_BILLING_FILE_REASON,
        contractVersion: '4.0.0', allowedActions: ['view', 'inspect-usage', 'list-invoices',
          ...(data.membershipRole === 'owner' && page.commands.includes('change-plan') ? ['upgrade-plan'] : [])],
        ...data, data };
    },
    async upgradePlan(scope, plan, options) {
      const result = await host.invoke('change-plan', {plan}, options) as UpgradePlanResponse;
      return readTenant(result.tenant, scope.tenantId);
    },
  };
  const controller = createTenantBillingController({ client, initialScope: scope });
  function Page() {
    const { model, retry } = useTenantAdminController(controller, scope);
    return <TenantBillingPage model={model} controller={controller} onRetry={retry} />;
  }
  const zh = page.locale.startsWith('zh');
  const messages = zh ? tenantAdminZhCN : tenantAdminEnUS;
  createRoot(document.getElementById('root')!).render(
    <I18nContext.Provider value={{locale: zh ? 'zh-CN' : 'en', setLocale: () => {},
      t: key => key === 'common.retry' ? (zh ? '重试' : 'Retry') : messages[key] ?? key }}>
      <Page />
      {page.projectId && <ProjectInvoiceActions commands={page.commands} locale={page.locale} />}
    </I18nContext.Provider>
  );
}
void mount();
