import type { ProjectKnowledgeScope } from './projectKnowledgeClient';

export type NativeKnowledgeJson =
  | null
  | boolean
  | number
  | string
  | readonly NativeKnowledgeJson[]
  | { readonly [key: string]: NativeKnowledgeJson };
export type NativeKnowledgeObject = { readonly [key: string]: NativeKnowledgeJson };
export type NativeKnowledgeScope = Readonly<{
  tenant_id: string;
  project_id: string;
  context_revision: number;
  profile_id: string;
  generation: number;
  digest: string;
}>;
export type NativeKnowledgeLink = Readonly<{
  remote_tenant_id: string;
  remote_project_id: string;
  /** Explicit association only; the sidecar separately verifies the cloud actor. */
  remote_actor_id: string;
}>;
export type NativeKnowledgeStatus = Readonly<{
  replica_id: string;
  link: NativeKnowledgeLink | null;
  pending_changes: number;
}>;
export type NativeKnowledgeMemory = Readonly<{
  id: string;
  project_id: string;
  title: string;
  content: string;
  author_id: string;
  content_type: string;
  tags: readonly string[];
  entities: readonly NativeKnowledgeJson[];
  version: number;
  status: string;
  created_at_ms: number;
  embedding: readonly number[] | null;
}>;
export type NativeKnowledgeContent = Readonly<{
  title: string;
  content: string;
  content_type: 'text' | 'document' | 'image' | 'video';
  tags: readonly string[];
  metadata: NativeKnowledgeObject;
  status: 'ENABLED' | 'DISABLED';
}>;
/** Unknown server extensions are preserved as JSON, alongside validated known fields. */
export type NativeKnowledgeRemote = NativeKnowledgeObject &
  Readonly<{
    memory_id: string;
    revision: number;
    deleted: boolean;
    author_id: string;
    created_at_ms: number;
    content: NativeKnowledgeContent;
  }>;
export type NativeKnowledgeProposal = NativeKnowledgeObject &
  Readonly<{
    memory_id: string;
    operation: 'create' | 'update' | 'delete';
    expected_revision: number;
    content: NativeKnowledgeContent | null;
  }>;
export type NativeKnowledgePushConflict = NativeKnowledgeObject &
  Readonly<{
    id: string;
    memory_id: string;
    proposed: NativeKnowledgeProposal;
    current: NativeKnowledgeRemote | null;
    resolved_change_id: string | null;
  }>;
export type NativeKnowledgePullConflict = Readonly<{
  sequence: number;
  memory_id: string;
  remote: NativeKnowledgeRemote;
  local: NativeKnowledgeMemory | null;
  local_deleted: boolean;
  baseline: NativeKnowledgeRemote | null;
}>;
export type NativeKnowledgeGuard = Readonly<{
  expected_local_revision: number;
  expected_remote_revision: number;
  expected_baseline_revision: number;
  conflict_sequences: readonly number[];
}>;
export type NativeKnowledgeLocalChoice =
  | Readonly<{ decision: 'use_local' | 'use_remote' | 'keep_both' }>
  | Readonly<{ decision: 'merged'; content: NativeKnowledgeContent }>;
export type NativeKnowledgeCloudChoice =
  | Readonly<{ decision: 'keep_current' | 'use_proposed' }>
  | Readonly<{ decision: 'merged'; content: NativeKnowledgeContent }>;
export type NativeKnowledgePullResolution = NativeKnowledgeGuard &
  Readonly<{
    memory_id: string;
    choice: NativeKnowledgeLocalChoice;
  }>;
