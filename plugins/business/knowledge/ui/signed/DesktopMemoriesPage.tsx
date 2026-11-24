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
import { parseCloudMemoryCapabilities } from '../desktop/project-knowledge/cloudMemoryCapabilities';
import { parseMemoryV2 } from '../desktop/project-knowledge/cloudMemoryProjection';
import {
  cloudMemoriesEnUS,
  cloudMemoriesZhCN,
} from '../desktop/project-knowledge/locales/cloudMemoriesMessages';
import type {
  CloudMemoryClient,
  CloudMemoryResponse,
} from '../desktop/project-knowledge/cloudMemoryClient';
import type { ProjectKnowledgeScope } from '../desktop/project-knowledge/projectKnowledgeClient';
import type { RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

interface DirectoryResponse {
  actor_id: string;
  memories: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
  command_capabilities: unknown;
}

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
  };
  const language = {
    locale: zh ? ('zh-CN' as const) : ('en' as const),
    setLocale: () => {},
    t: (key: string) => labels[key] ?? key,
  };
  const root = createRoot(document.getElementById('root')!);
  const list = (page: number, signal?: AbortSignal) =>
    host.invoke('list-memories', { page, page_size: 50 }, { signal }) as Promise<DirectoryResponse>;
  let first: DirectoryResponse | undefined;
  try {
    first = await list(1);
  } catch {
    root.render(
      <I18nContext.Provider value={language}>
        <CloudMemoriesUnavailable />
      </I18nContext.Provider>
    );
    return;
  }
  const actorId = first.actor_id;
  if (!actorId) throw new Error('memory_actor_required');
  const client: CloudMemoryClient = {
    async execute(_, command, options) {
      let recordId: string;
      if (command.operation === 'get') recordId = command.id;
      else {
        if (command.operation === 'delete') throw new Error('page_command_denied');
        const create = command.operation === 'create';
        const fields = create ? command.memory : command.patch;
        const saved = (await host.invoke(
          'save-memory',
          {
            ...fields,
            ...(create ? {} : { id: command.id }),
            version: create ? 0 : command.expectedRevision,
            change_id: command.idempotencyKey,
          },
          { signal: options.signal }
        )) as { id: string };
        recordId = saved.id;
      }
      const wire = await host.invoke(
        'read-memory',
        { id: recordId, detail: true },
        { signal: options.signal }
      );
      return {
        operation: command.operation,
        result: parseMemoryV2(wire, scope),
      } as CloudMemoryResponse<typeof command>;
    },
  };
  const controller = createCloudMemoriesController({
    authority: {
      binding: 'signed-page',
      scope,
      actorId,
      contextRevision: 0,
      available: true,
      allowedActions: ['list', 'view'],
    },
    client,
    listClient: {
      async load(_, options) {
        const page = options?.page ?? 1;
        const response = page === 1 && first ? first : await list(page, options?.signal);
        first = undefined;
        if (response.actor_id !== actorId) throw new Error('cloud_memory_ui_scope_conflict');
        const memories = response.memories.map((row) => parseMemoryV2(row, scope));
        const authenticated = parseCloudMemoryCapabilities(
          response.command_capabilities,
          scope,
          memories,
          actorId
        );
        const capabilities =
          authenticated && context.commands.includes('save-memory')
            ? {
                ...authenticated,
                objects: authenticated.objects.map((object) => ({
                  ...object,
                  allowedActions: object.allowedActions.filter((action) => action === 'update'),
                })),
              }
            : null;
        return {
          scope,
          scopeRevision: 0,
          authority: 'cloud',
          availability: 'available',
          reasonCode: null,
          allowedActions: ['list', 'view'],
          memories,
          page: response.page,
          pageSize: response.page_size,
          total: response.total,
          commandCapabilities: capabilities,
        };
      },
    },
  });
  function Page() {
    const model = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
    useEffect(() => {
      controller.activate();
      void controller.loadPage();
      return () => controller.stop();
    }, []);
    return <CloudMemoriesPage model={model} controller={controller} />;
  }
  root.render(
    <I18nContext.Provider value={language}>
      <Page />
    </I18nContext.Provider>
  );
}
void mount(window.memstack);
