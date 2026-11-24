import { useEffect, useSyncExternalStore } from 'react';
import { createRoot } from 'react-dom/client';

import { I18nContext } from '../../../../../agi-stack/apps/desktop/src/i18nContext';
import { CloudMemoryRouteContextProvider } from '../../../../../agi-stack/apps/desktop/src/features/project-knowledge/CloudMemoryRouteContext';
import type { RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { ProjectGraphPage } from '../desktop/project-knowledge/ProjectGraphPage';
import { createProjectGraphController } from '../desktop/project-knowledge/projectGraphController';
import { parseGraphV2 } from '../desktop/project-knowledge/graphWire';
import { PROJECT_GRAPH_DEGRADED_REASON, type ProjectGraphSnapshot } from '../desktop/project-knowledge/projectGraphClient';
import { signedMemoryBinding } from './signedMemoryBinding';
import '../../../../../agi-stack/apps/desktop/src/styles/tokens.css';
import '../desktop/project-knowledge/ProjectGraphPage.css';

async function mount(host: RichPageRuntime) {
  const context = await host.getContext();
  if (!context.projectId) throw new Error('project_required');
  const scope = { authority: 'cloud' as const, tenantId: context.tenantId, projectId: context.projectId };
  const snapshot = (raw: unknown): ProjectGraphSnapshot => ({
    ...parseGraphV2(raw, scope), scope, authority: 'cloud', scopeRevision: 0,
    availability: 'degraded', reasonCode: PROJECT_GRAPH_DEGRADED_REASON, allowedActions: ['view'],
  });
  const controller = createProjectGraphController({
    initialScope: scope, authority: 'cloud',
    client: {
      async load(_, options) {
        return snapshot(await host.invoke('read-graph', { limit: 1000 }, options));
      },
      async loadSource(_, { episodeUuid }, options) {
        return snapshot(await host.invoke('read-subgraph', {
          node_uuids: [episodeUuid], include_neighbors: false, limit: 1,
        }, options));
      },
    },
  });
  const zh = context.locale.startsWith('zh');
  const language = { locale: zh ? 'zh-CN' as const : 'en' as const, setLocale() {},
    t: (key: string) => key === 'common.refresh' ? (zh ? '刷新' : 'Refresh') : key,
  };
  function Graph() {
    const model = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
    useEffect(() => { void controller.load(scope); return controller.stop; }, []);
    return <ProjectGraphPage model={model} controller={controller} />;
  }
  // Reading graph data remains available when the account cannot preview a source memory.
  const binding = await signedMemoryBinding(host, context, scope).catch(() => null);
  createRoot(document.getElementById('root')!).render(
    <I18nContext.Provider value={language}><CloudMemoryRouteContextProvider value={binding}>
      <Graph />
    </CloudMemoryRouteContextProvider></I18nContext.Provider>
  );
}

void mount(window.memstack);
