import React from 'react';
import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { App, ConfigProvider, theme } from 'antd';
import { darkTheme, lightTheme } from '../../../../../web/src/theme/antdTheme';
import { NewMemory } from '../web/project/NewMemory';
import { subscribeToTask } from '../../../../../web/src/hooks/useTaskSSE';
import { MemoryList } from '../web/project/MemoryList';
import { MemoryDetailView } from '../web/project/MemoryDetailView';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './memories.css';
import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { useHostAppearance } from './appearance';

async function mount() {
  const host = window.memstack;
  const context = await host.getContext();
  const i18n = createInstance();
  await i18n.init({
    lng: context.locale.startsWith('zh') ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const base =
    '/tenant/' +
    encodeURIComponent(context.tenantId) +
    '/project/' +
    encodeURIComponent(context.projectId!);
  const initial = context.pathname.startsWith('/tenant/')
    ? context.pathname
    : base +
      (context.pathname.includes('/memory/')
        ? '/memory/' + context.pathname.split('/').at(-1)
        : context.pathname.endsWith('/new')
          ? '/memories/new'
          : '/memories');
  const drafts = {
    async read() {
      const result = (await host.invoke('read-memory', { draft: true })) as { draft: unknown };
      return result.draft ? JSON.stringify(result.draft) : null;
    },
    async write(_key: string, raw: string) {
      await host.invoke('save-memory', { draft: JSON.parse(raw) });
    },
  };
  const router = createMemoryRouter(
    [
      {
        path: '/tenant/:tenantId/project/:projectId/memories/new',
        element: <NewMemory drafts={drafts} />,
      },
      {
        path: '/tenant/:tenantId/project/:projectId/memories',
        element: <MemoryList recordMaintenance />,
      },
      {
        path: '/tenant/:tenantId/project/:projectId/memory/:memoryId',
        element: (
          <MemoryDetailView
            subscribeToTask={subscribeToTask}
            recordMaintenance
            externalActions={false}
          />
        ),
      },
      { path: '*', element: null },
    ],
    { initialEntries: [initial + context.search] },
  );
  let last = initial + context.search;
  router.subscribe(({ location, historyAction }) => {
    const path = location.pathname + location.search;
    if (path === last) return;
    last = path;
    void host.navigate(path, { replace: historyAction === 'REPLACE' });
  });
  function Page() {
    const dark = useHostAppearance() === 'dark';
    return (
      <I18nextProvider i18n={i18n}>
        <ConfigProvider
          theme={dark ? { ...darkTheme, algorithm: theme.darkAlgorithm } : lightTheme}
        >
          <App className="h-full">
            <RouterProvider router={router} />
          </App>
        </ConfigProvider>
      </I18nextProvider>
    );
  }
  createRoot(document.getElementById('root')!).render(<Page />);
}
void mount();
