//! P6 workspace foundation over Python-owned workspace tables.
//!
//! This deliberately covers only precise, database-backed resources:
//! workspaces, workspace chat messages, workspace tasks, topology nodes/edges, and blackboard
//! posts/replies/files plus transactional plan action/outbox rows. Runtime-heavy
//! siblings (execution diagnostics, full leader adjudication, autonomy)
//! remain Python-owned until their full semantics are migrated; accept-review
//! already projects linked attempts to accepted so pending adjudication does not
//! linger after explicit human acceptance.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, MutexGuard};

use async_trait::async_trait;
use axum::{
    body::Body,
    extract::{Multipart, Path, Query, State},
    http::{
        header::{
            ACCEPT_RANGES, CACHE_CONTROL, CONTENT_DISPOSITION, CONTENT_LENGTH, CONTENT_TYPE, ETAG,
            IF_NONE_MATCH,
        },
        HeaderMap, HeaderValue, StatusCode,
    },
    response::Response,
    Extension, Json,
};
use chrono::{DateTime, Duration, Utc};
use serde_json::{json, Map, Value};

#[cfg(test)]
use agistack_adapters_mem::InMemoryObjectStore;
use agistack_adapters_postgres::{
    BlackboardFileRecord, BlackboardOutboxRecord, BlackboardPostRecord, BlackboardReplyRecord,
    PgWorkspaceRepository, TopologyEdgeRecord, TopologyNodeRecord, WorkspaceAccess,
    WorkspaceAgentRecord, WorkspaceMessageRecord, WorkspacePlanBlackboardEntryRecord,
    WorkspacePlanEventRecord, WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord,
    WorkspacePlanRecord, WorkspaceProjectAccess, WorkspaceRecord, WorkspaceTaskRecord,
    WorkspaceTaskSessionAttemptRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;
use agistack_core::ports::ObjectStore;

use crate::auth::Identity;
use crate::AppState;

mod blackboard_service;
mod chat_mentions;
mod files;
mod handlers;
mod plan_actions;
mod plan_snapshot;
mod routes;
mod service;
mod shared;
mod task_service;
mod topology_service;
mod types;
mod views;
mod workspace_chat;
mod workspace_lifecycle;

#[cfg(test)]
use chat_mentions::{
    workspace_agent_mention_outbox_records, workspace_conversation_id,
    WorkspaceAgentMentionOutboxInput, WORKSPACE_AGENT_MENTION_EVENT,
    WORKSPACE_AGENT_MENTION_STATUS,
};
use types::{
    BlackboardFileDownload, BlackboardFileListQuery, BlackboardFileListView, BlackboardFileView,
    BlackboardPostCreatePayload, BlackboardPostListView, BlackboardPostUpdatePayload,
    BlackboardPostView, BlackboardReplyCreatePayload, BlackboardReplyListView,
    BlackboardReplyUpdatePayload, BlackboardReplyView, BlackboardUpload, CopyFilePayload,
    DeleteFileQuery, DeletedView, LimitOffset, MessageListQuery, MessageListView,
    MessageMentionQuery, MessageView, MkdirPayload, RenameOrMoveFilePayload, SendMessagePayload,
    TaskListQuery, TaskTransitionAction, TopologyEdgeCreatePayload, TopologyEdgeUpdatePayload,
    TopologyEdgeView, TopologyNodeCreatePayload, TopologyNodeUpdatePayload, TopologyNodeView,
    WorkspaceApiError, WorkspaceCreatePayload, WorkspaceDeliverySummaryView, WorkspaceListQuery,
    WorkspacePlanActionCapabilityView, WorkspacePlanActionRequest, WorkspacePlanActionResultView,
    WorkspacePlanBlackboardEntryView, WorkspacePlanEventView, WorkspacePlanEvidenceBundleView,
    WorkspacePlanGateStatusView, WorkspacePlanHistoryItemView, WorkspacePlanIterationPhaseView,
    WorkspacePlanIterationSummaryView, WorkspacePlanNodeView, WorkspacePlanOutboxItemView,
    WorkspacePlanPhaseContractView, WorkspacePlanPipelineRunRequest,
    WorkspacePlanRunAssessmentView, WorkspacePlanSnapshotQuery, WorkspacePlanSnapshotView,
    WorkspacePlanView, WorkspaceReplyUpdateInput, WorkspaceTaskCreatePayload,
    WorkspaceTaskUpdatePayload, WorkspaceTaskView, WorkspaceUpdatePayload, WorkspaceView,
};
use views::{
    dedup_truncate, first_metadata_string, int_from_value, int_list_from_value, iso,
    metadata_string_values, object_or_empty, phase_label, string_from_value, string_values,
};

pub(crate) use routes::router;
pub(crate) use service::{SharedWorkspaces, WorkspaceService};
use shared::{
    apply_task_transition, apply_task_update, clamp_limit, compose_workspace_metadata,
    priority_rank, validate_node_type, validate_non_empty, validate_post_status,
    validate_task_status, BLOCKED_FILE_SEGMENTS, MAX_COPY_ENTRIES, MAX_FILE_SIZE,
    OPERATOR_CLEARED_ATTEMPT_KEYS, OPERATOR_CLEARED_RETRY_KEYS,
};

const PIPELINE_RUN_REQUESTED_EVENT: &str = "pipeline_run_requested";
const SUPERVISOR_TICK_EVENT: &str = "supervisor_tick";
const WORKER_LAUNCH_EVENT: &str = "worker_launch";
const HANDOFF_RESUME_EVENT: &str = "handoff_resume";
const STALE_RECOVERY_DISPATCH_STALE_SECONDS: i64 = 180;
const STALE_RECOVERY_RUNNING_STALE_SECONDS: i64 = 300;
const STALE_RECOVERY_RECENT_JOB_SUPPRESSION_SECONDS: i64 = 300;

pub(crate) struct PgWorkspaceService {
    repo: PgWorkspaceRepository,
    object_store: Arc<dyn ObjectStore>,
}

impl PgWorkspaceService {
    pub(crate) fn new(repo: PgWorkspaceRepository, object_store: Arc<dyn ObjectStore>) -> Self {
        Self { repo, object_store }
    }

    async fn ensure_project_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        access: WorkspaceProjectAccess,
    ) -> Result<(), WorkspaceApiError> {
        if self
            .repo
            .user_can_access_project(user_id, tenant_id, project_id, access)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::forbidden())
        }
    }

    async fn ensure_workspace_access(
        &self,
        user_id: &str,
        workspace_id: &str,
        access: WorkspaceAccess,
    ) -> Result<(), WorkspaceApiError> {
        if self
            .repo
            .user_can_access_workspace(user_id, workspace_id, access)
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            Ok(())
        } else {
            Err(WorkspaceApiError::forbidden())
        }
    }

    async fn ensure_workspace_scope_and_access(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        access: WorkspaceAccess,
    ) -> Result<(), WorkspaceApiError> {
        let scoped = self
            .repo
            .workspace_in_scope(workspace_id, tenant_id, project_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if !scoped {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        self.ensure_workspace_access(user_id, workspace_id, access)
            .await
    }

    async fn enqueue_blackboard_event(
        &self,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        event_type: &str,
        payload: Value,
    ) -> Result<(), WorkspaceApiError> {
        self.repo
            .enqueue_blackboard_outbox(BlackboardOutboxRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                tenant_id: tenant_id.to_string(),
                project_id: project_id.to_string(),
                event_type: event_type.to_string(),
                payload_json: payload,
                metadata_json: json!({
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "surface_boundary": "blackboard",
                    "authority_class": "authoritative"
                }),
                correlation_id: None,
            })
            .await
            .map_err(WorkspaceApiError::internal)
    }

    async fn enqueue_chat_event(
        &self,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        event_type: &str,
        payload: Value,
    ) -> Result<(), WorkspaceApiError> {
        self.repo
            .enqueue_blackboard_outbox(BlackboardOutboxRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                tenant_id: tenant_id.to_string(),
                project_id: project_id.to_string(),
                event_type: event_type.to_string(),
                payload_json: payload,
                metadata_json: json!({
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "surface_owner": "workspace-chat",
                    "surface_boundary": "hosted",
                    "authority_class": "non-authoritative",
                    "signal_role": "sensing-capable"
                }),
                correlation_id: None,
            })
            .await
            .map_err(WorkspaceApiError::internal)
    }

    fn object_key(&self, workspace_id: &str, storage_key: &str) -> String {
        files::object_key(workspace_id, storage_key)
    }
}

