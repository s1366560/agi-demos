//! In-process suspended operations retain the same generation across HITL and pause.

use super::*;

pub(super) struct SuspendedAgentOperationV2 {
    message_id: String,
    run_id: Option<String>,
    request_id: Option<String>,
    generation: Arc<ActivePlatformPluginGenerationLeaseV2>,
}

impl LocalRuntimeState {
    pub(super) fn retain_suspended_operation_v2(
        &self,
        conversation_id: &str,
        message_id: &str,
        run_id: Option<&str>,
        checkpoint: Option<&SessionState>,
        generation: Option<&Arc<ActivePlatformPluginGenerationLeaseV2>>,
    ) {
        let mut suspended = self
            .suspended_agent_operations_v2
            .lock()
            .expect("suspended agent operations");
        let continuation = checkpoint.filter(|checkpoint| {
            matches!(
                checkpoint.status,
                SessionStatus::AwaitingInput | SessionStatus::Paused
            )
        });
        if let (Some(checkpoint), Some(generation)) = (continuation, generation) {
            suspended.insert(
                conversation_id.to_owned(),
                SuspendedAgentOperationV2 {
                    message_id: message_id.to_owned(),
                    run_id: run_id.map(str::to_owned),
                    request_id: checkpoint
                        .pending_hitl
                        .as_ref()
                        .map(|request| request.id.clone()),
                    generation: generation.clone(),
                },
            );
        } else if suspended
            .get(conversation_id)
            .is_some_and(|held| held.message_id == message_id && held.run_id.as_deref() == run_id)
        {
            suspended.remove(conversation_id);
        }
    }

    /// Called only after the current request has passed conversation/run/HITL authority checks.
    /// Authentication remains fresh; only the already admitted operation's generation is reused.
    pub(super) fn continuation_operation_v2(
        &self,
        conversation_id: &str,
        fallback_message_id: String,
        run_id: Option<&str>,
        request_id: Option<&str>,
        fallback_generation: Option<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    ) -> (String, Option<Arc<ActivePlatformPluginGenerationLeaseV2>>) {
        let suspended = self
            .suspended_agent_operations_v2
            .lock()
            .expect("suspended agent operations");
        let held = suspended.get(conversation_id).filter(|held| {
            held.run_id.as_deref() == run_id
                && held.request_id.as_deref() == request_id
                && (run_id.is_none() || held.message_id == fallback_message_id)
        });
        match held {
            Some(held) => (held.message_id.clone(), Some(held.generation.clone())),
            None => (fallback_message_id, fallback_generation),
        }
    }

    pub(super) fn clear_suspended_operation_v2(&self, conversation_id: &str, run_id: Option<&str>) {
        let mut suspended = self
            .suspended_agent_operations_v2
            .lock()
            .expect("suspended agent operations");
        if suspended
            .get(conversation_id)
            .is_some_and(|held| run_id.is_none() || held.run_id.as_deref() == run_id)
        {
            suspended.remove(conversation_id);
        }
    }
}
