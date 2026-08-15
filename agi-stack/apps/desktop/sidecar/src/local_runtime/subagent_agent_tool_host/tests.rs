use std::{
    collections::VecDeque,
    sync::{Arc, Mutex},
};

use agistack_adapters_mem::{FixedClock, InMemoryCheckpointStore, ScriptedLlm};
use agistack_core::{
    agent::{react::ReActEngine, types::AgentAction},
    model::Episode,
    ports::{CoreError, CoreResult, LlmPort, MemoryDraft, ToolHost},
};
use async_trait::async_trait;
use serde_json::{json, Value};

use super::*;
use crate::local_runtime::tool_authority::ToolEffect;

struct EmptyToolHost;

#[async_trait]
impl ToolHost for EmptyToolHost {
    fn list_tools(&self) -> Vec<String> {
        Vec::new()
    }

    async fn call(&self, tool: &str, _input_json: &str) -> CoreResult<String> {
        Err(CoreError::Tool(format!("unexpected tool: {tool}")))
    }
}

#[derive(Default)]
struct RecordingLifecycleObserver {
    started: Mutex<Vec<LifecyclePayloadMetadata>>,
    completed: Mutex<Vec<LifecyclePayloadMetadata>>,
}

impl SubagentLifecycleObserver for RecordingLifecycleObserver {
    fn on_started(
        &self,
        _subagent_id: &str,
        _subagent_name: &str,
        _subagent_display_name: &str,
        task: &LifecyclePayloadMetadata,
    ) {
        self.started
            .lock()
            .expect("record lifecycle start")
            .push(task.clone());
    }

    fn on_completed(
        &self,
        _subagent_id: &str,
        _subagent_name: &str,
        _subagent_display_name: &str,
        result: &LifecyclePayloadMetadata,
        _success: bool,
        _execution_time_ms: u64,
    ) {
        self.completed
            .lock()
            .expect("record lifecycle completion")
            .push(result.clone());
    }
}

struct SecretFailingLlm;

#[async_trait]
impl LlmPort for SecretFailingLlm {
    async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
        Err(CoreError::Llm("child-error-secret".to_string()))
    }

    async fn decide(
        &self,
        _goal: &str,
        _round: u64,
        _transcript: &[agistack_core::agent::types::TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        Err(CoreError::Llm("child-error-secret".to_string()))
    }
}

struct SequencedFinishLlm {
    answers: Mutex<VecDeque<String>>,
}

impl SequencedFinishLlm {
    fn new(answers: impl IntoIterator<Item = &'static str>) -> Self {
        Self {
            answers: Mutex::new(answers.into_iter().map(str::to_string).collect()),
        }
    }
}

#[async_trait]
impl LlmPort for SequencedFinishLlm {
    async fn extract_memory(&self, _episode: &Episode) -> CoreResult<MemoryDraft> {
        Err(CoreError::Llm(
            "SequencedFinishLlm does not extract memory".to_string(),
        ))
    }

    async fn decide(
        &self,
        _goal: &str,
        _round: u64,
        _transcript: &[agistack_core::agent::types::TranscriptEntry],
        _available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        let answer = self
            .answers
            .lock()
            .expect("sequenced answers")
            .pop_front()
            .ok_or_else(|| CoreError::Llm("sequenced answers exhausted".to_string()))?;
        Ok(AgentAction::Finish { answer })
    }
}

fn parent_agent(allowed_subagents: Value) -> Value {
    json!({
        "id": "qa-read-agent",
        "name": "qa-read-agent",
        "display_name": "QA Read Agent",
        "enabled": true,
        "status": "active",
        "can_spawn": true,
        "spawn_policy": { "allowed_subagents": allowed_subagents },
    })
}

fn subagent(id: &str, project_id: Value, status: &str, enabled: bool) -> Value {
    json!({
        "id": id,
        "name": id,
        "display_name": "QA Path Reader",
        "project_id": project_id,
        "status": status,
        "enabled": enabled,
        "allowed_tools": ["read", "glob", "grep"],
        "allowed_skills": [],
        "allowed_mcp_servers": [],
    })
}

