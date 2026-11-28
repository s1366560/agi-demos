import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { App, ConfigProvider, theme } from 'antd';
import { I18nextProvider } from 'react-i18next';
import { WorkspaceGroupChatPanel } from '../web/components/chat/WorkspaceGroupChatPanel';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import { darkTheme, lightTheme } from '../../../../../web/src/theme/antdTheme';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { useHostAppearance } from './useHostAppearance';
import { selectWorkspace, useWorkspaceStore } from './groupChatStore';
import i18n from './boardLocale';
import './blackboard.css';

function GroupChat({ context }: { context: RichPageContext }) {
  const dark = useHostAppearance() === 'dark';
  const [id, setId] = useState(new URLSearchParams(context.search).get('workspaceId') || '');
  const options = useWorkspaceStore(state => state.workspaces);
  const choose = (workspace: string) => {
    selectWorkspace(workspace);
    setId(workspace);
  };
  useEffect(() => {
    if (!id && options.length) choose(options[0]!.id);
  }, [id, options]);
  useEffect(() => {
    if (!id) return;
    selectWorkspace(id);
    const refresh = () => {
      if (!document.hidden)
        void useWorkspaceStore
          .getState()
          .loadChatMessages(context.tenantId, context.projectId!, id)
          .catch(() => {});
    };
    const timer = setInterval(refresh, 4000);
    return () => clearInterval(timer);
  }, [context, id]);
  return (
    <ConfigProvider theme={dark ? { ...darkTheme, algorithm: theme.darkAlgorithm } : lightTheme}>
      <App style={{ height: '100dvh' }}>
        <WorkspaceGroupChatPanel
          tenantId={context.tenantId}
          projectId={context.projectId!}
          workspaceId={id || null}
          onWorkspaceChange={choose}
        />
      </App>
    </ConfigProvider>
  );
}
async function mount() {
  const context = await window.memstack.getContext();
  selectWorkspace(new URLSearchParams(context.search).get('workspaceId') || '');
  await i18n.init({
    lng: context.locale.startsWith('zh') ? 'zh' : 'en',
    resources: { zh: { translation: zh }, en: { translation: en } },
    interpolation: { escapeValue: false },
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={i18n}>
      <GroupChat context={context} />
    </I18nextProvider>
  );
}
void mount();
