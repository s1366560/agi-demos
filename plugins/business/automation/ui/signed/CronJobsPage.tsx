import ConfigProvider from 'antd/es/config-provider';
import enUS from 'antd/es/locale/en_US';
import zhCN from 'antd/es/locale/zh_CN';
import { createInstance } from 'i18next';
import { useEffect, useState } from 'react';
import { Alert } from 'antd';
import { createRoot } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { CronJobs, type ScheduleConversation } from '../web/project/CronJobs';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './cron-jobs.css';

async function mount() {
  const { locale, tenantId, projectId, pathname, search, hash, commands } = await window.memstack.getContext();
  if (!projectId) throw new Error('project_scope_required');
  const chinese = locale.startsWith('zh');
  const i18n = createInstance();
  await i18n.init({
    lng: chinese ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const virtualPath = '/' + encodeURIComponent(projectId);
  const initial = virtualPath + (search ?? '') + (hash ?? '');
  function Schedules() {
    const [choices, setChoices] = useState<ScheduleConversation[]>();
    const [error, setError] = useState('');
    useEffect(() => {
      const controller = new AbortController();
      if (commands.includes('schedule-conversations')) {
        void window.memstack.invoke('schedule-conversations', {}, { signal: controller.signal })
          .then((value) => {
            if (!controller.signal.aborted) setChoices((value as {items: ScheduleConversation[]}).items);
          })
          .catch((reason) => { if (!controller.signal.aborted) setError(String(reason)); });
      }
      return () => controller.abort();
    }, []);
    return <>
      {error && <Alert type="error" message={error} />}
      <CronJobs conversations={choices} openConversation={({id, workspaceId}) => {
        const path = '/tenant/' + encodeURIComponent(tenantId) + '/agent-workspace/' + encodeURIComponent(id);
        void window.memstack.openPage('memstack-agent', 'chat', path + '?' + new URLSearchParams({workspaceId}))
          .catch((reason) => setError(String(reason)));
      }} />
    </>;
  }
  const router = createMemoryRouter([{ path: '/:projectId', element: <Schedules /> }], {
    initialEntries: [initial],
  });
  let current = initial;
  router.subscribe(({ location }) => {
    const next = virtualPath + location.search + location.hash;
    if (next === current) return;
    current = next;
    void window.memstack.navigate(pathname + location.search + location.hash, { replace: true });
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <ConfigProvider
        locale={chinese ? zhCN : enUS}
        theme={{
          token: {
            colorTextDescription: '#595959',
            colorTextSecondary: '#595959',
            colorTextPlaceholder: '#737373',
          },
        }}
      >
        <RouterProvider router={router} />
      </ConfigProvider>
    </I18nextProvider>
  );
}
void mount();
