import type { ProjectKnowledgeScope } from './projectKnowledgeClient';
import type {
  NativeKnowledgeScope,
  NativeKnowledgeRequestMap,
  NativeKnowledgeResultMap,
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingResultMap,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeProcessingCommandResultMap,
} from './nativeKnowledgeGenerated';

export type * from './nativeKnowledgeGenerated';

export type NativeKnowledgeOperation = keyof NativeKnowledgeRequestMap;
export type NativeKnowledgeCommand = {
  [K in NativeKnowledgeOperation]: Readonly<{ operation: K }> & NativeKnowledgeRequestMap[K];
}[NativeKnowledgeOperation];
export type NativeKnowledgeResponse<C extends NativeKnowledgeCommand = NativeKnowledgeCommand> =
  Readonly<{
    contract_version: '1.0.0';
    operation: C['operation'];
    scope: NativeKnowledgeScope;
    result: NativeKnowledgeResultMap[C['operation']];
  }>;
export interface NativeKnowledgeSyncAuthority {
  observeScope?(
    options: NativeKnowledgeScopeObservationOptions,
    requireCurrent?: () => void,
  ): Promise<NativeKnowledgeScope>;
  executeSync<C extends NativeKnowledgeCommand>(
    command: C,
    options?: NativeKnowledgeSyncOptions,
  ): Promise<NativeKnowledgeResponse<C>>;
}
export type NativeKnowledgeSyncOptions = Readonly<{
  signal?: AbortSignal;
  /** A previously observed context; changes must not silently rebind a decision. */
  expectedScope?: NativeKnowledgeScope;
}>;
export type NativeKnowledgeScopeObservationOptions = Readonly<{
  expectedActorId: string;
  signal?: AbortSignal;
}>;
export type NativeKnowledgeSelectedOperation =
  | 'create'
  | 'update'
  | 'delete'
  | 'sync_link'
  | 'sync_unbind'
  | 'resolve_pull'
  | 'resolve_push'
  | 'resume_resolution'
  | 'reconcile_resolution';
export type NativeKnowledgeDiscoveryCommand = Exclude<
  NativeKnowledgeCommand,
  { operation: NativeKnowledgeSelectedOperation }
>;
export type NativeKnowledgeObservedOptions = NativeKnowledgeSyncOptions &
  Readonly<{ expectedScope: NativeKnowledgeScope }>;
export interface NativeKnowledgeClient {
  observeScope(
    scope: ProjectKnowledgeScope,
    options: NativeKnowledgeScopeObservationOptions,
  ): Promise<NativeKnowledgeScope>;
  execute<C extends NativeKnowledgeCommand>(
    scope: ProjectKnowledgeScope,
    command: C,
    options: NativeKnowledgeObservedOptions,
  ): Promise<NativeKnowledgeResponse<C>>;
  execute<C extends NativeKnowledgeDiscoveryCommand>(
    scope: ProjectKnowledgeScope,
    command: C,
    options?: NativeKnowledgeSyncOptions,
  ): Promise<NativeKnowledgeResponse<C>>;
}

export type NativeKnowledgeProcessingResponse<
  Q extends NativeKnowledgeProcessingQuery = NativeKnowledgeProcessingQuery,
> = Readonly<{
  contract_version: '1.0.0';
  scope: NativeKnowledgeScope;
  result: NativeKnowledgeProcessingResultMap[Q['operation']];
}>;
export type NativeKnowledgeProcessingDiscoveryQuery = Exclude<
  NativeKnowledgeProcessingQuery,
  { operation: 'semantic' | 'graph_source' }
>;
/** Read-only processing wire surface, supplied only by the admitted native authority. */
export interface NativeKnowledgeProcessingClient {
  query<Q extends NativeKnowledgeProcessingQuery>(
    scope: ProjectKnowledgeScope,
    query: Q,
    options: NativeKnowledgeObservedOptions,
  ): Promise<NativeKnowledgeProcessingResponse<Q>>;
  query<Q extends NativeKnowledgeProcessingDiscoveryQuery>(
    scope: ProjectKnowledgeScope,
    query: Q,
    options?: NativeKnowledgeSyncOptions,
  ): Promise<NativeKnowledgeProcessingResponse<Q>>;
}

export type NativeKnowledgeProcessingCommandResponse<
  C extends NativeKnowledgeProcessingCommand = NativeKnowledgeProcessingCommand,
> = Readonly<{
  contract_version: '1.0.0';
  scope: NativeKnowledgeScope;
  result: NativeKnowledgeProcessingCommandResultMap[C['operation']];
}>;
/** Explicit writes require the exact context observed by the caller. */
export interface NativeKnowledgeProcessingCommandClient {
  execute<C extends NativeKnowledgeProcessingCommand>(
    scope: ProjectKnowledgeScope,
    command: C,
    options: NativeKnowledgeObservedOptions,
  ): Promise<NativeKnowledgeProcessingCommandResponse<C>>;
}
