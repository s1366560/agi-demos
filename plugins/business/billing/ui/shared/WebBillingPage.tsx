import { ProjectInvoiceActions } from './ProjectInvoiceActions';
import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { BillingView } from '../web/BillingView';
import type { BillingInfo, UpgradePlanResponse } from '../web/billingTypes';
import english from '../web/locales/en-US.json';
import chinese from '../web/locales/zh-CN.json';
import './webBilling.css';

async function mount() {
  const host = window.memstack;
  const scope = await host.getContext();
  const zh = scope.locale.startsWith('zh');
  const i18n = createInstance();
  await i18n.init({
    lng: zh ? 'zh' : 'en',
    resources: { [zh ? 'zh' : 'en']: { translation: zh ? chinese : english } },
    interpolation: { escapeValue: false },
  });
  const service = {
    getBillingInfo: () => host.invoke('billing-details') as Promise<BillingInfo>,
    upgradePlan: (_tenant: string, plan: 'free' | 'pro' | 'enterprise') =>
      host.invoke('change-plan', { plan }) as Promise<UpgradePlanResponse>,
  };
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <BillingView tenantId={scope.tenantId} billingService={service}
        canUpgrade={scope.commands.includes('change-plan')} />
      {scope.projectId && <ProjectInvoiceActions commands={scope.commands} locale={scope.locale} />}
    </I18nextProvider>
  );
}
void mount();
