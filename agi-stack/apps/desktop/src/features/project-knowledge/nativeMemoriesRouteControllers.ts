import type { NativeMemoriesRouteBinding } from './NativeMemoriesRouteContext';
import { createNativeMemoriesController } from './nativeMemoriesController';
import { createProjectMemoriesController } from './projectMemoriesController';
import { createNativeKnowledgeCloudConnectionController } from './nativeKnowledgeCloudConnectionController';
import { createNativeKnowledgeSyncController } from './nativeKnowledgeSyncController';
import { createNativeKnowledgeConflictController } from './nativeKnowledgeConflictController';
import { createNativeKnowledgeRetrievalController } from './nativeKnowledgeRetrievalController';
import { createNativeKnowledgeProcessingController } from './nativeKnowledgeProcessingController';
import { createNativeKnowledgeDiagnosticsController } from './nativeKnowledgeDiagnosticsController';

/** Every controller shares the admitted binding; callbacks refresh reads without replaying writes. */
export function createNativeMemoriesRouteControllers(binding: NativeMemoriesRouteBinding) {
  const list = createProjectMemoriesController({
    authority: 'local',
    client: binding.listClient,
    initialScope: binding.authority.scope,
  });
  const retrieval = createNativeKnowledgeRetrievalController({
    client: binding.processingClient,
    sourceClient: binding.client,
    authority: binding.authority,
  });
  const diagnostics = createNativeKnowledgeDiagnosticsController({
    client: binding.processingClient,
    authority: binding.authority,
  });
  const refreshDerived = () => {
    retrieval.clearNavigation();
    void retrieval.refreshConfiguration();
    void diagnostics.refresh();
  };
  const sourceAccepted = () => {
    if (binding.authority.allowedActions.includes('list')) void list.retry();
    sync.invalidateSources();
    processing.invalidateSources();
    refreshDerived();
  };
  const editor = createNativeMemoriesController({
    client: binding.client,
    authority: binding.authority,
    onAccepted: sourceAccepted,
  });
  const connection = createNativeKnowledgeCloudConnectionController({
    client: binding.connectionClient,
    sourceClient: binding.client,
    authClient: binding.cloudAuthClient ?? null,
    authority: binding.authority,
    onAccepted: () => {
      void sync.refresh();
    },
  });
  const sync = createNativeKnowledgeSyncController({
    canSync: () => connection.getSnapshot().bound,
    client: binding.client,
    authority: binding.authority,
    onAccepted: sourceAccepted,
  });
  const conflicts = createNativeKnowledgeConflictController({
    client: binding.client,
    authority: binding.authority,
    onAccepted: sourceAccepted,
  });
  const processing = createNativeKnowledgeProcessingController({
    queryClient: binding.processingClient,
    commandClient: binding.processingCommandClient,
    inputsClient: binding.processingInputsClient,
    authority: binding.authority,
    onAccepted: refreshDerived,
  });
  return Object.freeze({
    list,
    editor,
    sync,
    conflicts,
    retrieval,
    processing,
    diagnostics,
    connection,
  });
}
