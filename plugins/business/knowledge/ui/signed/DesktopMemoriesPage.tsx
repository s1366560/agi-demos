import { signedMemoryBinding } from './signedMemoryBinding';
import React, { useEffect, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';
import { I18nContext } from '../../../../../agi-stack/apps/desktop/src/i18nContext';
import '../../../../../agi-stack/apps/desktop/src/styles/tokens.css';
import {
  CloudMemoriesPage,
  CloudMemoriesUnavailable,
} from '../desktop/project-knowledge/CloudMemoriesPage';
import '../desktop/project-knowledge/CloudMemoriesPage.css';
import { createCloudMemoriesController } from '../desktop/project-knowledge/cloudMemoriesController';
import {
  cloudMemoriesEnUS,
  cloudMemoriesZhCN,
} from '../desktop/project-knowledge/locales/cloudMemoriesMessages';
import type { ProjectKnowledgeScope } from '../desktop/project-knowledge/projectKnowledgeClient';
import type { RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

async function mount(host: RichPageRuntime) {
  const context = await host.getContext();
  if (!context.projectId) throw new Error('project_required');
  const scope: ProjectKnowledgeScope = {
    authority: 'cloud',
    tenantId: context.tenantId,
    projectId: context.projectId,
  };
  const zh = context.locale.startsWith('zh');
  const labels: Record<string, string> = {
    ...(zh ? cloudMemoriesZhCN : cloudMemoriesEnUS),
    'common.refresh': zh ? '刷新' : 'Refresh',
    'common.close': zh ? '关闭' : 'Close',
  };
  const language = {
    locale: zh ? ('zh-CN' as const) : ('en' as const),
    setLocale: () => {},
    t: (key: string) => labels[key] ?? key,
  };
  const root = createRoot(document.getElementById('root')!);
  let binding;
  try {
    binding = await signedMemoryBinding(host, context, scope);
  } catch {
    root.render(
      <I18nContext.Provider value={language}><CloudMemoriesUnavailable /></I18nContext.Provider>,
    );
    return;
  }
  const controller = createCloudMemoriesController(binding);
  function Page() {
    const model = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
    useEffect(() => {
      controller.activate();
      let active = true;
      void controller.loadPage().then(() => {
        if (!active) return;
        if (context.pathname.endsWith('/memories/new')) controller.create();
        else if (context.pathname.includes('/memory/')) {
          void controller.open(decodeURIComponent(context.pathname.split('/').at(-1)!), 'view');
        }
      });
      return () => {
        active = false;
        controller.stop();
      };
    }, []);
    return (
      <CloudMemoriesPage
        model={model}
        controller={controller}
        reindex={
          context.commands.includes('reindex-memory')
            ? (id) => host.invoke('reindex-memory', { id })
            : undefined
        }
      />
    );
  }
  root.render(
    <I18nContext.Provider value={language}>
      <Page />
    </I18nContext.Provider>,
  );
}
void mount(window.memstack);
