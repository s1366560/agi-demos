import React from 'react';
import { createRoot } from 'react-dom/client';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';

import type { RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { createEntitiesList } from '../web/project/createEntitiesList';
import type { Entity, EntityTypeStats, EntityRelationships } from '../web/services/graphService';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './entities.css';

async function mount(host: RichPageRuntime) {
  const scope = await host.getContext();
  const instance = createInstance();
  await instance.init({
    lng: scope.locale.startsWith('zh') ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const Entities = createEntitiesList({
    async listEntities({ entity_type, limit, offset }) {
      const result = await host.invoke('list-entities', { entity_type, limit, offset }) as {
        entities: Entity[]; total: number; limit: number; offset: number;
      };
      return { ...result, items: result.entities, has_more: result.offset + result.entities.length < result.total };
    },
    getEntityTypes: () => host.invoke('entity-types') as Promise<EntityTypeStats>,
    getEntityRelationships: (entity_id, params) => host.invoke('entity-relationships', {
      entity_id, limit: params?.limit ?? 50,
    }) as Promise<EntityRelationships>,
  });
  const router = createMemoryRouter([
    { path: '*', element: <Entities tenantId={scope.tenantId} projectId={scope.projectId!} /> },
  ], { initialEntries: [scope.pathname + (scope.search ?? '') + (scope.hash ?? '')] });
  let last = router.state.location.search;
  router.subscribe(({ location }) => {
    if (location.search === last) return;
    last = location.search;
    void host.navigate(scope.pathname + last + location.hash, { replace: true });
  });
  createRoot(document.getElementById('root')!).render(
    <I18nextProvider i18n={instance}><RouterProvider router={router} /></I18nextProvider>
  );
}

void mount(window.memstack);