export type NativeKnowledgeCloudResolution = Readonly<{
  local_sequence: number;
  memory_id: string;
  conflict_id: string;
  guard: NativeKnowledgeGuard;
  choice: NativeKnowledgeCloudChoice;
}>;
export type NativeKnowledgeReconciliation = Readonly<{
  guard: NativeKnowledgeGuard;
  choice: NativeKnowledgeLocalChoice;
}>;
export type NativeKnowledgePullContext = Readonly<{
  memory_id: string;
  conflict_sequences: readonly number[];
  local: NativeKnowledgeMemory;
  local_deleted: boolean;
  local_metadata: NativeKnowledgeObject;
  baseline: NativeKnowledgeRemote | null;
  remote: NativeKnowledgeRemote;
}>;
export type NativeKnowledgeCloudContext = Readonly<{
  local_sequence: number;
  memory_id: string;
  conflict_id: string;
  original_request: NativeKnowledgeProposal & Readonly<{ change_id: string }>;
  cloud_conflict: NativeKnowledgePushConflict;
  local: NativeKnowledgeMemory;
  local_deleted: boolean;
  local_metadata: NativeKnowledgeObject;
  baseline: NativeKnowledgeRemote | null;
  remote: NativeKnowledgeRemote | null;
  conflict_sequences: readonly number[];
  pending_sequences: readonly number[];
  observed_cursor: number;
}>;
export type NativeKnowledgeLocalReceipt = Readonly<{
  resolution_id: string;
  memory_id: string;
  local_revision: number;
  remote_baseline_revision: number;
  copy_memory_id: string | null;
  processing_sequences: readonly number[];
  pending_push_sequences: readonly number[];
  superseded_sequences: readonly number[];
  conflict_sequences: readonly number[];
}>;
export type NativeKnowledgeReconciliationReceipt = Readonly<{
  local_revision: number;
  copy_memory_id: string | null;
  processing_sequences: readonly number[];
  pending_push_sequences: readonly number[];
  superseded_sequences: readonly number[];
  conflict_sequences: readonly number[];
}>;
export type NativeKnowledgeAppliedReceipt = NativeKnowledgeObject &
  Readonly<{
    status: 'applied';
    change_id: string;
    sequence: number;
    version: NativeKnowledgeRemote;
  }>;
export type NativeKnowledgeResolvedReceipt = NativeKnowledgeObject &
  Readonly<{
    status: 'resolved';
    change_id: string;
    conflict_id: string;
    version: NativeKnowledgeRemote | null;
  }>;
export type NativeKnowledgeCloudReceipt =
  | NativeKnowledgeAppliedReceipt
  | NativeKnowledgeResolvedReceipt;
export type NativeKnowledgeCloudOutcome = Readonly<{
  resolution_id: string;
  receipt: NativeKnowledgeCloudReceipt;
  pending_reconciliation: boolean;
  replayed: boolean;
}>;
export type NativeKnowledgeResolutionRecord = Readonly<{
  resolution_id: string;
  local_sequence: number;
  request_json: string;
  command: NativeKnowledgeCloudResolution;
  archive: NativeKnowledgeCloudContext;
  receipt: NativeKnowledgeCloudReceipt | null;
  rejection: NativeKnowledgeObject | null;
  reconciliation: NativeKnowledgeReconciliationReceipt | null;
  reconciliation_command:
    | NativeKnowledgeReconciliation
    | Readonly<{ source: 'cloud_receipt' }>
    | null;
  reconciliation_archive: NativeKnowledgeCloudContext | null;
}>;

