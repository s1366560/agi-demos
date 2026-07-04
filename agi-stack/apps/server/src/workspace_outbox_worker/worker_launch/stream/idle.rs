use super::*;

pub(super) struct WorkerStreamIdleProgress {
    pub(super) summary: String,
    pub(super) idle_seconds: i64,
    pub(super) running_exists: bool,
    pub(super) finished_message_id: Option<String>,
}

impl WorkerLaunchAdmissionHandler {
    pub(super) async fn worker_stream_idle_progress(
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

    pub(super) async fn mark_workspace_plan_node_stream_idle(
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
