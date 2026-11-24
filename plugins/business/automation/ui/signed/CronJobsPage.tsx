import { createInstance } from 'i18next';
import { createRoot } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { CronJobs } from '../web/project/CronJobs';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './cron-jobs.css';

async function mount() {
  const { locale, projectId } = await window.memstack.getContext();
  if (!projectId) throw new Error('project_scope_required');
  const i18n = createInstance();
  await i18n.init({
    lng: locale.startsWith('zh') ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter initialEntries={['/' + encodeURIComponent(projectId)]}>
        <Routes>
          <Route path="/:projectId" element={<CronJobs />} />
        </Routes>
      </MemoryRouter>
    </I18nextProvider>
  );
}
void mount();
