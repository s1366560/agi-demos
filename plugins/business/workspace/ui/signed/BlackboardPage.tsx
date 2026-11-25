import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';
import { App, ConfigProvider, theme } from 'antd';
import { boardAddress, boardLocation } from './boardLocation';
import { Blackboard } from '../web/project/Blackboard';
import { useHostAppearance } from './useHostAppearance';
import i18n from './boardLocale';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import { darkTheme, lightTheme } from '../../../../../web/src/theme/antdTheme';
import './blackboard.css';

async function mount() {
  const host = window.memstack;
  const context = await host.getContext();
  const base =
    '/tenant/' +
    encodeURIComponent(context.tenantId) +
    '/project/' +
    encodeURIComponent(context.projectId!);
  const initial = base + '/blackboard';
  const { params: search } = boardLocation(context);
  await i18n.init({
    lng: context.locale.startsWith('zh') ? 'zh' : 'en',
    resources: { zh: { translation: zh }, en: { translation: en } },
    interpolation: { escapeValue: false },
  });
  const router = createMemoryRouter(
    [{ path: '/tenant/:tenantId/project/:projectId/blackboard', element: <Blackboard /> }],
    { initialEntries: [initial + '?' + search + context.hash] }
  );
  let last =
    router.state.location.pathname + router.state.location.search + router.state.location.hash;
  router.subscribe(({ location, historyAction }) => {
    const path = location.pathname + location.search + location.hash;
    if (path !== last) {
      last = path;
      const address =
        location.pathname === initial
          ? boardAddress(context, new URLSearchParams(location.search), location.hash)
          : path;
      void host.navigate(address, { replace: historyAction === 'REPLACE' });
    }
  });
  function Page() {
    const dark = useHostAppearance() === 'dark';
    const [unavailable, setUnavailable] = useState(false);
    return (
      <I18nextProvider i18n={i18n}>
        <ConfigProvider
          theme={dark ? { ...darkTheme, algorithm: theme.darkAlgorithm } : lightTheme}
        >
          <App>
            <div
              onClickCapture={(event: React.MouseEvent) => {
                const link = event.target instanceof Element ? event.target.closest('a') : null;
                const pathname = link?.getAttribute('href')?.split('?')[0];
                const agentPath = '/tenant/' + context.tenantId + '/agent-workspace';
                if (pathname !== agentPath && !pathname?.startsWith(agentPath + '/')) return;
                event.preventDefault();
                event.stopPropagation();
                const destination = new URL(
                  link!.getAttribute('href')!,
                  'https://workspace.invalid'
                );
                destination.searchParams.delete('projectId');
                void host
                  .openPage(
                    'memstack-agent',
                    'chat',
                    destination.pathname + destination.search + destination.hash
                  )
                  .catch(() => setUnavailable(true));
              }}
            >
              {unavailable && (
                <p role="alert">
                  {i18n.t(
                    'blackboard.agentPageUnavailable',
                    'The Agent page is unavailable in this project.'
                  )}
                </p>
              )}
              <RouterProvider router={router} />
            </div>
          </App>
        </ConfigProvider>
      </I18nextProvider>
    );
  }
  createRoot(document.getElementById('root')!).render(<Page />);
}
void mount();