#[async_trait]
impl WorkspaceService for PgWorkspaceService {
    async fn create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.pg_create_workspace(user_id, tenant_id, project_id, body)
            .await
    }

    async fn list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError> {
        self.pg_list_workspaces(user_id, tenant_id, project_id, query)
            .await
    }

    async fn get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.pg_get_workspace(user_id, tenant_id, project_id, workspace_id)
            .await
    }

    async fn send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError> {
        self.pg_send_message(
            user_id,
            sender_name,
            tenant_id,
            project_id,
            workspace_id,
            body,
        )
        .await
    }

    async fn list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.pg_list_messages(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.pg_list_mentions(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            target_id,
            query,
        )
        .await
    }

    async fn get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError> {
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Read)
            .await?;
        let recover_stale_attempts = query.recover_stale_attempts.unwrap_or(false);
        let mut plans = self
            .repo
            .list_plans(workspace_id, 50)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plans.is_empty() {
            return Ok(plan_snapshot::empty_plan_snapshot(workspace_id));
        }
        let selected_plan_id = if let Some(plan_id) = query.plan_id.as_deref() {
            if !plans.iter().any(|plan| plan.id == plan_id) {
                let plan = self
                    .repo
                    .get_plan(plan_id)
                    .await
                    .map_err(WorkspaceApiError::internal)?
                    .filter(|plan| plan.workspace_id == workspace_id)
                    .ok_or_else(WorkspaceApiError::plan_not_found)?;
                plans.push(plan);
            }
            plan_id.to_string()
        } else {
            plans[0].id.clone()
        };
        let mut plans_with_nodes = Vec::with_capacity(plans.len());
        for plan in plans {
            let nodes = self
                .repo
                .list_plan_nodes(&plan.id)
                .await
                .map_err(WorkspaceApiError::internal)?;
            plans_with_nodes.push((plan, nodes));
        }
        let include_details = query.include_details.unwrap_or(true);
        if recover_stale_attempts
            && include_details
            && plans_with_nodes
                .first()
                .map(|(plan, _)| plan.id.as_str() == selected_plan_id.as_str())
                .unwrap_or(false)
            && self
                .repo
                .user_can_access_workspace(user_id, workspace_id, WorkspaceAccess::Write)
                .await
                .map_err(WorkspaceApiError::internal)?
        {
            if let Some((plan, nodes)) = plans_with_nodes
                .iter()
                .find(|(plan, _)| plan.id == selected_plan_id)
            {
                plan_actions::recover_stale_plan_records_pg(
                    &self.repo,
                    workspace_id,
                    plan,
                    nodes,
                    user_id,
                )
                .await?;
            }
        }
        let (blackboard, outbox, events) = if include_details {
            (
                self.repo
                    .list_plan_blackboard_latest(&selected_plan_id)
                    .await
                    .map_err(WorkspaceApiError::internal)?,
                self.repo
                    .list_plan_outbox(
                        &selected_plan_id,
                        query.outbox_limit.unwrap_or(20).clamp(0, 100),
                    )
                    .await
                    .map_err(WorkspaceApiError::internal)?,
                self.repo
                    .list_plan_events(
                        &selected_plan_id,
                        query.event_limit.unwrap_or(50).clamp(0, 200),
                    )
                    .await
                    .map_err(WorkspaceApiError::internal)?,
            )
        } else {
            (Vec::new(), Vec::new(), Vec::new())
        };
        Ok(plan_snapshot::build_plan_snapshot(
            workspace_id,
            plans_with_nodes,
            &selected_plan_id,
            include_details,
            blackboard,
            outbox,
            events,
        ))
    }

    async fn retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let now = Utc::now();
        let item = self
            .repo
            .retry_plan_outbox_now(
                outbox_id,
                workspace_id,
                Some(user_id),
                body.reason.as_deref(),
                now,
            )
            .await
            .map_err(plan_actions::map_plan_outbox_retry_error)?
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let plan_id = item
            .plan_id
            .clone()
            .ok_or_else(|| WorkspaceApiError::bad_request("Invalid workspace plan request"))?;
        self.repo
            .create_plan_event(plan_actions::plan_retry_event(
                &plan_id,
                workspace_id,
                user_id,
                outbox_id,
                &item.event_type,
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Outbox job queued for retry.".to_string(),
            plan_id,
            node_id: None,
            outbox_id: Some(outbox_id.to_string()),
        })
    }

    async fn recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let recovered = plan_actions::recover_stale_plan_records_pg(
            &self.repo,
            workspace_id,
            &plan,
            &nodes,
            user_id,
        )
        .await?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: if recovered {
                "Workspace plan stale attempt recovery queued."
            } else {
                "No stale workspace plan attempts needed recovery."
            }
            .to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: None,
        })
    }

    async fn request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_pipeline_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let node = plan_actions::pipeline_target_node(&nodes, body.node_id.as_deref())
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested harness-native pipeline".to_string());
        let outbox = self
            .repo
            .enqueue_plan_outbox(plan_actions::plan_action_outbox(
                &plan.id,
                workspace_id,
                PIPELINE_RUN_REQUESTED_EVENT,
                json!({
                    "workspace_id": workspace_id,
                    "plan_id": plan.id,
                    "node_id": node.id,
                    "attempt_id": node.current_attempt_id,
                    "reason": reason
                }),
                json!({"source": "workspace_plan.operator_delivery_run_pipeline"}),
                Utc::now(),
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Harness-native pipeline run requested.".to_string(),
            plan_id: plan.id,
            node_id: Some(node.id),
            outbox_id: Some(outbox.id),
        })
    }

    async fn request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let now = Utc::now();
        let mut workspace = self
            .repo
            .get_workspace(workspace_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        plan_actions::apply_delivery_contract_regeneration(
            &mut workspace.metadata_json,
            user_id,
            body.reason.as_deref(),
            now,
        );
        workspace.updated_at = Some(now);
        self.repo
            .save_workspace(workspace)
            .await
            .map_err(WorkspaceApiError::internal)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested delivery contract regeneration".to_string());
        let outbox = self
            .repo
            .enqueue_plan_outbox(plan_actions::plan_action_outbox(
                &plan.id,
                workspace_id,
                SUPERVISOR_TICK_EVENT,
                json!({
                    "workspace_id": workspace_id,
                    "plan_id": plan.id,
                    "reason": reason
                }),
                json!({"source": "workspace_plan.operator_delivery_regenerate_contract"}),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .create_plan_event(WorkspacePlanEventRecord {
                id: new_id(),
                plan_id: plan.id.clone(),
                workspace_id: workspace_id.to_string(),
                node_id: None,
                attempt_id: None,
                event_type: "delivery_contract_regeneration_requested".to_string(),
                source: "operator".to_string(),
                actor_id: None,
                payload_json: json!({
                    "reason": body.reason,
                    "requested_by": user_id,
                    "requested_at": iso(now)
                }),
                created_at: now,
            })
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Delivery contract regeneration requested.".to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: Some(outbox.id),
        })
    }

    async fn request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_replan_requested",
            reason.as_deref(),
            now,
            plan_actions::done_node_has_recoverable_failure,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        self.repo
            .save_plan_node(updated)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plan_changed {
            self.repo
                .save_plan(plan.clone())
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
                plan_actions::OperatorPlanEventInput {
                    plan_id: &plan.id,
                    workspace_id,
                    node_id,
                    attempt_id,
                    event_type: "operator_replan_requested",
                    actor_id: user_id,
                    payload_json: json!({"reason": reason}),
                    created_at: now,
                },
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .enqueue_plan_outbox(plan_actions::operator_tick_outbox(
                &plan.id,
                workspace_id,
                node_id,
                user_id,
                "operator_replan_requested",
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node sent back for supervisor recovery.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let mut plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        if node.intent != "blocked" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_node_reopened",
            reason.as_deref(),
            now,
            |_| false,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        self.repo
            .save_plan_node(updated)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if plan_changed {
            self.repo
                .save_plan(plan.clone())
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
                plan_actions::OperatorPlanEventInput {
                    plan_id: &plan.id,
                    workspace_id,
                    node_id,
                    attempt_id,
                    event_type: "operator_node_reopened",
                    actor_id: user_id,
                    payload_json: json!({"reason": reason}),
                    created_at: now,
                },
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        self.repo
            .enqueue_plan_outbox(plan_actions::operator_tick_outbox(
                &plan.id,
                workspace_id,
                node_id,
                user_id,
                "operator_node_reopened",
                body.reason.as_deref(),
                now,
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Blocked plan node reopened.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.ensure_workspace_access(user_id, workspace_id, WorkspaceAccess::Write)
            .await?;
        let plan = self
            .repo
            .list_plans(workspace_id, 1)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .next()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = self
            .repo
            .list_plan_nodes(&plan.id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .into_iter()
            .find(|node| node.id == node_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let task_id = node.workspace_task_id.clone();
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "Accepted after operator review.".to_string());
        let evidence_refs = plan_actions::trimmed_evidence_refs(&body.evidence_refs);
        let now = Utc::now();
        let mut updated = plan_actions::accept_node_for_operator_review(
            node,
            user_id,
            &reason,
            evidence_refs.clone(),
            now,
        )?;
        let accepted_attempt = if let Some(attempt_id) = attempt_id.as_deref() {
            self.repo
                .finish_task_session_attempt(
                    attempt_id,
                    "accepted",
                    Some(&reason),
                    Some("operator_review_accepted"),
                    now,
                )
                .await
                .map_err(WorkspaceApiError::internal)?
        } else {
            None
        };
        if let Some(attempt) = accepted_attempt.as_ref() {
            plan_actions::apply_human_review_acceptance_to_node_attempt(&mut updated, attempt);
        }
        self.repo
            .save_plan_node(updated.clone())
            .await
            .map_err(WorkspaceApiError::internal)?;
        if let Some(task_id) = task_id {
            let mut task = self
                .repo
                .get_task(workspace_id, &task_id)
                .await
                .map_err(WorkspaceApiError::internal)?
                .ok_or_else(WorkspaceApiError::task_not_found)?;
            plan_actions::apply_human_review_acceptance_to_task(
                &mut task,
                &reason,
                &updated.metadata_json,
                accepted_attempt.as_ref(),
                now,
            );
            self.repo
                .save_task(task)
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        self.repo
            .create_plan_event(plan_actions::operator_plan_event(
                plan_actions::OperatorPlanEventInput {
                    plan_id: &plan.id,
                    workspace_id,
                    node_id,
                    attempt_id,
                    event_type: "operator_review_accepted",
                    actor_id: user_id,
                    payload_json: json!({"reason": reason, "evidence_refs": evidence_refs}),
                    created_at: now,
                },
            ))
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node accepted after human review.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.pg_update_workspace(user_id, tenant_id, project_id, workspace_id, body)
            .await
    }

    async fn delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_workspace(user_id, tenant_id, project_id, workspace_id)
            .await
    }

    async fn create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_create_task(user_id, workspace_id, body).await
    }

    async fn list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError> {
        self.pg_list_tasks(user_id, workspace_id, query).await
    }

    async fn get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_get_task(user_id, workspace_id, task_id).await
    }

    async fn update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_update_task(user_id, workspace_id, task_id, body)
            .await
    }

    async fn delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_task(user_id, workspace_id, task_id).await
    }

    async fn transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.pg_transition_task(user_id, workspace_id, task_id, action)
            .await
    }

    async fn create_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyNodeCreatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.pg_create_node(user_id, workspace_id, body).await
    }

    async fn list_nodes(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyNodeView>, WorkspaceApiError> {
        self.pg_list_nodes(user_id, workspace_id, query).await
    }

    async fn get_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.pg_get_node(user_id, workspace_id, node_id).await
    }

    async fn update_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: TopologyNodeUpdatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.pg_update_node(user_id, workspace_id, node_id, body)
            .await
    }

    async fn delete_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_node(user_id, workspace_id, node_id).await
    }

    async fn create_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyEdgeCreatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.pg_create_edge(user_id, workspace_id, body).await
    }

    async fn list_edges(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyEdgeView>, WorkspaceApiError> {
        self.pg_list_edges(user_id, workspace_id, query).await
    }

    async fn get_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.pg_get_edge(user_id, workspace_id, edge_id).await
    }

    async fn update_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
        body: TopologyEdgeUpdatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.pg_update_edge(user_id, workspace_id, edge_id, body)
            .await
    }

    async fn delete_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.pg_delete_edge(user_id, workspace_id, edge_id).await
    }

    async fn create_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: BlackboardPostCreatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.pg_create_post(user_id, tenant_id, project_id, workspace_id, body)
            .await
    }

    async fn list_posts(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardPostListView, WorkspaceApiError> {
        self.pg_list_posts(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn get_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.pg_get_post(user_id, tenant_id, project_id, workspace_id, post_id)
            .await
    }

    async fn update_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardPostUpdatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.pg_update_post(user_id, tenant_id, project_id, workspace_id, post_id, body)
            .await
    }

    async fn delete_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.pg_delete_post(user_id, tenant_id, project_id, workspace_id, post_id)
            .await
    }

    async fn create_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardReplyCreatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.pg_create_reply(user_id, tenant_id, project_id, workspace_id, post_id, body)
            .await
    }

    async fn list_replies(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardReplyListView, WorkspaceApiError> {
        self.pg_list_replies(user_id, tenant_id, project_id, workspace_id, post_id, query)
            .await
    }

    async fn update_reply(
        &self,
        input: WorkspaceReplyUpdateInput<'_>,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.pg_update_reply(input).await
    }

    async fn delete_reply(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.pg_delete_reply(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            post_id,
            reply_id,
        )
        .await
    }

    async fn list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let parent_path = files::validate_file_path(query.parent_path.as_deref().unwrap_or("/"))?;
        let files = self
            .repo
            .list_files(workspace_id, &parent_path)
            .await
            .map_err(WorkspaceApiError::internal)?;
        Ok(BlackboardFileListView {
            items: files.into_iter().map(BlackboardFileView::from).collect(),
        })
    }

    async fn create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let parent_path = files::validate_file_path(&body.parent_path)?;
        let name = files::validate_filename(&body.name)?;
        if parent_path != "/" {
            files::require_directory_exists_pg(&self.repo, workspace_id, &parent_path).await?;
        }
        files::ensure_file_name_available_pg(&self.repo, workspace_id, &parent_path, &name).await?;
        let file = self
            .repo
            .create_file(BlackboardFileRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                parent_path,
                name,
                is_directory: true,
                file_size: 0,
                content_type: String::new(),
                storage_key: String::new(),
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            })
            .await
            .map_err(files::map_file_storage_error)?;
        let view = BlackboardFileView::from(file);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_created",
            files::file_event_payload(workspace_id, &view),
        )
        .await?;
        Ok(view)
    }

    async fn upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        if upload.bytes.len() > MAX_FILE_SIZE {
            return Err(WorkspaceApiError::bad_request(format!(
                "File exceeds maximum size of {MAX_FILE_SIZE} bytes"
            )));
        }
        let parent_path = files::validate_file_path(&upload.parent_path)?;
        if parent_path != "/" {
            files::require_directory_exists_pg(&self.repo, workspace_id, &parent_path).await?;
        }
        let filename = files::validate_filename(&upload.filename)?;
        files::ensure_file_name_available_pg(&self.repo, workspace_id, &parent_path, &filename)
            .await?;
        let file_id = new_id();
        let content_type = upload
            .content_type
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| files::guess_content_type(&filename));
        let file_size = upload.bytes.len().min(i32::MAX as usize) as i32;
        let storage_key = format!("{file_id}/{filename}");
        self.object_store
            .put(
                &self.object_key(workspace_id, &storage_key),
                upload.bytes,
                Some(&content_type),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        let file = self
            .repo
            .create_file(BlackboardFileRecord {
                id: file_id,
                workspace_id: workspace_id.to_string(),
                parent_path,
                name: filename,
                is_directory: false,
                file_size,
                content_type,
                storage_key,
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            })
            .await
            .map_err(files::map_file_storage_error)?;
        let mut file = file;
        if let Some(meta) = self
            .object_store
            .stat(&self.object_key(workspace_id, &file.storage_key))
            .await
            .map_err(WorkspaceApiError::internal)?
        {
            file.file_size = meta.size.min(i32::MAX as u64) as i32;
            if let Some(content_type) = meta.content_type {
                file.content_type = content_type;
            }
            file = self
                .repo
                .save_file(file)
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        let view = BlackboardFileView::from(file);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_created",
            files::file_event_payload(workspace_id, &view),
        )
        .await?;
        Ok(view)
    }

    async fn download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Read,
        )
        .await?;
        let file = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if file.is_directory {
            return Err(WorkspaceApiError::bad_request(
                "Cannot read directory content",
            ));
        }
        let bytes = self
            .object_store
            .get(&self.object_key(workspace_id, &file.storage_key))
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(|| {
                WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found")
            })?;
        Ok(BlackboardFileDownload {
            filename: file.name,
            content_type: if file.content_type.is_empty() {
                "application/octet-stream".to_string()
            } else {
                file.content_type
            },
            file_size: file.file_size,
            etag: file
                .checksum_sha256
                .map(|checksum| format!("\"{checksum}\""))
                .unwrap_or_else(|| format!("W/\"sz-{}-id-{}\"", file.file_size, file.id)),
            bytes,
        })
    }

    async fn patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        if body.name.is_none() && body.parent_path.is_none() {
            return Err(WorkspaceApiError::bad_request(
                "Provide at least one of 'name' or 'parent_path'",
            ));
        }
        let mut file = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if let Some(parent_path) = body.parent_path {
            let target_parent = files::validate_file_path(&parent_path)?;
            if target_parent != file.parent_path {
                if target_parent != "/" {
                    files::require_directory_exists_pg(&self.repo, workspace_id, &target_parent)
                        .await?;
                }
                if file.is_directory {
                    let own_prefix = files::join_child_path(&file.parent_path, &file.name)?;
                    if target_parent == own_prefix || target_parent.starts_with(&own_prefix) {
                        return Err(WorkspaceApiError::bad_request(
                            "Cannot move a directory into itself",
                        ));
                    }
                    let new_prefix = files::join_child_path(&target_parent, &file.name)?;
                    self.repo
                        .bulk_update_file_parent_path(workspace_id, &own_prefix, &new_prefix)
                        .await
                        .map_err(WorkspaceApiError::internal)?;
                }
                files::ensure_file_name_available_pg(
                    &self.repo,
                    workspace_id,
                    &target_parent,
                    &file.name,
                )
                .await?;
                file.parent_path = target_parent;
            }
        }
        if let Some(name) = body.name {
            let safe_name = files::validate_filename(&name)?;
            if safe_name != file.name {
                files::ensure_file_name_available_pg(
                    &self.repo,
                    workspace_id,
                    &file.parent_path,
                    &safe_name,
                )
                .await?;
                if file.is_directory {
                    let old_prefix = files::join_child_path(&file.parent_path, &file.name)?;
                    let new_prefix = files::join_child_path(&file.parent_path, &safe_name)?;
                    self.repo
                        .bulk_update_file_parent_path(workspace_id, &old_prefix, &new_prefix)
                        .await
                        .map_err(WorkspaceApiError::internal)?;
                }
                file.name = safe_name;
            }
        }
        let view = self
            .repo
            .save_file(file)
            .await
            .map(BlackboardFileView::from)
            .map_err(WorkspaceApiError::internal)?;
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_updated",
            json!({ "file": view, "file_id": view.id }),
        )
        .await?;
        Ok(view)
    }

    async fn copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let source = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        let target_parent = files::validate_file_path(&body.target_parent_path)?;
        if target_parent != "/" {
            files::require_directory_exists_pg(&self.repo, workspace_id, &target_parent).await?;
        }
        let copy_name = files::validate_filename(body.name.as_deref().unwrap_or(&source.name))?;
        files::ensure_file_name_available_pg(&self.repo, workspace_id, &target_parent, &copy_name)
            .await?;
        let copied = if source.is_directory {
            files::copy_directory_pg(
                &self.repo,
                Arc::clone(&self.object_store),
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        } else {
            files::copy_single_file_pg(
                &self.repo,
                Arc::clone(&self.object_store),
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        };
        let view = BlackboardFileView::from(copied);
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            "blackboard_file_created",
            files::file_event_payload(workspace_id, &view),
        )
        .await?;
        Ok(view)
    }

    async fn delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.ensure_workspace_scope_and_access(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            WorkspaceAccess::Write,
        )
        .await?;
        let file = self
            .repo
            .get_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        let was_directory = file.is_directory;
        if file.is_directory {
            let child_path = files::join_child_path(&file.parent_path, &file.name)?;
            let children = self
                .repo
                .list_files(workspace_id, &child_path)
                .await
                .map_err(WorkspaceApiError::internal)?;
            if !children.is_empty() && !query.recursive {
                return Err(WorkspaceApiError::bad_request("Directory is not empty"));
            }
            if query.recursive {
                let descendants = self
                    .repo
                    .find_file_descendants(workspace_id, &child_path)
                    .await
                    .map_err(WorkspaceApiError::internal)?;
                for descendant in descendants.iter().rev() {
                    if !descendant.is_directory && !descendant.storage_key.is_empty() {
                        self.object_store
                            .delete(&self.object_key(workspace_id, &descendant.storage_key))
                            .await
                            .map_err(WorkspaceApiError::internal)?;
                    }
                    self.repo
                        .delete_file(workspace_id, &descendant.id)
                        .await
                        .map_err(WorkspaceApiError::internal)?;
                }
            }
        } else if !file.storage_key.is_empty() {
            self.object_store
                .delete(&self.object_key(workspace_id, &file.storage_key))
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        let deleted = self
            .repo
            .delete_file(workspace_id, file_id)
            .await
            .map_err(WorkspaceApiError::internal)?;
        if !deleted {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        self.enqueue_blackboard_event(
            tenant_id,
            project_id,
            workspace_id,
            if was_directory {
                "blackboard_directory_deleted"
            } else {
                "blackboard_file_deleted"
            },
            json!({
                "workspace_id": workspace_id,
                "file_id": file_id,
                "deleted": deleted,
                "recursive": query.recursive,
                "is_directory": was_directory
            }),
        )
        .await?;
        Ok(DeletedView { deleted })
    }
}

