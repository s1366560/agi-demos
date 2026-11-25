import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { TenantAgentDashboardContent } from '../web/tenant/TenantAgentDashboardContent';
import en from '../../../../../web/src/locales/en-US.json';
import zh from '../../../../../web/src/locales/zh-CN.json';
import './webDashboard.css';

void window.memstack.getContext().then(async (scope) => {
  const lng = scope.locale.startsWith('zh') ? 'zh' : 'en';
  const i18n = createInstance();
  await i18n.init({
    lng,
    resources: { [lng]: { translation: lng === 'zh' ? zh : en } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <TenantAgentDashboardContent
        tenantId={scope.tenantId}
        showRelatedSurfaces={false}
        editableHooks={false}
      />
    </I18nextProvider>
  );
});
