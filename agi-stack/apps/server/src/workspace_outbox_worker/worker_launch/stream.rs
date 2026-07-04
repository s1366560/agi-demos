use super::*;

mod idle;
mod poll;
mod replay;

use poll::worker_stream_poll_outbox;
use replay::worker_stream_event_time_us;

pub(super) struct WorkerStreamReplayInput<'a> {
    pub(super) workspace_id: &'a str,
    pub(super) task_id: &'a str,
    pub(super) root_goal_task_id: Option<&'a str>,
    pub(super) attempt_id: &'a str,
    pub(super) conversation_id: &'a str,
    pub(super) actor_user_id: &'a str,
    pub(super) worker_agent_id: &'a str,
    pub(super) leader_agent_id: Option<&'a str>,
    pub(super) plan_id: Option<&'a str>,
    pub(super) node_id: Option<&'a str>,
    pub(super) stream_after_id: Option<&'a str>,
    pub(super) now: DateTime<Utc>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct WorkerStreamReplayResult {
    replay_after_id: String,
    last_entry_id: Option<String>,
    entries_read: usize,
    terminal_seen: bool,
}

impl WorkerStreamReplayResult {
    fn empty(replay_after_id: String) -> Self {
        Self {
            replay_after_id,
            last_entry_id: None,
            entries_read: 0,
            terminal_seen: false,
        }
    }

    fn next_after_id(&self) -> &str {
        self.last_entry_id
            .as_deref()
            .unwrap_or(&self.replay_after_id)
    }

    fn is_nonterminal(&self) -> bool {
        !self.terminal_seen
    }
}

impl WorkerLaunchAdmissionHandler {
    pub(super) async fn replay_bound_worker_stream_once(
        &self,
        input: WorkerStreamReplayInput<'_>,
    ) -> CoreResult<WorkerStreamReplayResult> {
        let stream_after_id = self.worker_stream_replay_after_id(&input).await?;
        let (mut state, mut last_event_time_us) = self
            .worker_stream_state_from_replay_metadata(&input)
            .await?;
        let entries = self
            .stream_events
            .read_after(
                input.conversation_id,
                &stream_after_id,
                DEFAULT_WORKER_STREAM_REPLAY_BATCH_LIMIT,
            )
            .await?;
        if entries.is_empty() {
            if self
                .stop_orphaned_worker_stream_if_needed(&input, &mut state, None, last_event_time_us)
                .await?
            {
                return Ok(WorkerStreamReplayResult {
                    replay_after_id: stream_after_id,
                    last_entry_id: None,
                    entries_read: 0,
                    terminal_seen: true,
                });
            }
            return Ok(WorkerStreamReplayResult::empty(stream_after_id));
        }

        let mut last_entry_id = None;
        let mut terminal_seen = false;
        let mut entries_read = 0;
        for entry in entries {
            entries_read += 1;
            last_entry_id = Some(entry.id.clone());
            let event = match serde_json::from_str::<Value>(&entry.payload) {
                Ok(event) => event,
                Err(err) => json!({
                    "type": "error",
                    "data": {
                        "message": format!(
                            "Malformed worker stream payload at {}: {err}",
                            entry.id
                        )
                    }
                }),
            };
            if let Some(event_time_us) = worker_stream_event_time_us(&event) {
                last_event_time_us = Some(event_time_us);
            }
            if state.observe_event(&event).is_some() {
                terminal_seen = true;
                break;
            }
        }

        let last_entry_id = last_entry_id.as_deref();
        if !terminal_seen {
            if self
                .stop_orphaned_worker_stream_if_needed(
                    &input,
                    &mut state,
                    last_entry_id,
                    last_event_time_us,
                )
                .await?
            {
                return Ok(WorkerStreamReplayResult {
                    replay_after_id: stream_after_id,
                    last_entry_id: last_entry_id.map(ToOwned::to_owned),
                    entries_read,
                    terminal_seen: true,
                });
            }
            self.patch_worker_stream_replay_metadata(
                &input,
                last_entry_id,
                last_event_time_us,
                &state,
                None,
            )
            .await?;
            return Ok(WorkerStreamReplayResult {
                replay_after_id: stream_after_id,
                last_entry_id: last_entry_id.map(ToOwned::to_owned),
                entries_read,
                terminal_seen: false,
            });
        }

        self.persist_worker_stream_replay_terminal_outcome(
            &input,
            &state,
            last_entry_id,
            last_event_time_us,
        )
        .await?;
        Ok(WorkerStreamReplayResult {
            replay_after_id: stream_after_id,
            last_entry_id: last_entry_id.map(ToOwned::to_owned),
            entries_read,
            terminal_seen: true,
        })
    }

