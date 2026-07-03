use super::*;

#[derive(Default)]
pub(super) struct FakeWorkspacePlanOutboxStore {
    items: Mutex<HashMap<String, WorkspacePlanOutboxRecord>>,
}

impl FakeWorkspacePlanOutboxStore {
    pub(super) fn insert(&self, item: WorkspacePlanOutboxRecord) {
        self.items.lock().unwrap().insert(item.id.clone(), item);
    }

    pub(super) fn get(&self, id: &str) -> WorkspacePlanOutboxRecord {
        self.items.lock().unwrap().get(id).unwrap().clone()
    }
}

#[async_trait]
impl WorkspacePlanOutboxStore for FakeWorkspacePlanOutboxStore {
    async fn claim_due(
        &self,
        limit: i64,
        lease_owner: &str,
        lease_seconds: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<WorkspacePlanOutboxRecord>> {
        let mut items = self.items.lock().unwrap();
        let mut due = items
            .values()
            .filter(|item| {
                let pending_due = matches!(item.status.as_str(), "pending" | "failed")
                    || (item.event_type == WORKSPACE_AGENT_MENTION_EVENT
                        && matches!(
                            item.status.as_str(),
                            "pending_runtime"
                                | WORKSPACE_AGENT_MENTION_RESPONSE_READY_STATUS
                                | WORKSPACE_AGENT_MENTION_ERROR_READY_STATUS
                        ));
                item.attempt_count < item.max_attempts
                    && ((pending_due && item.next_attempt_at.map(|due| due <= now).unwrap_or(true))
                        || (item.status == "processing"
                            && item
                                .lease_expires_at
                                .map(|expires_at| expires_at <= now)
                                .unwrap_or(false)))
            })
            .map(|item| item.id.clone())
            .collect::<Vec<_>>();
        due.sort();
        due.truncate(limit.max(0) as usize);

        let mut claimed = Vec::new();
        for id in due {
            let item = items.get_mut(&id).unwrap();
            item.status = "processing".to_string();
            item.attempt_count += 1;
            item.lease_owner = Some(lease_owner.to_string());
            item.lease_expires_at = Some(now + Duration::seconds(lease_seconds.max(1)));
            item.next_attempt_at = None;
            item.last_error = None;
            item.updated_at = Some(now);
            claimed.push(item.clone());
        }
        Ok(claimed)
    }

    async fn mark_completed(
        &self,
        outbox_id: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = "completed".to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        item.processed_at = Some(now);
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn mark_failed(
        &self,
        outbox_id: &str,
        error_message: &str,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = if item.attempt_count >= item.max_attempts {
            "dead_letter".to_string()
        } else {
            "failed".to_string()
        };
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = Some(error_message.to_string());
        item.next_attempt_at = Some(now + Duration::seconds(2));
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn release_processing(
        &self,
        outbox_id: &str,
        error_message: Option<&str>,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = "pending".to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = error_message.map(str::to_string);
        item.next_attempt_at = None;
        item.attempt_count = (item.attempt_count - 1).max(0);
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn park_processing(
        &self,
        outbox_id: &str,
        status: &str,
        metadata_patch: &Value,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = status.to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        let mut metadata = object_or_empty(item.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        item.metadata_json = Value::Object(metadata);
        item.updated_at = Some(now);
        Ok(true)
    }

    async fn park_processing_with_payload_patch(
        &self,
        outbox_id: &str,
        status: &str,
        metadata_patch: &Value,
        payload_patch: &Value,
        lease_owner: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        let mut items = self.items.lock().unwrap();
        let Some(item) = items.get_mut(outbox_id) else {
            return Ok(false);
        };
        if item.status != "processing" || item.lease_owner.as_deref() != lease_owner {
            return Ok(false);
        }
        item.status = status.to_string();
        item.lease_owner = None;
        item.lease_expires_at = None;
        item.last_error = None;
        item.next_attempt_at = None;
        let mut metadata = object_or_empty(item.metadata_json.clone());
        for (key, value) in object_or_empty(metadata_patch.clone()) {
            metadata.insert(key, value);
        }
        item.metadata_json = Value::Object(metadata);
        let mut payload = object_or_empty(item.payload_json.clone());
        for (key, value) in object_or_empty(payload_patch.clone()) {
            payload.insert(key, value);
        }
        item.payload_json = Value::Object(payload);
        item.updated_at = Some(now);
        Ok(true)
    }
}

#[derive(Clone)]
pub(super) enum HandlerBehavior {
    Complete,
    Release,
    Fail,
}

pub(super) struct StaticHandler {
    behavior: HandlerBehavior,
}

#[async_trait]
impl WorkspacePlanOutboxHandler for StaticHandler {
    async fn handle(
        &self,
        _item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome> {
        match self.behavior {
            HandlerBehavior::Complete => Ok(WorkspacePlanOutboxHandlerOutcome::Complete),
            HandlerBehavior::Release => Ok(WorkspacePlanOutboxHandlerOutcome::Release {
                reason: Some("shutdown".to_string()),
            }),
            HandlerBehavior::Fail => Err(CoreError::Storage("handler boom".to_string())),
        }
    }
}

pub(super) fn worker(
    store: Arc<FakeWorkspacePlanOutboxStore>,
    handlers: WorkspacePlanOutboxHandlers,
) -> WorkspacePlanOutboxWorker {
    WorkspacePlanOutboxWorker::new(
        store,
        WorkspacePlanOutboxWorkerConfig {
            worker_id: "worker-test".to_string(),
            batch_size: 10,
            lease_seconds: 60,
            poll_interval_millis: 5,
            autostart: false,
            production_ready: false,
        },
        handlers,
    )
}

pub(super) fn handler(behavior: HandlerBehavior) -> Arc<dyn WorkspacePlanOutboxHandler> {
    Arc::new(StaticHandler { behavior })
}

pub(super) fn outbox(id: &str, event_type: &str) -> WorkspacePlanOutboxRecord {
    WorkspacePlanOutboxRecord {
        id: id.to_string(),
        plan_id: Some("plan-test".to_string()),
        workspace_id: "workspace-test".to_string(),
        event_type: event_type.to_string(),
        payload_json: json!({"id": id}),
        status: "pending".to_string(),
        attempt_count: 0,
        max_attempts: 3,
        lease_owner: None,
        lease_expires_at: None,
        last_error: None,
        next_attempt_at: None,
        processed_at: None,
        metadata_json: json!({}),
        created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
        updated_at: None,
    }
}