type Page = Readonly<{ limit: number }>;
type Id = Readonly<{ id: string }>;
type ResolutionId = Readonly<{ resolution_id: string }>;
export interface NativeKnowledgeRequestMap {
  sync_status: Readonly<Record<never, never>>;
  sync_link: Readonly<{ link: NativeKnowledgeLink }>;
  sync_push: Readonly<Record<never, never>>;
  sync_pull: Readonly<Record<never, never>>;
  sync_outbox: Page & Readonly<{ after_sequence: number }>;
  remote_baseline: Id;
  push_conflicts: Page;
  pull_conflicts: Page;
  pull_conflict_context: Id;
  resolution_history: Id & Page;
  resolve_pull: Readonly<{ resolution: NativeKnowledgePullResolution; idempotency_key: string }>;
  cloud_conflict_context: Readonly<{ local_sequence: number }>;
  resolve_push: Readonly<{ resolution: NativeKnowledgeCloudResolution; idempotency_key: string }>;
  resume_resolution: ResolutionId;
  reconcile_resolution: ResolutionId & Readonly<{ reconciliation: NativeKnowledgeReconciliation }>;
  resolution: ResolutionId;
  resolution_by_key: Readonly<{ idempotency_key: string }>;
  resolutions: Page;
  pending_resolutions: Page & Readonly<{ before_resolution_id?: string | null }>;
  reconciliation_context: ResolutionId;
}
export type NativeKnowledgeOperation = keyof NativeKnowledgeRequestMap;
export type NativeKnowledgeCommand = {
  [K in NativeKnowledgeOperation]: Readonly<{ operation: K }> & NativeKnowledgeRequestMap[K];
}[NativeKnowledgeOperation];
export interface NativeKnowledgeResultMap {
  sync_status: Readonly<{ status: NativeKnowledgeStatus }>;
  sync_link: Readonly<{
    status: NativeKnowledgeStatus;
    association_state: 'configured';
    remote_authorization: 'unverified';
  }>;
  sync_push: Readonly<{
    local_sequence: number;
    replayed: boolean;
    receipt:
      | NativeKnowledgeAppliedReceipt
      | (NativeKnowledgeObject &
          Readonly<{
            status: 'conflict';
            change_id: string;
            conflict_id: string;
          }>);
  }> | null;
  sync_pull: Readonly<{
    next_cursor: number;
    applied: number;
    conflicts: number;
    has_more: boolean;
  }>;
  sync_outbox: Readonly<{
    items: readonly Readonly<{
      change_id: string;
      local_change: Readonly<{
        sequence: number;
        memory: NativeKnowledgeMemory;
        deleted: boolean;
      }>;
    }>[];
    next_sequence: number;
  }>;
  remote_baseline: Readonly<{ version: NativeKnowledgeRemote | null }>;
  push_conflicts: Readonly<{ items: readonly NativeKnowledgePushConflict[] }>;
  pull_conflicts: Readonly<{ items: readonly NativeKnowledgePullConflict[] }>;
  pull_conflict_context: Readonly<{ context: NativeKnowledgePullContext | null }>;
  resolution_history: Readonly<{
    items: readonly Readonly<{
      request: NativeKnowledgePullResolution;
      receipt: NativeKnowledgeLocalReceipt;
      archive: NativeKnowledgePullContext;
    }>[];
  }>;
  resolve_pull: Readonly<{ receipt: NativeKnowledgeLocalReceipt; replayed: boolean }>;
  cloud_conflict_context: Readonly<{ context: NativeKnowledgeCloudContext }>;
  resolve_push: NativeKnowledgeCloudOutcome;
  resume_resolution: NativeKnowledgeCloudOutcome;
  reconcile_resolution: NativeKnowledgeCloudOutcome;
  resolution: Readonly<{ record: NativeKnowledgeResolutionRecord }>;
  resolution_by_key: Readonly<{ record: NativeKnowledgeResolutionRecord | null }>;
  resolutions: Readonly<{ items: readonly NativeKnowledgeResolutionRecord[] }>;
  pending_resolutions: Readonly<{
    items: readonly NativeKnowledgeResolutionRecord[];
    next_before_resolution_id: string | null;
  }>;
  reconciliation_context: Readonly<{ context: NativeKnowledgeCloudContext }>;
}
export type NativeKnowledgeResponse<C extends NativeKnowledgeCommand = NativeKnowledgeCommand> =
  Readonly<{
    contract_version: '1.0.0';
    operation: C['operation'];
    scope: NativeKnowledgeScope;
    result: NativeKnowledgeResultMap[C['operation']];
  }>;
export interface NativeKnowledgeSyncAuthority {
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
export type NativeKnowledgeSelectedOperation =
  | 'sync_link'
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
