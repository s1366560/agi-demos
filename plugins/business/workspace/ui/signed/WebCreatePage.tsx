import React, { useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { ConfigProvider, Modal, theme } from 'antd';
import { darkTheme, lightTheme } from '../../../../../web/src/theme/antdTheme';
import { useHostAppearance } from './useHostAppearance';
import zhCN from 'antd/es/locale/zh_CN';
import enUS from 'antd/es/locale/en_US';
import { WorkspaceCreateView } from '../web/tenant/WorkspaceCreateView';
import { workspaceCreation, projectDirectory } from './createWorkspace';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './workspaceCreate.css';

function useWarnBeforeUnload(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
}

async function mount() {
  const host = window.memstack;
  const scope = await host.getContext();
  const directory = projectDirectory(scope.tenantId, scope.projectId);
  const chinese = scope.locale.startsWith('zh');
  const i18n = createInstance();
  await i18n.init({
    lng: chinese ? 'zh' : 'en',
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    interpolation: { escapeValue: false },
  });
  const createWorkspace = workspaceCreation(host);
  function Page() {
    const dark = useHostAppearance() === 'dark';
    return (
      <ConfigProvider
        locale={chinese ? zhCN : enUS}
        theme={dark ? { ...darkTheme, algorithm: theme.darkAlgorithm } : lightTheme}
      >
        <WorkspaceCreateView
          createWorkspace={createWorkspace}
          onCreated={(id) =>
            void host.navigate(directory + '/' + encodeURIComponent(id))
          }
          onBack={() => void host.navigate(directory)}
          confirmDiscard={(title) =>
            new Promise((resolve) => {
              Modal.confirm({
                title,
                centered: true,
                okButtonProps: { danger: true },
                onOk: () => resolve(true),
                onCancel: () => resolve(false),
              });
            })
          }
          isDuplicateName={(error) => error instanceof Error && error.message === 'conflict'}
          useUnsavedChangesWarning={useWarnBeforeUnload}
        />
      </ConfigProvider>
    );
  }
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <Page />
    </I18nextProvider>
  );
}
void mount();