#[derive(Default)]
struct DevWorkspaceState {
    workspaces: HashMap<String, WorkspaceRecord>,
    workspace_agents: Vec<WorkspaceAgentRecord>,
    tasks: HashMap<String, WorkspaceTaskRecord>,
    messages: HashMap<String, WorkspaceMessageRecord>,
    task_attempts: HashMap<String, WorkspaceTaskSessionAttemptRecord>,
    nodes: HashMap<String, TopologyNodeRecord>,
    edges: HashMap<String, TopologyEdgeRecord>,
    posts: HashMap<String, BlackboardPostRecord>,
    replies: HashMap<String, BlackboardReplyRecord>,
    files: HashMap<String, BlackboardFileRecord>,
    outbox: Vec<BlackboardOutboxRecord>,
    plans: HashMap<String, WorkspacePlanRecord>,
    plan_nodes: HashMap<String, WorkspacePlanNodeRecord>,
    plan_blackboard: Vec<WorkspacePlanBlackboardEntryRecord>,
    plan_events: Vec<WorkspacePlanEventRecord>,
    plan_outbox: Vec<WorkspacePlanOutboxRecord>,
}

pub(crate) struct DevWorkspaceService {
    dev_user_id: String,
    state: Mutex<DevWorkspaceState>,
    object_store: Arc<dyn ObjectStore>,
}

