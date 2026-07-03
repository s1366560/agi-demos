use super::*;

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

struct WorkerStreamIdleProgress {
    summary: String,
    idle_seconds: i64,
    running_exists: bool,
    finished_message_id: Option<String>,
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
        let mut state = worker_stream_watchdog::StreamState::default();
        state.stream_message_id = string_from_map(&metadata, "worker_stream_message_id");
        state.last_stream_event_type = string_from_map(&metadata, "worker_stream_last_event_type");
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
            &input,
            last_entry_id,
            last_event_time_us,
            &state,
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

    async fn worker_stream_idle_progress(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        state: &worker_stream_watchdog::StreamState,
        last_event_time_us: Option<i64>,
        metadata: &Map<String, Value>,
    ) -> Option<WorkerStreamIdleProgress> {
        let last_event_time_us = last_event_time_us?;
        let now_us = input.now.timestamp_micros();
        if now_us <= last_event_time_us {
            return None;
        }
        let idle_seconds = (now_us - last_event_time_us) as f64 / 1_000_000.0;
        let last_published_at = metadata
            .get("worker_stream_idle_progress_published_at_us")
            .and_then(Value::as_i64)
            .map(|value| value as f64 / 1_000_000.0)
            .unwrap_or_default();
        let now_seconds = now_us as f64 / 1_000_000.0;
        if !worker_stream_watchdog::should_publish_idle_progress(
            idle_seconds,
            last_published_at,
            now_seconds,
            None,
        ) {
            return None;
        }
        let finished_message_id = self
            .runtime_agent_finished_message_id(input.conversation_id)
            .await;
        let running_exists = self
            .runtime_agent_running_exists(input.conversation_id)
            .await;
        let summary = worker_stream_watchdog::idle_progress_summary(
            idle_seconds,
            state.last_stream_event_type.as_deref(),
            running_exists,
            finished_message_id.as_deref(),
        );
        Some(WorkerStreamIdleProgress {
            summary,
            idle_seconds: idle_seconds as i64,
            running_exists,
            finished_message_id,
        })
    }

    async fn mark_workspace_plan_node_stream_idle(
        &self,
        input: &WorkerStreamReplayInput<'_>,
        progress: &WorkerStreamIdleProgress,
    ) -> CoreResult<()> {
        let (Some(plan_id), Some(node_id)) = (input.plan_id, input.node_id) else {
            return Ok(());
        };
        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        let Some(mut node) = nodes.drain(..).find(|candidate| candidate.id == node_id) else {
            return Ok(());
        };
        if node.current_attempt_id.as_deref() != Some(input.attempt_id) {
            return Ok(());
        }
        if node.execution != "running" {
            return Ok(());
        }

        let mut progress_json = object_or_empty(node.progress_json.clone());
        progress_json
            .entry("percent".to_string())
            .or_insert_with(|| json!(0.0));
        progress_json
            .entry("confidence".to_string())
            .or_insert_with(|| json!(1.0));
        progress_json.insert("note".to_string(), json!(progress.summary.clone()));

        let mut metadata = object_or_empty(node.metadata_json.clone());
        let reported_at = input.now.to_rfc3339();
        let progress_event = json!({
            "event_type": "worker_stream_idle",
            "source_event_type": "worker_stream_idle",
            "summary": progress.summary.clone(),
            "attempt_id": input.attempt_id,
            "worker_agent_id": input.worker_agent_id,
            "idle_seconds": progress.idle_seconds,
            "running_exists": progress.running_exists,
            "reported_at": reported_at.clone()
        });
        let mut progress_events = metadata
            .get("progress_events")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        progress_events.push(progress_event.clone());
        if progress_events.len() > 25 {
            progress_events = progress_events.split_off(progress_events.len() - 25);
        }
        metadata.insert("progress_events".to_string(), Value::Array(progress_events));
        metadata.insert("latest_worker_progress".to_string(), progress_event);
        metadata.insert("launch_state".to_string(), json!("stream_idle"));
        metadata.insert(
            "worker_stream_idle_progress_summary".to_string(),
            json!(progress.summary.clone()),
        );
        metadata.insert(
            "worker_stream_idle_progress_published_at".to_string(),
            json!(reported_at),
        );

        node.intent = "in_progress".to_string();
        node.progress_json = Value::Object(progress_json);
        node.metadata_json = Value::Object(metadata);
        node.updated_at = Some(input.now);
        self.store.save_plan_node(node).await?;
        Ok(())
    }
}

fn worker_stream_event_time_us(event: &Value) -> Option<i64> {
    event
        .get("event_time_us")
        .and_then(Value::as_i64)
        .or_else(|| {
            event
                .get("event_time_us")
                .and_then(Value::as_u64)
                .and_then(|value| i64::try_from(value).ok())
        })
}

fn worker_stream_poll_outbox(
    item: &WorkspacePlanOutboxRecord,
    payload: &Map<String, Value>,
    conversation_id: &str,
    replay: &WorkerStreamReplayResult,
    delay_seconds: i64,
    now: DateTime<Utc>,
) -> WorkspacePlanOutboxRecord {
    let mut poll_payload = payload.clone();
    poll_payload.insert("worker_stream_poll".to_string(), json!(true));
    poll_payload.insert("stream_after_id".to_string(), json!(replay.next_after_id()));
    poll_payload.insert(
        "worker_stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    poll_payload.remove("reuse_conversation_id");

    let mut metadata = object_or_empty(item.metadata_json.clone());
    let poll_count = metadata
        .get("stream_poll_count")
        .and_then(Value::as_i64)
        .unwrap_or(0)
        + 1;
    metadata.insert(
        "source".to_string(),
        json!("workspace_plan.worker_launch.stream_poll"),
    );
    metadata.insert(
        "stream_poll_from_outbox_id".to_string(),
        json!(item.id.clone()),
    );
    metadata.insert("stream_poll_count".to_string(), json!(poll_count));
    metadata.insert(
        "stream_poll_after_id".to_string(),
        json!(replay.next_after_id()),
    );
    metadata.insert(
        "stream_poll_conversation_id".to_string(),
        json!(conversation_id),
    );
    metadata.insert(
        "stream_poll_entries_read".to_string(),
        json!(replay.entries_read),
    );

    WorkspacePlanOutboxRecord {
        id: generate_uuid_v4(),
        plan_id: item.plan_id.clone(),
        workspace_id: item.workspace_id.clone(),
        event_type: WORKER_LAUNCH_EVENT.to_string(),
        payload_json: Value::Object(poll_payload),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: item.max_attempts,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: Some(now + ChronoDuration::seconds(delay_seconds.max(1))),
        processed_at: None,
        metadata_json: Value::Object(metadata),
        created_at: now,
        updated_at: None,
    }
}
