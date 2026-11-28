import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';

import { MemoryGraph } from '../web/project/MemoryGraph';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import type {} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import './graph-web.css';

async function mount() {
  const host = window.memstack;
  const scope = await host.getContext();
  if (!scope.projectId) throw new Error('project_required');
  const i18n = createInstance();
  await i18n.init({
    lng: scope.locale.startsWith('zh') ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const base = '/tenant/' + encodeURIComponent(scope.tenantId) + '/project/' + encodeURIComponent(scope.projectId);
  const initial = base + '/graph' + scope.search + scope.hash;
  const router = createMemoryRouter([
    { path: '/tenant/:tenantId/project/:projectId/graph', element: <MemoryGraph /> },
    { path: '*', element: null },
  ], { initialEntries: [initial] });
  router.subscribe(({ location, historyAction }) => {
    const path = location.pathname + location.search + location.hash;
    if (path !== initial) void host.navigate(path, { replace: historyAction === 'REPLACE' });
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}><RouterProvider router={router} /></I18nextProvider>
  );
}

void mount();
