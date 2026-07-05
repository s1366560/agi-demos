use super::*;

mod idle;
mod metadata;
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
}
