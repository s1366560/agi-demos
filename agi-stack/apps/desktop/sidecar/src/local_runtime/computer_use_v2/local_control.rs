//! A paused local call retains its exact native session until the user resolves it.
use super::*;
use agistack_core::{agent::ToolControlResolution, ports::ToolControlOutcome};

pub(super) struct Receipt {
    session: Arc<Session>,
    native: NativeIdentity,
}

impl Receipt {
    pub(super) fn belongs_to_run(&self, run_id: &str) -> bool {
        self.session.context.run_id == run_id
    }
}

pub(super) fn retain(
    state: &LocalRuntimeState,
    session: &Arc<Session>,
    native: &NativeIdentity,
    tool: &str,
    result: &ToolResult,
) -> CoreResult<()> {
    if session.cloud.is_some() || result.control_outcome != Some(ToolControlOutcome::UserPaused) {
        return Ok(());
    }
    let generation = result
        .control_generation
        .as_ref()
        .ok_or_else(|| CoreError::Tool("cua_control_generation_required".into()))?;
    let identity = call_identity::current(tool)?;
    let mut receipts = state
        .computer_use
        .local_controls
        .lock()
        .expect("local control receipts");
    // One engine dispatches one tool per round. Replacing its receipt bounds
    // abandoned results when a result policy withholds a control outcome.
    receipts.retain(|(engine, _), _| engine != identity.engine_session_id());
    receipts.insert(
        (identity.engine_session_id().into(), generation.clone()),
        Receipt {
            session: session.clone(),
            native: native.clone(),
        },
    );
    Ok(())
}

pub(in crate::local_runtime) async fn wait(
    state: &LocalRuntimeState,
    conversation_id: &str,
    engine_session_id: &str,
    result: &ToolResult,
) -> CoreResult<ToolControlResolution> {
    if result.control_outcome != Some(ToolControlOutcome::UserPaused) {
        return Ok(ToolControlResolution::Stopped);
    }
    let generation = result
        .control_generation
        .as_deref()
        .ok_or_else(|| CoreError::Tool("cua_control_generation_required".into()))?;
    let receipt = state
        .computer_use
        .local_controls
        .lock()
        .expect("local control receipts")
        .remove(&(engine_session_id.into(), generation.into()));
    let Some(receipt) = receipt else {
        // Recovery without the original native generation cannot create resume authority.
        return Ok(ToolControlResolution::Pending);
    };
    if receipt.session.context.conversation_id != conversation_id {
        return Err(CoreError::Tool("cua_control_scope_mismatch".into()));
    }
    wait_until_resolved(&receipt.session.user_control, generation, || {
        let active = state
            .agent_runs
            .lock()
            .expect("local agent runs")
            .get(conversation_id)
            .cloned();
        if active.as_ref().is_some_and(|active| {
            active
                .run_id
                .as_deref()
                .is_none_or(|run| run == receipt.session.context.run_id)
                && active.control.directive.load(Ordering::Acquire)
                    != super::super::LocalRunControl::CONTINUE
        }) {
            // Let the engine consume its normal Pause/Cancel directive next.
            return Ok(false);
        }
        if !receipt.native.current(state) {
            return Err(CoreError::Tool("cua_authorization_revoked".into()));
        }
        let instance = store::instance(
            &*state
                .session_store
                .connection()
                .map_err(CoreError::Storage)?,
            &receipt.session.owner,
        )
        .map_err(CoreError::Storage)?;
        if !instance.enabled || !instance.installed || instance.revision != receipt.session.revision
        {
            return Err(CoreError::Tool("cua_instance_disabled".into()));
        }
        if let Some(child) = receipt.session.child.as_ref() {
            let run = state
                .session_store
                .run(&child.run_id)
                .map_err(CoreError::Storage)?
                .ok_or_else(|| CoreError::Tool("cua_child_authority_revoked".into()))?;
            if !state.subagent_controls.plugin_execution_current(
                &child.execution_id,
                conversation_id,
                &run,
                &child.subagent_id,
                state.control_for_run(&run).as_ref(),
            ) {
                return Err(CoreError::Tool("cua_child_authority_revoked".into()));
            }
        }
        if receipt.session.stopped.load(Ordering::SeqCst)
            && receipt.session.user_control.completed(generation) != Some("stopped")
        {
            return Err(CoreError::Tool("cua_authorization_revoked".into()));
        }
        Ok(true)
    })
    .await
}

async fn wait_until_resolved(
    control: &user_control::Control,
    generation: &str,
    current: impl Fn() -> CoreResult<bool>,
) -> CoreResult<ToolControlResolution> {
    loop {
        if !current()? {
            return Ok(ToolControlResolution::RunInterrupted);
        }
        match control.completed(generation) {
            Some("resumed") => return Ok(ToolControlResolution::Resumed),
            Some("stopped") => return Ok(ToolControlResolution::Stopped),
            Some(_) => return Err(CoreError::Tool("cua_control_state_invalid".into())),
            None => {}
        }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn local_control_wait_retains_early_stop_and_resume_without_replay() {
        for stop in [false, true] {
            let control = user_control::Control::default();
            let generation = control.pause();
            let waiting = wait_until_resolved(&control, &generation, || Ok(true));
            tokio::pin!(waiting);
            assert!(
                tokio::time::timeout(std::time::Duration::from_millis(5), &mut waiting)
                    .await
                    .is_err()
            );
            if stop {
                control.stop();
            } else {
                control.resume();
            }
            let expected = if stop {
                ToolControlResolution::Stopped
            } else {
                ToolControlResolution::Resumed
            };
            assert_eq!(waiting.await.unwrap(), expected);
            assert_eq!(
                wait_until_resolved(&control, &generation, || Ok(true))
                    .await
                    .unwrap(),
                expected
            );
        }
    }

    #[tokio::test]
    async fn local_control_wait_honors_revocation_and_parent_cancel() {
        let control = user_control::Control::default();
        let generation = control.pause();
        control.resume();
        assert!(
            wait_until_resolved(&control, &generation, || Err(CoreError::Tool(
                "revoked".into()
            )))
            .await
            .is_err()
        );
        let generation = control.pause();
        assert_eq!(
            wait_until_resolved(&control, &generation, || Ok(false))
                .await
                .unwrap(),
            ToolControlResolution::RunInterrupted
        );
        assert_eq!(control.completed(&generation), None);
    }
}