fn target(resource: Value) -> SubagentToolTarget {
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "README evidence verified".to_string(),
        }])),
        Arc::new(EmptyToolHost),
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(FixedClock(1_000)),
    );
    SubagentToolTarget::new(
        resource,
        ToolEffect::Read,
        engine,
        "local-project".to_string(),
        "run-qa-read".to_string(),
        1,
    )
    .expect("valid SubAgent target")
}

fn target_with_runtime(
    resource: Value,
    llm: Arc<dyn LlmPort>,
    checkpoints: Arc<dyn agistack_core::ports::CheckpointStore>,
) -> SubagentToolTarget {
    target_with_runtime_at_revision(resource, llm, checkpoints, 1)
}

fn target_with_runtime_at_revision(
    resource: Value,
    llm: Arc<dyn LlmPort>,
    checkpoints: Arc<dyn agistack_core::ports::CheckpointStore>,
    run_revision: u64,
) -> SubagentToolTarget {
    let engine = ReActEngine::new(
        llm,
        Arc::new(EmptyToolHost),
        checkpoints,
        Arc::new(FixedClock(1_000)),
    );
    SubagentToolTarget::new(
        resource,
        ToolEffect::Read,
        engine,
        "local-project".to_string(),
        "run-qa-read".to_string(),
        run_revision,
    )
    .expect("valid runtime-backed SubAgent target")
}

async fn authorized_call(
    host: &SubagentAgentToolHost,
    invocation_id: &str,
    run_revision: u64,
    input_json: &str,
) -> CoreResult<String> {
    authorized_tool_host::with_authorized_invocation_context(
        authorized_tool_host::AuthorizedInvocationContext {
            invocation_id: invocation_id.to_string(),
            run_id: "run-qa-read".to_string(),
            run_revision,
        },
        host.call(SUBAGENT_TOOL_NAME, input_json),
    )
    .await
}

#[test]
fn authorization_selects_only_active_visible_allowlisted_subagents() {
    let agent = parent_agent(json!([
        "qa-path-reader",
        "foreign-reader",
        "disabled-reader"
    ]));
    let resources = vec![
        subagent("qa-path-reader", json!("local-project"), "active", true),
        subagent("foreign-reader", json!("other-project"), "active", true),
        subagent("disabled-reader", json!("local-project"), "disabled", false),
        subagent("not-allowlisted", Value::Null, "active", true),
    ];

    let authorized = authorized_subagent_resources(&agent, &resources, "local-project")
        .expect("valid spawn authority");

    assert_eq!(authorized.len(), 1);
    assert_eq!(authorized[0]["id"], "qa-path-reader");
}

#[test]
fn authorization_fails_closed_for_missing_or_malformed_spawn_policy() {
    for agent in [
        json!({ "id": "missing-can-spawn" }),
        json!({ "id": "missing-policy", "can_spawn": true }),
        json!({
            "id": "malformed-allowlist",
            "can_spawn": true,
            "spawn_policy": { "allowed_subagents": "qa-path-reader" },
        }),
    ] {
        assert!(authorized_subagent_resources(&agent, &[], "local-project").is_err());
    }
}

#[tokio::test]
async fn structured_subagent_tool_runs_the_exact_authorized_target() {
    let host = SubagentAgentToolHost::new(vec![target(subagent(
        "qa-path-reader",
        json!("local-project"),
        "active",
        true,
    ))])
    .expect("SubAgent host");

    let output = authorized_call(
        &host,
        "invocation-readme",
        1,
        &json!({
            "subagent_id": "qa-path-reader",
            "task": "Inspect README.md and report direct evidence",
        })
        .to_string(),
    )
    .await
    .expect("authorized delegation");
    let output: Value = serde_json::from_str(&output).expect("structured tool output");

    assert_eq!(host.list_tools(), [SUBAGENT_TOOL_NAME]);
    assert_eq!(
        host.authority_metadata_by_name()[SUBAGENT_TOOL_NAME].effect,
        ToolEffect::Read
    );
    assert_eq!(output["subagent_id"], "qa-path-reader");
    assert_eq!(output["status"], "completed");
    assert_eq!(output["content"], "README evidence verified");

    let compatible_name_output = authorized_call(
        &host,
        "invocation-cargo",
        1,
        &json!({
            "subagent_name": "QA Path Reader",
            "task": "Inspect Cargo.toml and report direct evidence",
        })
        .to_string(),
    )
    .await
    .expect("uniquely authorized name delegation");
    let compatible_name_output: Value =
        serde_json::from_str(&compatible_name_output).expect("structured name output");
    assert_eq!(compatible_name_output["subagent_id"], "qa-path-reader");

    let model_alias_output = authorized_call(
        &host,
        "invocation-model-alias",
        1,
        &json!({
            "agent": "QA Path Reader",
            "task": "Inspect the model-facing alias",
        })
        .to_string(),
    )
    .await
    .expect("model-facing agent alias delegation");
    let model_alias_output: Value =
        serde_json::from_str(&model_alias_output).expect("structured alias output");
    assert_eq!(model_alias_output["subagent_id"], "qa-path-reader");
}

