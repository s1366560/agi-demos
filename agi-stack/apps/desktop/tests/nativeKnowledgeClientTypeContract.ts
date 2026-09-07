import type {
  NativeKnowledgeClient,
  NativeKnowledgeCommand,
  NativeKnowledgeDiscoveryCommand,
  NativeKnowledgeObservedOptions,
  NativeKnowledgeSelectedOperation,
  NativeKnowledgeSyncOptions,
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
