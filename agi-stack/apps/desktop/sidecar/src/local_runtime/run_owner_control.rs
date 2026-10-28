//! Cancellation follows the authenticated session that owns an execution.
use std::sync::{Arc, Weak};

use chrono::Utc;

use super::{
    auth_context::AuthenticatedContext, knowledge_authority_v2::agent_access, ActiveAgentRun,
    DesktopRunStatus, LocalRunControl, LocalRuntimeState, SessionStatus,
};

#[derive(Clone)]
pub(super) struct OwnedExecution {
    auth: AuthenticatedContext,
    pub(super) run_id: Option<String>,
    control: Weak<LocalRunControl>,
    revoked: bool,
}

impl LocalRuntimeState {
    pub(super) fn bind_current_run_owner(
        &self,
        conversation_id: &str,
        run_id: Option<&str>,
        control: &Arc<LocalRunControl>,
    ) {
        if let Some(auth) = agent_access::current_auth() {
            self.bind_run_owner(conversation_id, run_id, control, auth);
        }
    }

    pub(super) fn bind_run_owner(
        &self,
        conversation_id: &str,
        run_id: Option<&str>,
        control: &Arc<LocalRunControl>,
        auth: AuthenticatedContext,
    ) {
        let runs = self.agent_runs.lock().expect("local agent runs");
        if !runs
            .get(conversation_id)
            .is_some_and(|active| Arc::ptr_eq(&active.control, control))
        {
            return;
        }
        self.record_run_owner(conversation_id, run_id, control, auth);
    }

    // Caller holds agent_runs, so registration cannot race revocation's idle claim.
    pub(super) fn record_run_owner(
        &self,
        conversation_id: &str,
        run_id: Option<&str>,
        control: &Arc<LocalRunControl>,
        auth: AuthenticatedContext,
    ) {
        let mut owners = self.run_owners.lock().expect("local run owners");
        let revoked = owners
            .get(conversation_id)
            .is_some_and(|owner| owner.revoked && owner.control.ptr_eq(&Arc::downgrade(control)));
        owners.insert(
            conversation_id.to_owned(),
            OwnedExecution {
                auth: auth.clone(),
                run_id: run_id.map(str::to_owned),
                control: Arc::downgrade(control),
                revoked,
            },
        );
        drop(owners);
        // Publishing before revalidation closes logout-before-registration races.
        if !self
            .session_store
            .session_context_is_current(&auth, Utc::now().timestamp_millis())
            .unwrap_or(false)
        {
            control.request_cancel();
            if let Some(run_id) = run_id {
                self.cua_repl.cancel_run(run_id);
                self.clear_run_capabilities(run_id);
            }
        }
    }

    pub(super) fn clear_run_capabilities(&self, run_id: &str) {
        self.browser_once_consents
            .lock()
            .expect("browser once consents")
            .retain(|(owner, _)| owner != run_id);
        self.run_once_tool_permissions
            .lock()
            .expect("run once tool permissions")
            .retain(|(owner, _)| owner != run_id);
        self.mcp_app_automation.revoke_run(run_id);
        self.browser_auth.cancel_run(run_id);
    }

    pub(super) async fn revoke_session_runs(self: &Arc<Self>, session_id: &str) {
        self.revoke_owned_runs(|owner| owner.auth.session_id == session_id)
            .await;
    }

    pub(super) async fn revoke_stale_context_runs(self: &Arc<Self>, user_id: &str) {
        self.revoke_owned_runs(|owner| {
            owner.auth.user.user_id == user_id
                && !self
                    .session_store
                    .session_context_is_current(&owner.auth, Utc::now().timestamp_millis())
                    .unwrap_or(false)
        })
        .await;
    }

