import React from 'react';
import { createRoot } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import { I18nContext } from '../../../../../agi-stack/apps/desktop/src/i18nContext';
import '../../../../../agi-stack/apps/desktop/src/styles/tokens.css';
import { WorkspaceCollaborationCanvas } from '../desktop/workspace/WorkspaceCollaborationCanvas';
import { createWorkspaceSurfaceClient } from '../desktop/workspace/workspaceSurfaceClient';
import en from '../desktop/workspace/collaboration.en.json';
import zh from '../desktop/workspace/collaboration.zh.json';
import { request } from './blackboardTransport';
import { boardLocation } from './boardLocation';
import { readDirectory } from './readDirectory';
import { useHostAppearance } from './useHostAppearance';

async function mount() {
  const ctx = await window.memstack.getContext();
  const location=boardLocation(ctx);
  const workspaceId=location.id??(await readDirectory(window.memstack))[0]?.id;
  const chinese = ctx.locale.startsWith('zh');
  const labels: Record<string, string> = chinese ? zh : en;
  const root = createRoot(document.getElementById('root')!);
  if (!workspaceId) {
    root.render(<p>{chinese ? '暂无工作区' : 'No workspaces'}</p>);
    return;
  }
  const client = createWorkspaceSurfaceClient({
    mode: 'cloud',
    tenantId: ctx.tenantId,
    projectId: ctx.projectId!,
    workspaceId,
    request,
  });
  function Page() {
    const appearance = useHostAppearance();
    return (
      <Theme appearance={appearance}>
        <I18nContext.Provider
          value={{
            locale: chinese ? 'zh-CN' : 'en',
            setLocale: () => {},
            t: (key, values = {}) =>
              (labels[key] ?? key).replace(/\{(\w+)\}/g, (token, name) =>
                String(values[name] ?? token)
              ),
          }}
        >
          <WorkspaceCollaborationCanvas
            workspaceId={workspaceId}
            client={client}
            initialSurface={location.tab ?? 'goals'}
            createIdempotencyKey={() => crypto.randomUUID()}
          />
        </I18nContext.Provider>
      </Theme>
    );
  }
  root.render(<Page />);
}
void mount();
