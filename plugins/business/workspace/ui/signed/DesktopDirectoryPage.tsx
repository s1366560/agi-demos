import React from 'react';
import { createRoot } from 'react-dom/client';
import { Theme, Button } from '@radix-ui/themes';
import '@radix-ui/themes/styles.css';
import '../../../../../agi-stack/apps/desktop/src/styles/tokens.css';
import { I18nContext } from '../../../../../agi-stack/apps/desktop/src/i18nContext';
import { ProjectWorkspacesPage } from '../desktop/project-workspaces/ProjectWorkspacesPage';
import { createProjectWorkspacesController } from '../desktop/project-workspaces/projectWorkspacesController';
import { useProjectWorkspacesController } from '../desktop/project-workspaces/useProjectWorkspacesController';
import {
  tenantWorkspacesEnUS,
  tenantWorkspacesZhCN,
} from '../desktop/tenant/tenantWorkspacesMessages';
import { useHostAppearance } from './useHostAppearance';
import { projectDirectory, workspaceCreation } from './createWorkspace';
import { readDirectory } from './readDirectory';

async function mount() {
  const host = window.memstack;
  const context = await host.getContext();
  if (!context.projectId) throw new Error('project_required');
  const base = projectDirectory(context.tenantId, context.projectId);
  const scope = {
    authority: 'cloud' as const,
    tenantId: context.tenantId,
    projectId: context.projectId,
  };
  const zh = context.locale.startsWith('zh');
  const messages: Readonly<Record<string, string>> = {
    ...(zh ? tenantWorkspacesZhCN : tenantWorkspacesEnUS),
    'common.cancel': zh ? '取消' : 'Cancel',
    'common.retry': zh ? '重试' : 'Retry',
    'workspaceCollaboration.title': zh ? '协作画布' : 'Collaboration canvas',
  };
  const create = workspaceCreation(host);
  const controller = createProjectWorkspacesController({
    initialScope: scope,
    authority: 'cloud',
    client: {
      async list(_, options) {
        const rows = await readDirectory(host, options?.signal);
        return {
          scope,
          authority: 'cloud',
          availability: 'available',
          reasonCode: null,
          serviceVersion: '1.4.0',
          contractVersion: '1.0.0',
          authorityRevision: null,
          allowedActions: context.commands.includes('create-workspace')
            ? ['create', 'open-blackboard']
            : ['open-blackboard'],
          workspaces: rows.map((item) => ({
            id: item.id,
            tenantId: scope.tenantId,
            projectId: scope.projectId,
            name: item.name,
            description: item.description ?? '',
            archived: !!item.is_archived,
            createdAt: item.created_at,
            updatedAt: item.updated_at ?? null,
          })),
        };
      },
      async create(_, input, options) {
        const item = await create(input, options?.signal);
        return {
          id: item.id,
          tenantId: scope.tenantId,
          projectId: scope.projectId,
          ...input,
          archived: false,
          createdAt: null,
          updatedAt: null,
        };
      },
    },
  });
  function Page() {
    const appearance = useHostAppearance();
    const { model, retry } = useProjectWorkspacesController(controller, scope);
    return (
      <Theme
        appearance={appearance}
        accentColor="gray"
        grayColor="slate"
        radius="medium"
        scaling="95%"
      >
        <ProjectWorkspacesPage
          model={model}
          controller={controller}
          onRetry={retry}
          onOpenBlackboard={(id) =>
            void host.navigate(base + '/' + encodeURIComponent(id))
          }
          extraActions={
            <Button
              variant="soft"
              color="gray"
              onClick={() => void host.navigate(base + '/export')}
            >
              {zh ? '导出 CSV' : 'Export CSV'}
            </Button>
          }
        />
      </Theme>
    );
  }
  createRoot(document.getElementById('root')!).render(
    <I18nContext.Provider
      value={{ locale: zh ? 'zh-CN' : 'en', setLocale: () => {}, t: (key) => messages[key] ?? key }}
    >
      <Page />
    </I18nContext.Provider>
  );
}
void mount();