    async fn revoke_owned_runs(self: &Arc<Self>, revoked: impl Fn(&OwnedExecution) -> bool) {
        let owners = {
            let mut runs = self.agent_runs.lock().expect("local agent runs");
            let mut owners = self.run_owners.lock().expect("local run owners");
            let mut selected = Vec::new();
            owners.retain(|conversation_id, owner| {
                if !owner.revoked && revoked(owner) {
                    owner.revoked = true;
                    let idle_control = if runs.contains_key(conversation_id) {
                        None
                    } else {
                        let control = Arc::new(LocalRunControl::new(
                            self.session_store.clone(),
                            owner.run_id.as_deref(),
                        ));
                        control.request_cancel();
                        runs.insert(
                            conversation_id.clone(),
                            ActiveAgentRun {
                                run_id: owner.run_id.clone(),
                                control: control.clone(),
                            },
                        );
                        Some(control)
                    };
                    let active = idle_control.is_none();
                    selected.push((conversation_id.clone(), owner.clone(), idle_control));
                    active
                } else {
                    true
                }
            });
            selected
        };
        // Revoke every execution before cleanup performs any asynchronous I/O.
        for (conversation_id, owner, idle_control) in &owners {
            if let Some(control) = owner.control.upgrade() {
                control.request_cancel();
                if idle_control.is_none() {
                    let state = self.clone();
                    let conversation_id = conversation_id.clone();
                    let owner = owner.clone();
                    tokio::spawn(async move {
                        control.wait_until_released().await;
                        state.cancel_released_owner(&conversation_id, &owner).await;
                    });
                }
            }
            if let Some(run_id) = owner.run_id.as_deref() {
                self.cua_repl.cancel_run(run_id);
                self.clear_run_capabilities(run_id);
            }
        }
        for (conversation_id, owner, idle_control) in owners {
            if let Some(run_id) = owner.run_id.as_deref() {
                self.computer_use.stop_run(self, run_id).await;
                if let Some(host) = self.connected_browser_tool_host() {
                    host.turn_ended(run_id).await;
                }
            }
            // An active engine persists its own cancellation. A suspended run
            // needs the same exclusive claim before changing its checkpoint.
            let Some(control) = idle_control else {
                continue;
            };
            if let Err(error) = self
                .cancel_idle_owned_run(&conversation_id, owner.run_id.as_deref())
                .await
            {
                eprintln!("failed to cancel revoked local execution: {error}");
            }
            self.clear_suspended_operation_v2(&conversation_id, owner.run_id.as_deref());
            self.release_agent_run_if_control(&conversation_id, &control);
        }
    }

    async fn cancel_released_owner(&self, conversation_id: &str, expected: &OwnedExecution) {
        let control = {
            let mut runs = self.agent_runs.lock().expect("local agent runs");
            let mut owners = self.run_owners.lock().expect("local run owners");
            if !owners.get(conversation_id).is_some_and(|owner| {
                owner.revoked
                    && Weak::ptr_eq(&owner.control, &expected.control)
                    && owner.run_id == expected.run_id
            }) || runs.contains_key(conversation_id)
            {
                return;
            }
            owners.remove(conversation_id);
            let control = Arc::new(LocalRunControl::new(
                self.session_store.clone(),
                expected.run_id.as_deref(),
            ));
            control.request_cancel();
            runs.insert(
                conversation_id.to_owned(),
                ActiveAgentRun {
                    run_id: expected.run_id.clone(),
                    control: control.clone(),
                },
            );
            control
        };
        if let Err(error) = self
            .cancel_idle_owned_run(conversation_id, expected.run_id.as_deref())
            .await
        {
            eprintln!("failed to finish revoked local execution: {error}");
        }
        self.clear_suspended_operation_v2(conversation_id, expected.run_id.as_deref());
        self.release_agent_run_if_control(conversation_id, &control);
    }

    async fn cancel_idle_owned_run(
        &self,
        conversation_id: &str,
        run_id: Option<&str>,
    ) -> Result<(), String> {
        if let Some(run_id) = run_id {
            let Some(run) = self.session_store.run(run_id)? else {
                return Ok(());
            };
            if run.status.is_terminal() || run.status == DesktopRunStatus::ReadyReview {
                return Ok(());
            }
            let Some(mut checkpoint) = self.load_authoritative_checkpoint_for_run(&run).await?
            else {
                return Err("revoked execution checkpoint is missing or changed".into());
            };
            if matches!(
                checkpoint.status,
                SessionStatus::Finished | SessionStatus::Failed
            ) {
                return Err("revoked execution checkpoint is already terminal".into());
            }
            checkpoint.status = SessionStatus::Cancelled;
            checkpoint.answer = None;
            checkpoint.pending_hitl = None;
            self.checkpoints
                .save(&checkpoint)
                .await
                .map_err(|error| error.to_string())?;
            let cancelled = self
                .persist_authoritative_run_outcome(
                    &run,
                    DesktopRunStatus::Cancelled,
                    None,
                    &super::now_iso(),
                )
                .await?;
            self.publish_run_status(&cancelled);
        } else if let Some(mut checkpoint) = self
            .checkpoints
            .load(conversation_id)
            .await
            .map_err(|error| error.to_string())?
        {
            if !matches!(
                checkpoint.status,
                SessionStatus::Finished | SessionStatus::Failed | SessionStatus::Cancelled
            ) {
                checkpoint.status = SessionStatus::Cancelled;
                checkpoint.answer = None;
                checkpoint.pending_hitl = None;
                self.checkpoints
                    .save(&checkpoint)
                    .await
                    .map_err(|error| error.to_string())?;
            }
        }
        Ok(())
    }
}
