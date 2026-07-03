use super::*;

pub(super) struct FakeWorkspaceAgentMentionRuntime {
    result: Result<String, String>,
    prompts: Mutex<Vec<String>>,
}

impl FakeWorkspaceAgentMentionRuntime {
    pub(super) fn ok(answer: &str) -> Self {
        Self {
            result: Ok(answer.to_string()),
            prompts: Mutex::new(Vec::new()),
        }
    }

    pub(super) fn err(message: &str) -> Self {
        Self {
            result: Err(message.to_string()),
            prompts: Mutex::new(Vec::new()),
        }
    }

    pub(super) fn prompts(&self) -> Vec<String> {
        self.prompts.lock().unwrap().clone()
    }
}

#[async_trait]
impl WorkspaceAgentMentionRuntime for FakeWorkspaceAgentMentionRuntime {
    async fn complete(&self, input: WorkspaceAgentMentionRuntimeInput) -> CoreResult<String> {
        self.prompts.lock().unwrap().push(input.user_prompt);
        self.result
            .clone()
            .map_err(|message| CoreError::Llm(message.to_string()))
    }
}

#[derive(Default)]
pub(super) struct StaticPipelineStageRunner {
    results: Mutex<HashMap<String, PipelineStageResult>>,
    seen: Mutex<Vec<(String, String, String)>>,
}

impl StaticPipelineStageRunner {
    pub(super) fn with_result(self, result: PipelineStageResult) -> Self {
        self.results
            .lock()
            .unwrap()
            .insert(result.stage.clone(), result);
        self
    }

    pub(super) fn seen(&self) -> Vec<(String, String, String)> {
        self.seen.lock().unwrap().clone()
    }
}

#[async_trait]
impl WorkspacePipelineStageRunner for StaticPipelineStageRunner {
    async fn run_stage(
        &self,
        project_id: &str,
        _contract: &PipelineContractFoundation,
        stage: &PipelineStageSpec,
    ) -> PipelineStageResult {
        self.seen.lock().unwrap().push((
            project_id.to_string(),
            stage.stage.clone(),
            stage.command.clone(),
        ));
        self.results
            .lock()
            .unwrap()
            .get(&stage.stage)
            .cloned()
            .unwrap_or_else(|| PipelineStageResult {
                stage: stage.stage.clone(),
                status: "success".to_string(),
                command: stage.command.clone(),
                exit_code: Some(0),
                stdout_preview: "ok".to_string(),
                stderr_preview: String::new(),
                duration_ms: 25,
                log_ref: Some(format!("sandbox://pipeline/test/{}.log", stage.stage)),
                artifact_refs: vec![format!(
                    "pipeline_log:{}:sandbox://pipeline/test/{}.log",
                    stage.stage, stage.stage
                )],
                service_id: stage.service_id.clone(),
                required: stage.required,
            })
    }
}

#[derive(Default)]
pub(super) struct FakeWorkerLaunchRuntimeStateStore {
    cooldowns: Mutex<HashSet<String>>,
    running: Mutex<HashSet<String>>,
    finished: Mutex<HashMap<String, String>>,
    claims: Mutex<Vec<String>>,
    clears: Mutex<Vec<String>>,
    refresh_cooldowns: Mutex<Vec<String>>,
    refresh_running: Mutex<Vec<String>>,
}

impl FakeWorkerLaunchRuntimeStateStore {
    pub(super) fn insert_cooldown(&self, conversation_id: &str) {
        self.cooldowns
            .lock()
            .unwrap()
            .insert(conversation_id.to_string());
    }

    pub(super) fn insert_running(&self, conversation_id: &str) {
        self.running
            .lock()
            .unwrap()
            .insert(conversation_id.to_string());
    }

    pub(super) fn insert_finished(&self, conversation_id: &str) {
        self.finished
            .lock()
            .unwrap()
            .insert(conversation_id.to_string(), "msg-1".to_string());
    }

    pub(super) fn has_cooldown(&self, conversation_id: &str) -> bool {
        self.cooldowns.lock().unwrap().contains(conversation_id)
    }

    pub(super) fn has_finished(&self, conversation_id: &str) -> bool {
        self.finished.lock().unwrap().contains_key(conversation_id)
    }

    pub(super) fn claims(&self) -> Vec<String> {
        self.claims.lock().unwrap().clone()
    }

    pub(super) fn clears(&self) -> Vec<String> {
        self.clears.lock().unwrap().clone()
    }

    pub(super) fn refresh_cooldowns(&self) -> Vec<String> {
        self.refresh_cooldowns.lock().unwrap().clone()
    }

    pub(super) fn refresh_running(&self) -> Vec<String> {
        self.refresh_running.lock().unwrap().clone()
    }
}

#[async_trait]
impl WorkerLaunchRuntimeStateStore for FakeWorkerLaunchRuntimeStateStore {
    async fn claim_launch_cooldown(
        &self,
        conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.claims
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        let mut cooldowns = self.cooldowns.lock().unwrap();
        if cooldowns.contains(conversation_id) {
            return Ok(false);
        }
        cooldowns.insert(conversation_id.to_string());
        Ok(true)
    }

    async fn refresh_launch_cooldown(
        &self,
        conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        self.refresh_cooldowns
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        Ok(self.cooldowns.lock().unwrap().contains(conversation_id))
    }

    async fn agent_finished_message_id(&self, conversation_id: &str) -> CoreResult<Option<String>> {
        Ok(self.finished.lock().unwrap().get(conversation_id).cloned())
    }

    async fn agent_running_exists(&self, conversation_id: &str) -> CoreResult<bool> {
        Ok(self.running.lock().unwrap().contains(conversation_id))
    }

    async fn refresh_agent_running_marker(
        &self,
        conversation_id: &str,
        _ttl_seconds: u64,
    ) -> CoreResult<bool> {
        if self.finished.lock().unwrap().contains_key(conversation_id) {
            return Ok(false);
        }
        self.refresh_running
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        Ok(self.running.lock().unwrap().contains(conversation_id))
    }

    async fn clear_reused_session_markers(&self, conversation_id: &str) -> CoreResult<()> {
        self.clears
            .lock()
            .unwrap()
            .push(conversation_id.to_string());
        self.finished.lock().unwrap().remove(conversation_id);
        self.cooldowns.lock().unwrap().remove(conversation_id);
        Ok(())
    }
}

#[derive(Default)]
pub(super) struct FakeWorkerLaunchEventStream {
    entries: Mutex<HashMap<String, Vec<StreamEntry>>>,
}

impl FakeWorkerLaunchEventStream {
    pub(super) fn push(&self, conversation_id: &str, id: &str, payload: Value) {
        self.entries
            .lock()
            .unwrap()
            .entry(conversation_id.to_string())
            .or_default()
            .push(StreamEntry {
                id: id.to_string(),
                payload: payload.to_string(),
            });
    }
}

#[async_trait]
impl WorkerLaunchEventStream for FakeWorkerLaunchEventStream {
    async fn read_after(
        &self,
        conversation_id: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>> {
        let entries = self.entries.lock().unwrap();
        let mut seen_after = after_id.is_empty() || after_id == "0";
        let mut out = Vec::new();
        for entry in entries.get(conversation_id).into_iter().flatten() {
            if !seen_after {
                seen_after = entry.id == after_id;
                continue;
            }
            out.push(entry.clone());
            if out.len() >= limit {
                break;
            }
        }
        Ok(out)
    }
}
