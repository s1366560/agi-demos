import React from 'react';
import { createRoot } from 'react-dom/client';
import { ProjectKnowledgeView } from '../desktop/project-knowledge/ProjectKnowledgeView';
import { createProjectKnowledgeController } from '../desktop/project-knowledge/projectKnowledgeController';
import { buildProjectEntitiesPresentation } from '../desktop/project-knowledge/projectEntitiesPresentationModel';
import { useProjectKnowledgeController } from '../desktop/project-knowledge/useProjectKnowledgeController';
import type { Entity } from '../web/services/graphService';
import type { RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

async function mount(host: RichPageRuntime) {
  const context = await host.getContext();
  if (!context.projectId) throw new Error('project_required');
  const scope = { authority: 'cloud' as const, tenantId: context.tenantId, projectId: context.projectId };
  const controller = createProjectKnowledgeController({
    authority: scope.authority, initialScope: scope, buildPresentation: buildProjectEntitiesPresentation,
    client: {
      async load(_scope, options) {
        const page = await host.invoke('list-entities', { limit: 100 }, options) as {
          entities: Entity[]; total: number;
        };
        return {
          scope, authority: scope.authority, scopeRevision: 0, availability: 'available', reasonCode: null,
          allowedActions: ['read'], total: page.total, entityTypes: [],
          entities: page.entities.map(row => ({ id: row.uuid, name: row.name, entityType: row.entity_type,
            summary: row.summary, projectId: scope.projectId, createdAt: row.created_at ?? null })),
        };
      },
    },
  });
  const labels: Record<string, string> = context.locale.startsWith('zh') ? {
    'common.retry': '重试', 'common.pagination': '分页', 'common.previousPage': '上一页', 'common.nextPage': '下一页',
  } : {
    'common.retry': 'Retry', 'common.pagination': 'Pagination', 'common.previousPage': 'Previous page', 'common.nextPage': 'Next page',
  };
  function Entities() {
    const { model, retry } = useProjectKnowledgeController(controller, scope);
    return <ProjectKnowledgeView model={model} onRetry={retry} t={key => labels[key] ?? key} />;
  }
  createRoot(document.getElementById('root')!).render(<Entities />);
}

void mount(window.memstack);
