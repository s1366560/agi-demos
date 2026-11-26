import { createInstance } from 'i18next';
import { createRoot } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import { App, ConfigProvider, theme } from 'antd';
import enUS from 'antd/es/locale/en_US';
import zhCN from 'antd/es/locale/zh_CN';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { useHostAppearance } from '../../../../../sdk/memstack-plugin-sdk/ui/hostAppearance';
import { DeployProgress } from '../web/tenant/DeployProgress';
import { TemplateDetail } from '../web/tenant/TemplateDetail';
import { InstanceTemplateList } from '../web/tenant/InstanceTemplateList';
import { CreateInstance } from '../web/tenant/CreateInstance';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './tenant-deploy.css';

async function mount() {
  const host = window.memstack;
  const context = await host.getContext();
  const chinese = context.locale.startsWith('zh');
  const i18n = createInstance();
  await i18n.init({
    lng: chinese ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const base = '/tenant/' + encodeURIComponent(context.tenantId);
  const initial = context.pathname + context.search + context.hash;
  const fallback = context.pathname.includes('/instance-templates/')
    ? base + '/instance-templates'
    : context.pathname.includes('/deploy/')
      ? base + '/deploy'
      : base + '/instances';
  const router = createMemoryRouter(
    [
      {
        path: '/tenant/:tenantId',
        children: [
          { path: 'deploy', element: <DeployProgress /> },
          { path: 'deploy/:deployId', element: <DeployProgress /> },
          { path: 'instances/:instanceId/deploy', element: <DeployProgress /> },
          { path: 'instance-templates', element: <InstanceTemplateList /> },
          { path: 'instance-templates/:templateId', element: <TemplateDetail /> },
          { path: 'instances', children: [{ path: 'create', element: <CreateInstance /> }] },
          { path: '*', element: null },
        ],
      },
    ],
    { initialEntries: [fallback, initial], initialIndex: 1 },
  );
  let last = initial;
  router.subscribe(({ location, historyAction }) => {
    const next = location.pathname + location.search + location.hash;
    if (next !== last) {
      last = next;
      void host.navigate(next, { replace: historyAction === 'REPLACE' });
    }
  });
  function Page() {
    const dark = useHostAppearance() === 'dark';
    return (
      <ConfigProvider
        locale={chinese ? zhCN : enUS}
        theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm }}
      >
        <App>
          <RouterProvider router={router} />
        </App>
      </ConfigProvider>
    );
  }
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <Page />
    </I18nextProvider>,
  );
}
void mount();
