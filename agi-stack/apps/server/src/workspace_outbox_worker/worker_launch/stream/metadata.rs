use super::*;

impl WorkerLaunchAdmissionHandler {
    pub(super) async fn worker_stream_state_from_replay_metadata(
        &self,
        input: &WorkerStreamReplayInput<'_>,
    ) -> CoreResult<(worker_stream_watchdog::StreamState, Option<i64>)> {
        let Some(task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok((worker_stream_watchdog::StreamState::default(), None));
        };
        let metadata = object_or_empty(task.metadata_json);
        if !worker_stream_replay_metadata_matches_attempt(&metadata, input.attempt_id) {
            return Ok((worker_stream_watchdog::StreamState::default(), None));
        }
        let state = worker_stream_watchdog::StreamState {
            stream_message_id: string_from_map(&metadata, "worker_stream_message_id"),
            last_stream_event_type: string_from_map(&metadata, "worker_stream_last_event_type"),
            ..Default::default()
        };
        let last_event_time_us = metadata
            .get("worker_stream_last_event_time_us")
            .and_then(Value::as_i64);
        Ok((state, last_event_time_us))
    }

    pub(super) async fn worker_stream_replay_after_id(
        &self,
        input: &WorkerStreamReplayInput<'_>,
    ) -> CoreResult<String> {
        if let Some(after_id) = input
            .stream_after_id
            .filter(|value| !value.trim().is_empty())
        {
            return Ok(after_id.to_string());
        }
        let after_id = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
            .and_then(|task| {
                let metadata = object_or_empty(task.metadata_json);
                if !worker_stream_replay_metadata_matches_attempt(&metadata, input.attempt_id) {
                    return None;
                }
                metadata
                    .get("worker_stream_last_entry_id")
                    .and_then(Value::as_str)
                    .filter(|value| !value.trim().is_empty())
                    .map(ToOwned::to_owned)
            })
            .unwrap_or_default();
        Ok(after_id)
    }

    pub(super) async fn patch_worker_stream_replay_metadata(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
        state: &worker_stream_watchdog::StreamState,
        outcome: Option<&worker_stream_watchdog::TerminalOutcome>,
    ) -> CoreResult<()> {
        let Some(mut task) = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
        else {
            return Ok(());
        };
        let mut metadata = object_or_empty(task.metadata_json.clone());
        let idle_progress = if outcome.is_none() {
            self.worker_stream_idle_progress(input, state, last_event_time_us, &metadata)
                .await
        } else {
            None
        };
        if let Some(last_entry_id) = last_entry_id {
            metadata.insert(
                "worker_stream_last_entry_id".to_string(),
                json!(last_entry_id),
            );
        }
        if let Some(last_event_time_us) = last_event_time_us {
            metadata.insert(
                "worker_stream_last_event_time_us".to_string(),
                json!(last_event_time_us),
            );
        }
        metadata.insert(
            "worker_stream_last_replayed_at".to_string(),
            json!(input.now.to_rfc3339()),
        );
        metadata.insert(
            "worker_stream_replay_status".to_string(),
            json!(if outcome.is_some() {
                "terminal"
            } else if idle_progress.is_some() {
                "stream_idle"
            } else {
                "observed"
            }),
        );
        metadata.insert(
            "worker_stream_replay_attempt_id".to_string(),
            json!(input.attempt_id),
        );
        if let Some(last_event_type) = state
            .last_stream_event_type
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            metadata.insert(
                "worker_stream_last_event_type".to_string(),
                json!(last_event_type),
            );
        }
        if let Some(message_id) = state
            .stream_message_id
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            metadata.insert("worker_stream_message_id".to_string(), json!(message_id));
        }
        if let Some(outcome) = outcome {
            metadata.insert(
                "worker_stream_terminal_outcome".to_string(),
                json!(outcome.outcome_reason),
            );
            metadata.insert(
                "worker_stream_terminal_launch_state".to_string(),
                json!(outcome.launch_state),
            );
            metadata.insert(
                "worker_stream_terminal_should_report".to_string(),
                json!(outcome.should_report),
            );
            metadata.insert(
                "worker_stream_terminal_replayed_at".to_string(),
                json!(input.now.to_rfc3339()),
            );
        }
        if let Some(progress) = idle_progress.as_ref() {
            metadata.insert(
                "worker_stream_idle_progress_summary".to_string(),
                json!(progress.summary.clone()),
            );
            metadata.insert(
                "worker_stream_idle_seconds".to_string(),
                json!(progress.idle_seconds),
            );
            metadata.insert(
                "worker_stream_idle_progress_published_at".to_string(),
                json!(input.now.to_rfc3339()),
            );
            metadata.insert(
                "worker_stream_idle_progress_published_at_us".to_string(),
                json!(input.now.timestamp_micros()),
            );
            metadata.insert(
                "worker_stream_idle_running_exists".to_string(),
                json!(progress.running_exists),
            );
            if let Some(finished_message_id) = progress.finished_message_id.as_deref() {
                metadata.insert(
                    "worker_stream_idle_finished_message_id".to_string(),
                    json!(finished_message_id),
                );
            }
            metadata.insert(
                "execution_state".to_string(),
                worker_execution_state(
                    "in_progress",
                    &progress.summary,
                    "observe_stream_idle",
                    input.leader_agent_id.unwrap_or(input.actor_user_id),
                    input.now,
                ),
            );
        }
        task.metadata_json = Value::Object(metadata);
        task.updated_at = Some(input.now);
        self.store.save_task(task).await?;
        if let Some(progress) = idle_progress.as_ref() {
            self.mark_workspace_plan_node_stream_idle(input, progress)
                .await?;
        }
        Ok(())
    }
}