#[tokio::test]
async fn structured_subagent_tool_rejects_unlisted_and_ambiguous_targets() {
    let mut same_display_name =
        subagent("qa-path-reader-2", json!("local-project"), "active", true);
    same_display_name["name"] = json!("qa-path-reader-secondary");
    let host = SubagentAgentToolHost::new(vec![
        target(subagent(
            "qa-path-reader",
            json!("local-project"),
            "active",
            true,
        )),
        target(same_display_name),
    ])
    .expect("SubAgent host");

    for input in [
        json!({ "subagent_name": "not-allowlisted", "task": "inspect" }),
        json!({ "subagent_name": "QA Path Reader", "task": "inspect" }),
        json!({
            "subagent_id": "qa-path-reader",
            "subagent_name": "qa-path-reader-secondary",
            "task": "inspect",
        }),
        json!({ "subagent_name": "qa-path-reader", "task": "" }),
        json!({
            "subagent_name": "qa-path-reader",
            "task": "inspect",
            "unexpected": true,
        }),
    ] {
        let error = authorized_call(&host, "invocation-rejected", 1, &input.to_string())
            .await
            .expect_err("delegation must fail closed");
        assert!(matches!(error, CoreError::Tool(_)));
    }
}

#[tokio::test]
async fn lifecycle_observer_never_receives_raw_task_or_child_answer() {
    let lifecycle = Arc::new(RecordingLifecycleObserver::default());
    let checkpoints: Arc<dyn agistack_core::ports::CheckpointStore> =
        Arc::new(InMemoryCheckpointStore::new());
    let host = SubagentAgentToolHost::new(vec![target_with_runtime(
        subagent("qa-path-reader", json!("local-project"), "active", true),
        Arc::new(ScriptedLlm::new(vec![AgentAction::Finish {
            answer: "child-answer-secret".to_string(),
        }])),
        checkpoints,
    )])
    .expect("SubAgent host")
    .with_lifecycle_observer(lifecycle.clone());

    let output = authorized_call(
        &host,
        "invocation-lifecycle-success",
        1,
        &json!({
            "subagent_id": "qa-path-reader",
            "task": "inspect using task-secret",
        })
        .to_string(),
    )
    .await
    .expect("authorized delegation");

    assert!(output.contains("child-answer-secret"));
    let lifecycle_payload = format!(
        "{:?}{:?}",
        lifecycle.started.lock().expect("started lifecycle"),
        lifecycle.completed.lock().expect("completed lifecycle")
    );
    assert!(!lifecycle_payload.contains("task-secret"));
    assert!(!lifecycle_payload.contains("child-answer-secret"));
    assert_eq!(
        lifecycle.started.lock().expect("started lifecycle")[0].bytes,
        "inspect using task-secret".len()
    );
    assert_eq!(
        lifecycle.completed.lock().expect("completed lifecycle")[0].bytes,
        "child-answer-secret".len()
    );
}

