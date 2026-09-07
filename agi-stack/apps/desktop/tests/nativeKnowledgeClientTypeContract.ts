import type {
  NativeKnowledgeClient,
  NativeKnowledgeCommand,
  NativeKnowledgeDiscoveryCommand,
  NativeKnowledgeObservedOptions,
  NativeKnowledgeSelectedOperation,
  NativeKnowledgeSyncOptions,
  NativeKnowledgeMutationMemory,
} from '../src/features/project-knowledge/nativeKnowledgeContracts';
import type { ProjectKnowledgeScope } from '../src/features/project-knowledge/projectKnowledgeClient';

declare const client: NativeKnowledgeClient;
declare const scope: ProjectKnowledgeScope;
declare const selected: Extract<
  NativeKnowledgeCommand,
  { operation: NativeKnowledgeSelectedOperation }
>;
declare const discovery: NativeKnowledgeDiscoveryCommand;
declare const observed: NativeKnowledgeObservedOptions;
declare const optional: NativeKnowledgeSyncOptions;
declare const mutationMemory: NativeKnowledgeMutationMemory;

client.execute(scope, discovery);
client.execute(scope, discovery, optional);
client.execute(scope, selected, observed);
// @ts-expect-error Selected mappings, decisions and recovery items require their observed scope.
client.execute(scope, selected);
// @ts-expect-error An optional scope cannot stand in for a required observed scope.
client.execute(scope, selected, optional);
const status = client.execute(scope, { operation: 'sync_status' });
status.then((response) => {
  const pending: number = response.result.status.pending_changes;
  void pending;
  // @ts-expect-error The status result is correlated with the command discriminant.
  response.result.receipt;
});

client.execute(scope, { operation: 'get', id: 'memory-1' }).then((response) => {
  const memoryId: string = response.result.memory.id;
  void memoryId;
  // @ts-expect-error Get returns a memory, not a mutation receipt.
  response.result.receipt;
});
client
  .execute(
    scope,
    { operation: 'create', memory: mutationMemory, idempotency_key: 'create-1' },
    observed,
  )
  .then((response) => {
    const accepted: 'accepted' = response.result.processing_status;
    const replayed: boolean = response.result.replayed;
    void accepted;
    void replayed;
  });
// @ts-expect-error A native mutation requires an observed context.
client.execute(scope, {
  operation: 'delete',
  id: 'memory-1',
  expected_revision: 1,
  idempotency_key: 'delete-1',
});
