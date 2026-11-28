import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { ProjectOverviewView } from '../web/project/ProjectOverviewView';
import { readOverview } from './overviewData';
import { useHostAppearance } from './useHostAppearance';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './workspaceOverview.css';

async function mount() {
  const host = window.memstack;
  const ctx = await host.getContext();
  const base =
    '/tenant/' +
    encodeURIComponent(ctx.tenantId) +
    '/project/' +
    encodeURIComponent(ctx.projectId!);
  const i18n = createInstance();
  await i18n.init({
    lng: ctx.locale.startsWith('zh') ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const load = () => readOverview();
  function Page() {
    const dark = useHostAppearance() === 'dark';
    const [error, setError] = useState('');
    return (
      <div
        className={dark ? 'dark' : ''}
        onClickCapture={(event) => {
          const link = event.target instanceof Element && event.target.closest('a[href]');
          if (!link) return;
          event.preventDefault();
          event.stopPropagation();
          const path = link.getAttribute('href')!;
          const target =
            path === base + '/memories'
              ? 'memories'
              : path.startsWith(base + '/memory/')
                ? 'memory-detail'
                : null;
          void (
            target ? host.openPage('memstack-knowledge', target, path) : host.navigate(path)
          ).catch((e: Error) => setError(e.message));
        }}
      >
        {error && <p role="alert">{error}</p>}
        <MemoryRouter initialEntries={[base]}>
          <Routes>
            <Route
              path="/tenant/:tenantId/project/:projectId"
              element={<ProjectOverviewView load={load} />}
            />
          </Routes>
        </MemoryRouter>
      </div>
    );
  }
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <Page />
    </I18nextProvider>
  );
}
void mount();