#[tokio::test]
async fn lifecycle_and_tool_error_never_receive_raw_child_error() {
    let lifecycle = Arc::new(RecordingLifecycleObserver::default());
    let checkpoints: Arc<dyn agistack_core::ports::CheckpointStore> =
        Arc::new(InMemoryCheckpointStore::new());
    let host = SubagentAgentToolHost::new(vec![target_with_runtime(
        subagent("qa-path-reader", json!("local-project"), "active", true),
        Arc::new(SecretFailingLlm),
        checkpoints,
    )])
    .expect("SubAgent host")
    .with_lifecycle_observer(lifecycle.clone());

    let error = authorized_call(
        &host,
        "invocation-lifecycle-error",
        1,
        &json!({
            "subagent_id": "qa-path-reader",
            "task": "inspect without leaking errors",
        })
        .to_string(),
    )
    .await
    .expect_err("child LLM must fail");

    let rendered_error = error.to_string();
    assert!(rendered_error.contains("SubAgent execution failed"));
    assert!(!rendered_error.contains("child-error-secret"));
    assert!(!rendered_error.contains("digest"));
    let lifecycle_payload = format!(
        "{:?}",
        lifecycle.completed.lock().expect("completed lifecycle")
    );
    assert!(!lifecycle_payload.contains("child-error-secret"));
}

#[tokio::test]
async fn trim_equivalent_tasks_from_distinct_invocations_do_not_share_child_checkpoint() {
    let checkpoints: Arc<dyn agistack_core::ports::CheckpointStore> =
        Arc::new(InMemoryCheckpointStore::new());
    let host = SubagentAgentToolHost::new(vec![target_with_runtime(
        subagent("qa-path-reader", json!("local-project"), "active", true),
        Arc::new(SequencedFinishLlm::new([
            "first invocation",
            "second invocation",
        ])),
        checkpoints,
    )])
    .expect("SubAgent host");

    let first = authorized_call(
        &host,
        "invocation-trim-a",
        1,
        r#"{"subagent_id":"qa-path-reader","task":"inspect README"}"#,
    )
    .await
    .expect("first delegation");
    let second = authorized_call(
        &host,
        "invocation-trim-b",
        1,
        r#"{"subagent_id":"qa-path-reader","task":" inspect README "}"#,
    )
    .await
    .expect("second delegation");

    assert!(first.contains("first invocation"));
    assert!(second.contains("second invocation"));
}

#[tokio::test]
async fn same_invocation_retry_reuses_child_checkpoint() {
    let checkpoints: Arc<dyn agistack_core::ports::CheckpointStore> =
        Arc::new(InMemoryCheckpointStore::new());
    let host = SubagentAgentToolHost::new(vec![target_with_runtime(
        subagent("qa-path-reader", json!("local-project"), "active", true),
        Arc::new(SequencedFinishLlm::new([
            "first invocation",
            "next invocation",
        ])),
        checkpoints,
    )])
    .expect("SubAgent host");
    let input = r#"{"subagent_id":"qa-path-reader","task":"inspect README"}"#;

    let first = authorized_call(&host, "invocation-stable", 1, input)
        .await
        .expect("first delegation");
    let retry = authorized_call(&host, "invocation-stable", 1, input)
        .await
        .expect("stable retry");
    let next = authorized_call(&host, "invocation-next", 1, input)
        .await
        .expect("distinct delegation");

    assert!(first.contains("first invocation"));
    assert!(retry.contains("first invocation"));
    assert!(next.contains("next invocation"));
}

#[tokio::test]
async fn run_revisions_do_not_share_child_checkpoint() {
    let checkpoints: Arc<dyn agistack_core::ports::CheckpointStore> =
        Arc::new(InMemoryCheckpointStore::new());
    let llm: Arc<dyn LlmPort> = Arc::new(SequencedFinishLlm::new(["revision one", "revision two"]));
    let resource = subagent("qa-path-reader", json!("local-project"), "active", true);
    let revision_one = SubagentAgentToolHost::new(vec![target_with_runtime_at_revision(
        resource.clone(),
        llm.clone(),
        checkpoints.clone(),
        1,
    )])
    .expect("revision one host");
    let revision_two = SubagentAgentToolHost::new(vec![target_with_runtime_at_revision(
        resource,
        llm,
        checkpoints,
        2,
    )])
    .expect("revision two host");
    let input = r#"{"subagent_id":"qa-path-reader","task":"inspect README"}"#;

    let first = authorized_call(&revision_one, "invocation-shared", 1, input)
        .await
        .expect("revision one delegation");
    let second = authorized_call(&revision_two, "invocation-shared", 2, input)
        .await
        .expect("revision two delegation");

    assert!(first.contains("revision one"));
    assert!(second.contains("revision two"));
}