    async fn worker_stream_state_from_replay_metadata(
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

    async fn stop_orphaned_worker_stream_if_needed(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &mut worker_stream_watchdog::StreamState,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
    ) -> CoreResult<bool> {
        let finished_message_id = self
            .runtime_agent_finished_message_id(input.conversation_id)
            .await;
        let running_exists = self
            .runtime_agent_running_exists(input.conversation_id)
            .await;
        let idle_seconds = last_event_time_us
            .filter(|event_time_us| input.now.timestamp_micros() > *event_time_us)
            .map(|event_time_us| {
                (input.now.timestamp_micros() - event_time_us) as f64 / 1_000_000.0
            })
            .unwrap_or_default();
        let decision = worker_stream_watchdog::should_stop(
            finished_message_id.as_deref(),
            state.stream_message_id.as_deref(),
            running_exists,
            idle_seconds,
            None,
        );
        if !decision.should_stop {
            return Ok(false);
        }
        state.mark_orphaned_stream_stop(
            decision
                .reason
                .map(worker_stream_watchdog::StopReason::as_str),
        );
        self.persist_worker_stream_replay_terminal_outcome(
            input,
            state,
            last_entry_id,
            last_event_time_us,
        )
        .await?;
        Ok(true)
    }

    async fn persist_worker_stream_replay_terminal_outcome(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &worker_stream_watchdog::StreamState,
        last_entry_id: Option<&str>,
        last_event_time_us: Option<i64>,
    ) -> CoreResult<()> {
        let report_recorded_for_attempt = self
            .store
            .get_task(input.workspace_id, input.task_id)
            .await?
            .map(|task| {
                worker_stream_watchdog::terminal_report_metadata_matches_attempt(
                    Some(&task.metadata_json),
                    Some(input.attempt_id),
                    None,
                )
            })
            .unwrap_or(false);
        let outcome = state.terminal_outcome(report_recorded_for_attempt);
        self.persist_worker_stream_terminal_outcome(WorkerStreamTerminalPersistence {
            workspace_id: input.workspace_id,
            task_id: input.task_id,
            root_goal_task_id: input.root_goal_task_id,
            attempt_id: Some(input.attempt_id),
            conversation_id: Some(input.conversation_id),
            actor_user_id: input.actor_user_id,
            worker_agent_id: input.worker_agent_id,
            leader_agent_id: input.leader_agent_id,
            plan_id: input.plan_id,
            node_id: input.node_id,
            outcome: &outcome,
            now: input.now,
        })
        .await?;
        self.patch_worker_stream_replay_metadata(
            input,
            last_entry_id,
            last_event_time_us,
            state,
            Some(&outcome),
        )
        .await?;
        Ok(())
    }

    pub(super) async fn enqueue_worker_stream_poll_if_needed(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        replay: &WorkerStreamReplayResult,
        conversation_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        if !replay.is_nonterminal() {
            return Ok(());
        }
        if self
            .runtime_agent_finished_message_id(conversation_id)
            .await
            .is_some()
        {
            return Ok(());
        }
        let running_exists = self.runtime_agent_running_exists(conversation_id).await;
        if !running_exists && replay.entries_read == 0 {
            return Ok(());
        }
        self.store
            .enqueue_plan_outbox(worker_stream_poll_outbox(
                item,
                payload,
                conversation_id,
                replay,
                self.config.stream_poll_interval_seconds,
                now,
            ))
            .await?;
        Ok(())
    }

    async fn worker_stream_replay_after_id(
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

    async fn patch_worker_stream_replay_metadata(
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