impl DevWorkspaceService {
    #[cfg(test)]
    pub(crate) fn new(dev_user_id: impl Into<String>) -> Self {
        Self::with_object_store(dev_user_id, Arc::new(InMemoryObjectStore::new()))
    }

    pub(crate) fn with_object_store(
        dev_user_id: impl Into<String>,
        object_store: Arc<dyn ObjectStore>,
    ) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            state: Mutex::new(DevWorkspaceState::default()),
            object_store,
        }
    }

    fn require_dev_user(&self, user_id: &str) -> Result<(), WorkspaceApiError> {
        if user_id == self.dev_user_id {
            Ok(())
        } else {
            Err(WorkspaceApiError::forbidden())
        }
    }

    fn lock_state(&self) -> Result<MutexGuard<'_, DevWorkspaceState>, WorkspaceApiError> {
        self.state
            .lock()
            .map_err(|_| WorkspaceApiError::internal("workspace dev state unavailable"))
    }

    fn workspace_matches(
        &self,
        workspace: &WorkspaceRecord,
        tenant_id: &str,
        project_id: &str,
    ) -> bool {
        workspace.tenant_id == tenant_id && workspace.project_id == project_id
    }

    fn object_key(&self, workspace_id: &str, storage_key: &str) -> String {
        files::object_key(workspace_id, storage_key)
    }
}

