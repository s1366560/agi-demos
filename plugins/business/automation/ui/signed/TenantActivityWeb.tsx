import { App, ConfigProvider, theme } from 'antd';
import enUS from 'antd/locale/en_US';
import zhCN from 'antd/locale/zh_CN';
import { createInstance } from 'i18next';
import { createRoot } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { darkTheme, lightTheme } from '../../../../../web/src/theme/antdTheme';
import { Events } from '../web/tenant/Events';
import { Webhooks } from '../web/tenant/Webhooks';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import { useHostAppearance } from '../../../../../sdk/memstack-plugin-sdk/ui/hostAppearance';
import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import './tenant-activity.css';

async function mount() {
  const scope = await window.memstack.getContext();
  const chinese = scope.locale.startsWith('zh');
  const i18n = createInstance();
  await i18n.init({
    lng: chinese ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const initial = scope.pathname + scope.search + scope.hash;
  const router = createMemoryRouter(
    [
      { path: '/tenant/:tenantId/events', element: <Events /> },
      { path: '/tenant/:tenantId/webhooks', element: <Webhooks /> },
    ],
    { initialEntries: [initial] }
  );
  let current = initial;
  router.subscribe(({ location, historyAction }) => {
    const next = location.pathname + location.search + location.hash;
    if (next !== current) {
      current = next;
      void window.memstack.navigate(next, { replace: historyAction === 'REPLACE' });
    }
  });
  function Page() {
    const dark = useHostAppearance() === 'dark';
    return (
      <I18nextProvider i18n={i18n}>
        <ConfigProvider
          locale={chinese ? zhCN : enUS}
          theme={dark ? { ...darkTheme, algorithm: theme.darkAlgorithm } : lightTheme}
        >
          <App>
            <RouterProvider router={router} />
          </App>
        </ConfigProvider>
      </I18nextProvider>
    );
  }
  createRoot(document.getElementById('root')!).render(<Page />);
}
void mount();
