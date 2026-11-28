import type { CloudMemoryRouteBinding } from '../../../../../agi-stack/apps/desktop/src/features/project-knowledge/CloudMemoryRouteContext';
import { parseCloudMemoryCapabilities } from '../desktop/project-knowledge/cloudMemoryCapabilities';
import { parseMemoryV2 } from '../desktop/project-knowledge/cloudMemoryProjection';
import type {
  CloudMemoryClient,
  CloudMemoryResponse,
} from '../desktop/project-knowledge/cloudMemoryClient';
import type { ProjectKnowledgeScope } from '../desktop/project-knowledge/projectKnowledgeClient';
import type { RichPageContext, RichPageRuntime } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

interface DirectoryResponse {
  actor_id: string;
  memories: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
  command_capabilities: unknown;
}

export async function signedMemoryBinding(
  host: RichPageRuntime, context: RichPageContext, scope: ProjectKnowledgeScope,
): Promise<CloudMemoryRouteBinding> {
  const list = (page: number, signal?: AbortSignal) =>
    host.invoke('list-memories', { page, page_size: 50 }, { signal }) as Promise<DirectoryResponse>;
  let first: DirectoryResponse | undefined = await list(1);
  const actorId = first.actor_id;
  if (!actorId) throw new Error('memory_actor_required');
  const client: CloudMemoryClient = {
    async execute(_, command, options) {
      let recordId: string;
      if (command.operation === 'get') recordId = command.id;
      else {
        if (command.operation === 'delete') {
          const result = await host.invoke(
            'delete-memory',
            {
              id: command.id,
              version: command.expectedRevision,
              change_id: command.idempotencyKey,
            },
            { signal: options.signal },
          );
          return { operation: command.operation, result } as CloudMemoryResponse<typeof command>;
        }
        const create = command.operation === 'create';
        const fields = create ? command.memory : command.patch;
        const saved = (await host.invoke(
          'save-memory',
          {
            title: fields.title,
            content: fields.content,
            tags: fields.tags,
            metadata: fields.metadata,
            ...(create ? {} : { id: command.id }),
            version: create ? 0 : command.expectedRevision,
            change_id: command.idempotencyKey,
          },
          { signal: options.signal },
        )) as { id: string };
        recordId = saved.id;
      }
      const wire = await host.invoke(
        'read-memory',
        { id: recordId, detail: true },
        { signal: options.signal },
      );
      return {
        operation: command.operation,
        result: parseMemoryV2(wire, scope),
      } as CloudMemoryResponse<typeof command>;
    },
  };
  return {
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
          actorId,
        );
        const capabilities =
          authenticated && context.commands.includes('save-memory')
            ? {
                ...authenticated,
                objects: authenticated.objects.map((object) => ({
                  ...object,
                  allowedActions: object.allowedActions.filter(
                    (action) => action === 'update' || context.commands.includes('delete-memory'),
                  ),
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
  };
}
