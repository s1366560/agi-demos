import { DesktopApiError } from '../api/client';
import type { DesktopRuntimeConfig } from '../types';
import type { NativeKnowledgeProcessingClient } from '../features/project-knowledge/nativeKnowledgeContracts';
import type {
  NativeKnowledgeProcessingInputsClient,
  NativeKnowledgeEmbeddingChoice,
  NativeKnowledgeInputDirectory,
  NativeKnowledgeWorkspaceChoice,
} from '../features/project-knowledge/nativeKnowledgeProcessingInputs';
import { projectKnowledgeError } from '../features/project-knowledge/projectKnowledgeClient';
import { requireNativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeValidation';
import { sameJson } from '../features/project-knowledge/nativeKnowledgeRelationships';
import type { DesktopTenantProvidersClientV2 } from './desktopTenantProvidersAuthorityModuleV2';
import type { DesktopWorkspaceCatalogOperationsV2 } from './desktopWorkspaceCatalogAuthorityModuleV2';
import { DesktopWorkspaceCatalogAuthorityUnavailableErrorV2 } from './desktopWorkspaceCatalogAuthorityModuleV2';
import {
  cloneDesktopProjectMemoriesRuntimeConfigV2,
  cloneDesktopProjectMemoriesScopeV2,
} from './desktopProjectMemoriesOperationContractV2';

type Dependencies = Readonly<{
  processing: NativeKnowledgeProcessingClient;
  providers: Pick<DesktopTenantProvidersClientV2, 'listLlmProviders' | 'discoverLlmProviderModels'>;
  workspaces: DesktopWorkspaceCatalogOperationsV2;
  isCurrent: (operation: 'configure_embedding' | 'process_one' | 'process_community_one') => boolean;
}>;
const unavailable = Object.freeze({
  availability: 'unavailable' as const,
  items: Object.freeze([]) as readonly [],
});
/** Only generation-owned catalogs supply selectable models and workspaces. */
export function createDesktopNativeKnowledgeInputsClientV2(
  config: DesktopRuntimeConfig,
  dependencies: Dependencies,
): NativeKnowledgeProcessingInputsClient {
  const runtime = cloneDesktopProjectMemoriesRuntimeConfigV2(config);
  return Object.freeze({
    async load(scope, input) {
      const pinned = cloneDesktopProjectMemoriesScopeV2(scope, runtime);
      if (
        pinned.authority !== 'local' ||
        !input ||
        !['configure_embedding', 'process_one', 'process_community_one'].includes(input.operation) ||
        Object.keys(input).some((key) => !['operation', 'expectedScope', 'signal'].includes(key))
      )
        throw invalid();
      const expected = requireNativeKnowledgeScope(
        { contract_version: '1.0.0', scope: input.expectedScope },
        pinned,
      );
      const signal = input.signal;
      const operation = input.operation;
      if (signal !== undefined && !(signal instanceof AbortSignal)) throw invalid();
      const current = () => {
        signal?.throwIfAborted();
        if (!dependencies.isCurrent(operation)) throw conflict();
      };
      const observe = async () => {
        current();
        const response = await dependencies.processing.query(
          pinned,
          { operation: operation === 'process_community_one' ? 'community_active' : 'configuration' },
          { signal, expectedScope: expected },
        );
        current();
        if (
          !sameJson(
            requireNativeKnowledgeScope(
              { contract_version: '1.0.0', scope: response.scope },
              pinned,
            ),
            expected,
          )
        )
          throw conflict();
      };
      await observe();
      let embeddingModels: NativeKnowledgeInputDirectory<NativeKnowledgeEmbeddingChoice> =
        unavailable;
      let workspaces: NativeKnowledgeInputDirectory<NativeKnowledgeWorkspaceChoice> = unavailable;
      if (operation === 'configure_embedding') {
        try {
          embeddingModels = await modelChoices(dependencies, pinned.tenantId, current, signal);
        } catch (error) {
          current();
          if (!directoryUnavailable(error)) throw error;
        }
      } else {
        try {
          const rows = await dependencies.workspaces.listWorkspacesForProject({
            config: Object.freeze({ ...runtime, workspaceId: '' }),
            signal,
          });
          current();
          const ids = new Set<string>();
          const items: NativeKnowledgeWorkspaceChoice[] = [];
          for (const row of rows) {
            if (row.tenant_id !== pinned.tenantId || row.project_id !== pinned.projectId)
              throw conflict();
            const id = identifier(row.id);
            if (ids.has(id)) throw invalid();
            ids.add(id);
            if (row.is_archived === true || row.status === 'archived' || row.status === 'deleted')
              continue;
            if (row.is_archived !== false && row.status !== 'active') continue;
            items.push(Object.freeze({ id, name: identifier(row.name ?? row.title) }));
          }
          workspaces = Object.freeze({ availability: 'available', items: Object.freeze(items) });
        } catch (error) {
          current();
          if (!directoryUnavailable(error)) throw error;
        }
      }
      await observe();
      current();
      return Object.freeze({ scope: expected, embeddingModels, workspaces });
    },
  } satisfies NativeKnowledgeProcessingInputsClient);
}
async function modelChoices(
  dependencies: Dependencies,
  tenantId: string,
  current: () => void,
  signal?: AbortSignal,
): Promise<NativeKnowledgeInputDirectory<NativeKnowledgeEmbeddingChoice>> {
  const rows = await dependencies.providers.listLlmProviders(signal);
  current();
  const ids = new Set<string>();
  const eligible: Readonly<{ id: string; name: string; revision: number }>[] = [];
  for (const provider of rows) {
    if (provider.tenant_id !== tenantId) throw conflict();
    const id = identifier(provider.id);
    if (ids.has(id)) throw invalid();
    ids.add(id);
    // This is the exact activation field required by the native embedding adapter.
    if (provider.is_active !== true) continue;
    if (!Number.isSafeInteger(provider.revision) || Number(provider.revision) < 0) throw invalid();
    eligible.push(
      Object.freeze({ id, name: identifier(provider.name), revision: Number(provider.revision) }),
    );
  }
  const items: NativeKnowledgeEmbeddingChoice[] = [];
  let observed = eligible.length === 0;
  for (const provider of eligible) {
    current();
    try {
      const catalog = await dependencies.providers.discoverLlmProviderModels(
        provider.id,
        provider.revision!,
        signal,
      );
      current();
      if (catalog.providerId !== provider.id) throw conflict();
      if (catalog.availability !== 'available') continue;
      observed = true;
      const models = new Set<string>();
      for (const model of catalog.models) {
        if (model.capability !== 'embedding') continue;
        const modelId = identifier(model.id);
        if (models.has(modelId)) throw invalid();
        models.add(modelId);
        items.push(
          Object.freeze({
            providerId: provider.id,
            providerRevision: provider.revision!,
            providerName: identifier(provider.name),
            modelId,
          }),
        );
      }
    } catch (error) {
      current();
      if (!directoryUnavailable(error)) throw error;
    }
  }
  return observed
    ? Object.freeze({ availability: 'available', items: Object.freeze(items) })
    : unavailable;
}
function directoryUnavailable(error: unknown): boolean {
  return (
    error instanceof DesktopWorkspaceCatalogAuthorityUnavailableErrorV2 ||
    (error instanceof DesktopApiError && [403, 404, 501, 502, 503].includes(error.status))
  );
}
function identifier(value: unknown): string {
  if (
    typeof value !== 'string' ||
    !value ||
    value !== value.trim() ||
    value.length > 512 ||
    /[\u0000-\u001f\u007f]/u.test(value)
  )
    throw invalid();
  return value;
}
function invalid(): Error {
  return projectKnowledgeError('native_knowledge_inputs_invalid');
}
function conflict(): Error {
  return projectKnowledgeError('project_knowledge_scope_conflict', 409);
}