#[async_trait]
impl WorkspaceService for DevWorkspaceService {
    async fn create_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        body: WorkspaceCreatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.dev_create_workspace(user_id, tenant_id, project_id, body)
            .await
    }

    async fn list_workspaces(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        query: WorkspaceListQuery,
    ) -> Result<Vec<WorkspaceView>, WorkspaceApiError> {
        self.dev_list_workspaces(user_id, tenant_id, project_id, query)
            .await
    }

    async fn get_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.dev_get_workspace(user_id, tenant_id, project_id, workspace_id)
            .await
    }

    async fn send_message(
        &self,
        user_id: &str,
        sender_name: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: SendMessagePayload,
    ) -> Result<MessageView, WorkspaceApiError> {
        self.dev_send_message(
            user_id,
            sender_name,
            tenant_id,
            project_id,
            workspace_id,
            body,
        )
        .await
    }

    async fn list_messages(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: MessageListQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.dev_list_messages(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn list_mentions(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        target_id: &str,
        query: MessageMentionQuery,
    ) -> Result<MessageListView, WorkspaceApiError> {
        self.dev_list_mentions(
            user_id,
            tenant_id,
            project_id,
            workspace_id,
            target_id,
            query,
        )
        .await
    }

    async fn get_plan_snapshot(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshotView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let recover_stale_attempts = query.recover_stale_attempts.unwrap_or(false);
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut plans: Vec<_> = state
            .plans
            .values()
            .filter(|plan| plan.workspace_id == workspace_id)
            .cloned()
            .collect();
        plans.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(a.id.cmp(&b.id)));
        if plans.is_empty() {
            return Ok(plan_snapshot::empty_plan_snapshot(workspace_id));
        }
        let selected_plan_id = if let Some(plan_id) = query.plan_id.as_deref() {
            if !plans.iter().any(|plan| plan.id == plan_id) {
                return Err(WorkspaceApiError::plan_not_found());
            }
            plan_id.to_string()
        } else {
            plans[0].id.clone()
        };
        let include_details = query.include_details.unwrap_or(true);
        if recover_stale_attempts
            && include_details
            && plans
                .first()
                .map(|plan| plan.id.as_str() == selected_plan_id.as_str())
                .unwrap_or(false)
        {
            if let Some(plan) = plans
                .iter()
                .find(|plan| plan.id == selected_plan_id)
                .cloned()
            {
                let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
                plan_actions::recover_stale_plan_records_dev(
                    &mut state,
                    workspace_id,
                    &plan,
                    &nodes,
                    user_id,
                    Utc::now(),
                );
            }
        }
        let plans_with_nodes: Vec<_> = plans
            .into_iter()
            .map(|plan| {
                let mut nodes: Vec<_> = state
                    .plan_nodes
                    .values()
                    .filter(|node| node.plan_id == plan.id)
                    .cloned()
                    .collect();
                nodes.sort_by(|a, b| {
                    a.kind
                        .cmp(&b.kind)
                        .then(a.priority.cmp(&b.priority))
                        .then(a.id.cmp(&b.id))
                });
                (plan, nodes)
            })
            .collect();
        let (blackboard, outbox, events) = if include_details {
            let mut latest = HashMap::<String, WorkspacePlanBlackboardEntryRecord>::new();
            for entry in state
                .plan_blackboard
                .iter()
                .filter(|entry| entry.plan_id == selected_plan_id.as_str())
            {
                let replace = latest
                    .get(&entry.key)
                    .map(|current| {
                        entry.version > current.version
                            || (entry.version == current.version
                                && entry.created_at > current.created_at)
                    })
                    .unwrap_or(true);
                if replace {
                    latest.insert(entry.key.clone(), entry.clone());
                }
            }
            let mut blackboard: Vec<_> = latest.into_values().collect();
            blackboard.sort_by(|a, b| a.key.cmp(&b.key));
            let outbox_limit = query.outbox_limit.unwrap_or(20).clamp(0, 100) as usize;
            let mut outbox: Vec<_> = state
                .plan_outbox
                .iter()
                .filter(|item| item.plan_id.as_deref() == Some(selected_plan_id.as_str()))
                .cloned()
                .collect();
            outbox.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(b.id.cmp(&a.id)));
            outbox.truncate(outbox_limit);
            let event_limit = query.event_limit.unwrap_or(50).clamp(0, 200) as usize;
            let mut events: Vec<_> = state
                .plan_events
                .iter()
                .filter(|event| event.plan_id == selected_plan_id.as_str())
                .cloned()
                .collect();
            events.sort_by(|a, b| b.created_at.cmp(&a.created_at).then(b.id.cmp(&a.id)));
            events.truncate(event_limit);
            (blackboard, outbox, events)
        } else {
            (Vec::new(), Vec::new(), Vec::new())
        };
        Ok(plan_snapshot::build_plan_snapshot(
            workspace_id,
            plans_with_nodes,
            &selected_plan_id,
            include_details,
            blackboard,
            outbox,
            events,
        ))
    }

    async fn retry_plan_outbox(
        &self,
        user_id: &str,
        workspace_id: &str,
        outbox_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let now = Utc::now();
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let item = state
            .plan_outbox
            .iter_mut()
            .find(|item| item.id == outbox_id && item.workspace_id == workspace_id)
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let delayed_pending = item.status == "pending"
            && item
                .next_attempt_at
                .map(|next_attempt_at| next_attempt_at > now)
                .unwrap_or(false);
        if !matches!(item.status.as_str(), "failed" | "dead_letter") && !delayed_pending {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let plan_id = item
            .plan_id
            .clone()
            .ok_or_else(|| WorkspaceApiError::bad_request("Invalid workspace plan request"))?;
        let previous_status = item.status.clone();
        let previous_error = item.last_error.clone();
        let previous_next_attempt_at = item.next_attempt_at.map(iso);
        let previous_event_type = item.event_type.clone();
        item.status = "pending".to_string();
        if previous_status == "dead_letter" {
            item.attempt_count = 0;
        }
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        item.processed_at = None;
        item.updated_at = Some(now);
        let mut metadata = match item.metadata_json.clone() {
            Value::Object(map) => map,
            _ => Map::new(),
        };
        metadata.insert(
            "operator_retry".to_string(),
            json!({
                "actor_id": user_id,
                "reason": body.reason.clone(),
                "retried_at": iso(now),
                "previous_status": previous_status,
                "previous_error": previous_error,
                "previous_next_attempt_at": previous_next_attempt_at
            }),
        );
        item.metadata_json = Value::Object(metadata);
        state.plan_events.push(plan_actions::plan_retry_event(
            &plan_id,
            workspace_id,
            user_id,
            outbox_id,
            &previous_event_type,
            body.reason.as_deref(),
            now,
        ));
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Outbox job queued for retry.".to_string(),
            plan_id,
            node_id: None,
            outbox_id: Some(outbox_id.to_string()),
        })
    }

    async fn recover_stale_attempts(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
        let recovered = plan_actions::recover_stale_plan_records_dev(
            &mut state,
            workspace_id,
            &plan,
            &nodes,
            user_id,
            Utc::now(),
        );
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: if recovered {
                "Workspace plan stale attempt recovery queued."
            } else {
                "No stale workspace plan attempts needed recovery."
            }
            .to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: None,
        })
    }

    async fn request_delivery_pipeline_run(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanPipelineRunRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_pipeline_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        if !state.workspaces.contains_key(workspace_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let nodes = plan_actions::plan_nodes_for_dev(&state, &plan.id);
        let node = plan_actions::pipeline_target_node(&nodes, body.node_id.as_deref())
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested harness-native pipeline".to_string());
        let outbox = plan_actions::plan_action_outbox(
            &plan.id,
            workspace_id,
            PIPELINE_RUN_REQUESTED_EVENT,
            json!({
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "node_id": node.id,
                "attempt_id": node.current_attempt_id,
                "reason": reason
            }),
            json!({"source": "workspace_plan.operator_delivery_run_pipeline"}),
            Utc::now(),
        );
        let outbox_id = outbox.id.clone();
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Harness-native pipeline run requested.".to_string(),
            plan_id: plan.id,
            node_id: Some(node.id),
            outbox_id: Some(outbox_id),
        })
    }

    async fn request_delivery_contract_regeneration(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let now = Utc::now();
        let workspace = state
            .workspaces
            .get_mut(workspace_id)
            .ok_or_else(WorkspaceApiError::workspace_not_found)?;
        plan_actions::apply_delivery_contract_regeneration(
            &mut workspace.metadata_json,
            user_id,
            body.reason.as_deref(),
            now,
        );
        workspace.updated_at = Some(now);
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "operator requested delivery contract regeneration".to_string());
        let outbox = plan_actions::plan_action_outbox(
            &plan.id,
            workspace_id,
            SUPERVISOR_TICK_EVENT,
            json!({
                "workspace_id": workspace_id,
                "plan_id": plan.id,
                "reason": reason
            }),
            json!({"source": "workspace_plan.operator_delivery_regenerate_contract"}),
            now,
        );
        let outbox_id = outbox.id.clone();
        state.plan_outbox.push(outbox);
        state.plan_events.push(WorkspacePlanEventRecord {
            id: new_id(),
            plan_id: plan.id.clone(),
            workspace_id: workspace_id.to_string(),
            node_id: None,
            attempt_id: None,
            event_type: "delivery_contract_regeneration_requested".to_string(),
            source: "operator".to_string(),
            actor_id: None,
            payload_json: json!({
                "reason": body.reason,
                "requested_by": user_id,
                "requested_at": iso(now)
            }),
            created_at: now,
        });
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Delivery contract regeneration requested.".to_string(),
            plan_id: plan.id,
            node_id: None,
            outbox_id: Some(outbox_id),
        })
    }

    async fn request_plan_node_replan(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let mut plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_replan_requested",
            reason.as_deref(),
            now,
            plan_actions::done_node_has_recoverable_failure,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        state.plan_nodes.insert(node_id.to_string(), updated);
        if plan_changed {
            state.plans.insert(plan.id.clone(), plan.clone());
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_replan_requested",
                actor_id: user_id,
                payload_json: json!({"reason": reason}),
                created_at: now,
            },
        ));
        let outbox = plan_actions::operator_tick_outbox(
            &plan.id,
            workspace_id,
            node_id,
            user_id,
            "operator_replan_requested",
            body.reason.as_deref(),
            now,
        );
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node sent back for supervisor recovery.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn reopen_plan_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let mut plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        if node.intent != "blocked" {
            return Err(WorkspaceApiError::bad_request(
                "Invalid workspace plan request",
            ));
        }
        let attempt_id = node.current_attempt_id.clone();
        let reason = body.reason.clone();
        let now = Utc::now();
        let updated = plan_actions::reset_node_for_operator(
            node,
            user_id,
            "operator_node_reopened",
            reason.as_deref(),
            now,
            |_| false,
        )?;
        let plan_changed = plan_actions::reactivate_plan_for_operator_recovery(&mut plan, now);
        state.plan_nodes.insert(node_id.to_string(), updated);
        if plan_changed {
            state.plans.insert(plan.id.clone(), plan.clone());
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_node_reopened",
                actor_id: user_id,
                payload_json: json!({"reason": reason}),
                created_at: now,
            },
        ));
        let outbox = plan_actions::operator_tick_outbox(
            &plan.id,
            workspace_id,
            node_id,
            user_id,
            "operator_node_reopened",
            body.reason.as_deref(),
            now,
        );
        state.plan_outbox.push(outbox);
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Blocked plan node reopened.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn accept_plan_node_review(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: WorkspacePlanActionRequest,
    ) -> Result<WorkspacePlanActionResultView, WorkspaceApiError> {
        plan_actions::validate_plan_action_request(&body)?;
        self.require_dev_user(user_id)?;
        let mut state = self.lock_state()?;
        let plan = plan_actions::latest_plan_for_workspace(&state, workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let node = state
            .plan_nodes
            .get(node_id)
            .filter(|node| node.plan_id == plan.id)
            .cloned()
            .ok_or_else(WorkspaceApiError::plan_not_found)?;
        let attempt_id = node.current_attempt_id.clone();
        let task_id = node.workspace_task_id.clone();
        let reason = body
            .reason
            .clone()
            .unwrap_or_else(|| "Accepted after operator review.".to_string());
        let evidence_refs = plan_actions::trimmed_evidence_refs(&body.evidence_refs);
        let now = Utc::now();
        let mut updated = plan_actions::accept_node_for_operator_review(
            node,
            user_id,
            &reason,
            evidence_refs.clone(),
            now,
        )?;
        let accepted_attempt = if let Some(attempt_id) = attempt_id.as_deref() {
            state.task_attempts.get_mut(attempt_id).map(|attempt| {
                attempt.status = "accepted".to_string();
                attempt.leader_feedback = Some(reason.clone());
                attempt.adjudication_reason = Some("operator_review_accepted".to_string());
                attempt.completed_at = Some(now);
                attempt.updated_at = Some(now);
                attempt.clone()
            })
        } else {
            None
        };
        if let Some(attempt) = accepted_attempt.as_ref() {
            plan_actions::apply_human_review_acceptance_to_node_attempt(&mut updated, attempt);
        }
        state
            .plan_nodes
            .insert(node_id.to_string(), updated.clone());
        if let Some(task_id) = task_id {
            let task = state
                .tasks
                .get_mut(&task_id)
                .filter(|task| task.workspace_id == workspace_id)
                .ok_or_else(WorkspaceApiError::task_not_found)?;
            plan_actions::apply_human_review_acceptance_to_task(
                task,
                &reason,
                &updated.metadata_json,
                accepted_attempt.as_ref(),
                now,
            );
        }
        state.plan_events.push(plan_actions::operator_plan_event(
            plan_actions::OperatorPlanEventInput {
                plan_id: &plan.id,
                workspace_id,
                node_id,
                attempt_id,
                event_type: "operator_review_accepted",
                actor_id: user_id,
                payload_json: json!({"reason": reason, "evidence_refs": evidence_refs}),
                created_at: now,
            },
        ));
        Ok(WorkspacePlanActionResultView {
            ok: true,
            message: "Plan node accepted after human review.".to_string(),
            plan_id: plan.id,
            node_id: Some(node_id.to_string()),
            outbox_id: None,
        })
    }

    async fn update_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: WorkspaceUpdatePayload,
    ) -> Result<WorkspaceView, WorkspaceApiError> {
        self.dev_update_workspace(user_id, tenant_id, project_id, workspace_id, body)
            .await
    }

    async fn delete_workspace(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.dev_delete_workspace(user_id, tenant_id, project_id, workspace_id)
            .await
    }

    async fn create_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: WorkspaceTaskCreatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.dev_create_task(user_id, workspace_id, body).await
    }

    async fn list_tasks(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: TaskListQuery,
    ) -> Result<Vec<WorkspaceTaskView>, WorkspaceApiError> {
        self.dev_list_tasks(user_id, workspace_id, query).await
    }

    async fn get_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.dev_get_task(user_id, workspace_id, task_id).await
    }

    async fn update_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        body: WorkspaceTaskUpdatePayload,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.dev_update_task(user_id, workspace_id, task_id, body)
            .await
    }

    async fn delete_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.dev_delete_task(user_id, workspace_id, task_id).await
    }

    async fn transition_task(
        &self,
        user_id: &str,
        workspace_id: &str,
        task_id: &str,
        action: TaskTransitionAction,
    ) -> Result<WorkspaceTaskView, WorkspaceApiError> {
        self.dev_transition_task(user_id, workspace_id, task_id, action)
            .await
    }

    async fn create_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyNodeCreatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.dev_create_node(user_id, workspace_id, body).await
    }

    async fn list_nodes(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyNodeView>, WorkspaceApiError> {
        self.dev_list_nodes(user_id, workspace_id, query).await
    }

    async fn get_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.dev_get_node(user_id, workspace_id, node_id).await
    }

    async fn update_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
        body: TopologyNodeUpdatePayload,
    ) -> Result<TopologyNodeView, WorkspaceApiError> {
        self.dev_update_node(user_id, workspace_id, node_id, body)
            .await
    }

    async fn delete_node(
        &self,
        user_id: &str,
        workspace_id: &str,
        node_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.dev_delete_node(user_id, workspace_id, node_id).await
    }

    async fn create_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        body: TopologyEdgeCreatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.dev_create_edge(user_id, workspace_id, body).await
    }

    async fn list_edges(
        &self,
        user_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<Vec<TopologyEdgeView>, WorkspaceApiError> {
        self.dev_list_edges(user_id, workspace_id, query).await
    }

    async fn get_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.dev_get_edge(user_id, workspace_id, edge_id).await
    }

    async fn update_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
        body: TopologyEdgeUpdatePayload,
    ) -> Result<TopologyEdgeView, WorkspaceApiError> {
        self.dev_update_edge(user_id, workspace_id, edge_id, body)
            .await
    }

    async fn delete_edge(
        &self,
        user_id: &str,
        workspace_id: &str,
        edge_id: &str,
    ) -> Result<(), WorkspaceApiError> {
        self.dev_delete_edge(user_id, workspace_id, edge_id).await
    }

    async fn create_post(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: BlackboardPostCreatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.dev_create_post(user_id, tenant_id, project_id, workspace_id, body)
            .await
    }

    async fn list_posts(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardPostListView, WorkspaceApiError> {
        self.dev_list_posts(user_id, tenant_id, project_id, workspace_id, query)
            .await
    }

    async fn get_post(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.dev_get_post(user_id, _tenant_id, _project_id, workspace_id, post_id)
            .await
    }

    async fn update_post(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardPostUpdatePayload,
    ) -> Result<BlackboardPostView, WorkspaceApiError> {
        self.dev_update_post(
            user_id,
            _tenant_id,
            _project_id,
            workspace_id,
            post_id,
            body,
        )
        .await
    }

    async fn delete_post(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.dev_delete_post(user_id, _tenant_id, _project_id, workspace_id, post_id)
            .await
    }

    async fn create_reply(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        body: BlackboardReplyCreatePayload,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.dev_create_reply(
            user_id,
            _tenant_id,
            _project_id,
            workspace_id,
            post_id,
            body,
        )
        .await
    }

    async fn list_replies(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        query: LimitOffset,
    ) -> Result<BlackboardReplyListView, WorkspaceApiError> {
        self.dev_list_replies(
            user_id,
            _tenant_id,
            _project_id,
            workspace_id,
            post_id,
            query,
        )
        .await
    }

    async fn update_reply(
        &self,
        input: WorkspaceReplyUpdateInput<'_>,
    ) -> Result<BlackboardReplyView, WorkspaceApiError> {
        self.dev_update_reply(input).await
    }

    async fn delete_reply(
        &self,
        user_id: &str,
        _tenant_id: &str,
        _project_id: &str,
        workspace_id: &str,
        post_id: &str,
        reply_id: &str,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.dev_delete_reply(
            user_id,
            _tenant_id,
            _project_id,
            workspace_id,
            post_id,
            reply_id,
        )
        .await
    }

    async fn list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let parent_path = files::validate_file_path(query.parent_path.as_deref().unwrap_or("/"))?;
        let state = self.lock_state()?;
        if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut files: Vec<_> = state
            .files
            .values()
            .filter(|file| file.workspace_id == workspace_id && file.parent_path == parent_path)
            .cloned()
            .collect();
        files::sort_files(&mut files);
        Ok(BlackboardFileListView {
            items: files.into_iter().map(BlackboardFileView::from).collect(),
        })
    }

    async fn create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let parent_path = files::validate_file_path(&body.parent_path)?;
        let name = files::validate_filename(&body.name)?;
        let mut state = self.lock_state()?;
        if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        if parent_path != "/" {
            files::require_directory_exists_dev(&state, workspace_id, &parent_path)?;
        }
        files::ensure_file_name_available_dev(&state, workspace_id, &parent_path, &name)?;
        let file = BlackboardFileRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            parent_path,
            name,
            is_directory: true,
            file_size: 0,
            content_type: String::new(),
            storage_key: String::new(),
            uploader_type: "user".to_string(),
            uploader_id: user_id.to_string(),
            uploader_name: user_id.to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at: Utc::now(),
        };
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: files::file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if upload.bytes.len() > MAX_FILE_SIZE {
            return Err(WorkspaceApiError::bad_request(format!(
                "File exceeds maximum size of {MAX_FILE_SIZE} bytes"
            )));
        }
        let parent_path = files::validate_file_path(&upload.parent_path)?;
        let filename = files::validate_filename(&upload.filename)?;
        {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            if parent_path != "/" {
                files::require_directory_exists_dev(&state, workspace_id, &parent_path)?;
            }
            files::ensure_file_name_available_dev(&state, workspace_id, &parent_path, &filename)?;
        }
        let file_id = new_id();
        let content_type = upload
            .content_type
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| files::guess_content_type(&filename));
        let file_size = upload.bytes.len().min(i32::MAX as usize) as i32;
        let storage_key = format!("{file_id}/{filename}");
        self.object_store
            .put(
                &self.object_key(workspace_id, &storage_key),
                upload.bytes,
                Some(&content_type),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        let file = BlackboardFileRecord {
            id: file_id,
            workspace_id: workspace_id.to_string(),
            parent_path,
            name: filename,
            is_directory: false,
            file_size,
            content_type,
            storage_key,
            uploader_type: "user".to_string(),
            uploader_id: user_id.to_string(),
            uploader_name: user_id.to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at: Utc::now(),
        };
        let mut state = self.lock_state()?;
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: files::file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let file = {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?
        };
        if file.is_directory {
            return Err(WorkspaceApiError::bad_request(
                "Cannot read directory content",
            ));
        }
        let bytes = self
            .object_store
            .get(&self.object_key(workspace_id, &file.storage_key))
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(|| {
                WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found")
            })?;
        Ok(BlackboardFileDownload {
            filename: file.name,
            content_type: if file.content_type.is_empty() {
                "application/octet-stream".to_string()
            } else {
                file.content_type
            },
            file_size: file.file_size,
            etag: file
                .checksum_sha256
                .map(|checksum| format!("\"{checksum}\""))
                .unwrap_or_else(|| format!("W/\"sz-{}-id-{}\"", file.file_size, file.id)),
            bytes,
        })
    }

    async fn patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if body.name.is_none() && body.parent_path.is_none() {
            return Err(WorkspaceApiError::bad_request(
                "Provide at least one of 'name' or 'parent_path'",
            ));
        }
        let mut state = self.lock_state()?;
        if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut file = state
            .files
            .get(file_id)
            .filter(|file| file.workspace_id == workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if let Some(parent_path) = body.parent_path {
            let target_parent = files::validate_file_path(&parent_path)?;
            if target_parent != file.parent_path {
                if target_parent != "/" {
                    files::require_directory_exists_dev(&state, workspace_id, &target_parent)?;
                }
                if file.is_directory {
                    let own_prefix = files::join_child_path(&file.parent_path, &file.name)?;
                    if target_parent == own_prefix || target_parent.starts_with(&own_prefix) {
                        return Err(WorkspaceApiError::bad_request(
                            "Cannot move a directory into itself",
                        ));
                    }
                    let new_prefix = files::join_child_path(&target_parent, &file.name)?;
                    files::bulk_update_parent_path_dev(
                        &mut state,
                        workspace_id,
                        &own_prefix,
                        &new_prefix,
                    );
                }
                files::ensure_file_name_available_dev(
                    &state,
                    workspace_id,
                    &target_parent,
                    &file.name,
                )?;
                file.parent_path = target_parent;
            }
        }
        if let Some(name) = body.name {
            let safe_name = files::validate_filename(&name)?;
            if safe_name != file.name {
                files::ensure_file_name_available_dev(
                    &state,
                    workspace_id,
                    &file.parent_path,
                    &safe_name,
                )?;
                if file.is_directory {
                    let old_prefix = files::join_child_path(&file.parent_path, &file.name)?;
                    let new_prefix = files::join_child_path(&file.parent_path, &safe_name)?;
                    files::bulk_update_parent_path_dev(
                        &mut state,
                        workspace_id,
                        &old_prefix,
                        &new_prefix,
                    );
                }
                file.name = safe_name;
            }
        }
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_updated".to_string(),
            payload_json: json!({ "file": view, "file_id": view.id }),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let source;
        let target_parent = files::validate_file_path(&body.target_parent_path)?;
        let copy_name;
        {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            source = state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
            if target_parent != "/" {
                files::require_directory_exists_dev(&state, workspace_id, &target_parent)?;
            }
            copy_name = files::validate_filename(body.name.as_deref().unwrap_or(&source.name))?;
            files::ensure_file_name_available_dev(
                &state,
                workspace_id,
                &target_parent,
                &copy_name,
            )?;
        }
        let copied = if source.is_directory {
            files::copy_directory_dev(
                self,
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        } else {
            files::copy_single_file_dev(
                self,
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        };
        let mut state = self.lock_state()?;
        let view = BlackboardFileView::from(copied);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: files::file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    async fn delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let (file, descendants) = {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            let file = state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
            let descendants = if file.is_directory {
                let child_path = files::join_child_path(&file.parent_path, &file.name)?;
                let children = files::list_files_dev(&state, workspace_id, &child_path);
                if !children.is_empty() && !query.recursive {
                    return Err(WorkspaceApiError::bad_request("Directory is not empty"));
                }
                files::find_descendants_dev(&state, workspace_id, &child_path)
            } else {
                Vec::new()
            };
            (file, descendants)
        };
        for descendant in &descendants {
            if !descendant.is_directory && !descendant.storage_key.is_empty() {
                self.object_store
                    .delete(&self.object_key(workspace_id, &descendant.storage_key))
                    .await
                    .map_err(WorkspaceApiError::internal)?;
            }
        }
        if !file.is_directory && !file.storage_key.is_empty() {
            self.object_store
                .delete(&self.object_key(workspace_id, &file.storage_key))
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        let mut state = self.lock_state()?;
        for descendant in descendants {
            state.files.remove(&descendant.id);
        }
        if state.files.remove(file_id).is_none() {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: if file.is_directory {
                "blackboard_directory_deleted".to_string()
            } else {
                "blackboard_file_deleted".to_string()
            },
            payload_json: json!({
                "workspace_id": workspace_id,
                "file_id": file_id,
                "deleted": true,
                "recursive": query.recursive,
                "is_directory": file.is_directory
            }),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(DeletedView { deleted: true })
    }
}

fn new_id() -> String {
    generate_uuid_v4()
}

#[cfg(test)]
mod tests;
