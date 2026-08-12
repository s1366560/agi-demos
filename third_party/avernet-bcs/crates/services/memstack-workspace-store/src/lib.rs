//! Transactional persistence for the MemStack Workspace extension.
//!
//! The crate owns dialect-aware SQL and the mutation receipt/revision/outbox
//! transaction contract. HTTP adapters and application services supply
//! validated commands plus domain-specific checked mutations.

mod agent;
mod autonomy;
mod blackboard;
mod blackboard_mutation;
mod context;
mod creation;
mod event;
mod file;
mod gene;
mod member;
mod message;
mod message_delivery;
mod objective;
mod plan;
mod plan_authority;
mod plan_delivery;
mod plan_records;
mod plan_replay;
mod plan_snapshot_sql;
mod policy;
mod profile;
mod repository;
mod task;
mod task_dispatch;
mod task_mutation;
mod topology;
mod topology_mutation;

pub use agent::{WorkspaceAgentSnapshot, WorkspaceAgentStore, WorkspaceAgentStoreError};
pub use autonomy::{
    WorkspaceAutonomyJudgmentAudit, WorkspaceAutonomyMutation, WorkspaceAutonomyMutationOutcome,
    WorkspaceAutonomyScope, WorkspaceAutonomyStore, WorkspaceAutonomyStoreError,
};
pub use blackboard::{
    WorkspaceBlackboardDomainWrite, WorkspaceBlackboardMutation,
    WorkspaceBlackboardMutationOutcome, WorkspaceBlackboardPostRecord,
    WorkspaceBlackboardReplyRecord, WorkspaceBlackboardScope, WorkspaceBlackboardStore,
    WorkspaceBlackboardStoreError,
};
pub use context::{
    WorkspaceContextAccessSnapshot, WorkspaceContextAuditRecord, WorkspaceContextCandidateSnapshot,
    WorkspaceContextEventReceipt, WorkspaceContextSnapshot, WorkspaceContextStore,
    WorkspaceContextStoreError, WorkspaceContextTransition, WorkspaceContextTransitionKind,
};
pub use creation::{
    WorkspaceCreationOwnerIdentity, WorkspaceCreationPlan, WorkspaceCreationPlanError,
    WorkspaceCreationPlanner, WorkspaceCreationTimestamps,
};
pub use event::{LegacyWorkspaceEvent, LegacyWorkspaceEventError};
pub use file::{
    WorkspaceFileDomainWrite, WorkspaceFileMutation, WorkspaceFileMutationOutcome,
    WorkspaceFileOperationRecord, WorkspaceFileRecord, WorkspaceFileScope, WorkspaceFileStore,
    WorkspaceFileStoreError,
};
pub use gene::{
    WorkspaceGeneDomainWrite, WorkspaceGeneMutation, WorkspaceGeneMutationOutcome,
    WorkspaceGeneRecord, WorkspaceGeneScope, WorkspaceGeneStore, WorkspaceGeneStoreError,
};
pub use member::{WorkspaceMemberSnapshot, WorkspaceMemberStore, WorkspaceMemberStoreError};
pub use message::{
    ResolvedWorkspaceMentions, WorkspaceMessageDeliveryTarget, WorkspaceMessageRecord,
    WorkspaceMessageScope, WorkspaceMessageStore, WorkspaceMessageStoreError,
    WorkspaceMessageWrite, WorkspaceMessageWriteOutcome,
};
pub use message_delivery::{WorkspaceMessageDeliveryClaim, WorkspaceMessageDeliveryFailureOutcome};
pub use objective::{
    WorkspaceObjectiveDomainWrite, WorkspaceObjectiveMutation, WorkspaceObjectiveMutationOutcome,
    WorkspaceObjectiveRecord, WorkspaceObjectiveScope, WorkspaceObjectiveStore,
    WorkspaceObjectiveStoreError,
};
pub use plan::{
    WorkspaceDomainMutation, WorkspaceMutationPlan, WorkspaceMutationPlanError,
    WorkspaceMutationPlanner,
};
pub use plan_authority::{
    WorkspacePipelineRunRecord, WorkspacePlanBlackboardRecord, WorkspacePlanEventRecord,
    WorkspacePlanJudgmentAudit, WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord,
    WorkspacePlanRecord, WorkspacePlanScope, WorkspacePlanSnapshot, WorkspacePlanSnapshotQuery,
    WorkspacePlanStore, WorkspacePlanTransition, WorkspacePlanTransitionKind,
    WorkspacePlanTransitionOutcome,
};
pub use plan_delivery::{
    WORKSPACE_PLAN_RUNTIME_EVENT_TYPES, WorkspacePlanDeliveryClaim,
    WorkspacePlanDeliveryCompletion, WorkspacePlanDeliveryFailureOutcome,
    WorkspacePlanDeliveryStore, WorkspacePlanDeliveryStoreError,
};
pub use plan_records::WorkspacePlanStoreError;
pub use policy::{
    WorkspacePolicyScopeSnapshot, WorkspacePolicySnapshot, WorkspacePolicyStore,
    WorkspacePolicyStoreError,
};
pub use profile::{WorkspaceProfileSnapshot, WorkspaceProfileStore, WorkspaceProfileStoreError};
pub use repository::{
    WorkspaceMutationOutcome, WorkspaceMutationStore, WorkspaceMutationStoreError,
};
pub use task::{
    WorkspaceObjectiveTaskProjection, WorkspaceObjectiveTaskProjectionWrite,
    WorkspaceTaskAttemptRecord, WorkspaceTaskAuxiliaryWrite, WorkspaceTaskDomainWrite,
    WorkspaceTaskExecutionRecord, WorkspaceTaskMutation, WorkspaceTaskMutationOutcome,
    WorkspaceTaskRecord, WorkspaceTaskScope, WorkspaceTaskStore, WorkspaceTaskStoreError,
};
pub use task_dispatch::{
    WorkspaceTaskDispatchClaim, WorkspaceTaskDispatchFailureOutcome, WorkspaceTaskDispatchWrite,
};
pub use topology::{
    WorkspaceTopologyDomainWrite, WorkspaceTopologyEdgeRecord, WorkspaceTopologyMutation,
    WorkspaceTopologyMutationOutcome, WorkspaceTopologyNodeRecord, WorkspaceTopologyScope,
    WorkspaceTopologyStore, WorkspaceTopologyStoreError,
};
