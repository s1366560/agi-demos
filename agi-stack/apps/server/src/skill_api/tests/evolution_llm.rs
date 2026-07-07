use std::collections::VecDeque;
use std::sync::{Arc, Mutex};

use agistack_adapters_postgres::SkillEvolutionPipelineSessionRecord;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use serde_json::json;

use super::super::evolution_llm::{LlmSkillEvolutionStageEngine, SkillEvolutionCompletionClient};
use super::super::evolution_pipeline::{SkillEvolutionEvidenceGroup, SkillEvolutionStageEngine};
use super::super::SkillApiError;

#[derive(Default)]
struct ScriptedCompletionClient {
    responses: Mutex<VecDeque<String>>,
    requests: Mutex<Vec<(String, String)>>,
}

impl ScriptedCompletionClient {
    fn with_responses(responses: impl IntoIterator<Item = &'static str>) -> Self {
        Self {
            responses: Mutex::new(responses.into_iter().map(str::to_string).collect()),
            requests: Mutex::new(Vec::new()),
        }
    }
}

#[async_trait]
impl SkillEvolutionCompletionClient for ScriptedCompletionClient {
    async fn complete(&self, system: &str, user: String) -> Result<String, SkillApiError> {
        self.requests
            .lock()
            .map_err(SkillApiError::internal)?
            .push((system.to_string(), user));
        self.responses
            .lock()
            .map_err(SkillApiError::internal)?
            .pop_front()
            .ok_or_else(|| SkillApiError::internal("missing scripted completion response"))
    }
}

#[tokio::test]
async fn llm_skill_evolution_summarizes_fenced_json_and_preserves_final_response() {
    let client = Arc::new(ScriptedCompletionClient::with_responses([r#"```json
{"trajectory":[{"step":1,"action":"read patch","tool":"read_file","outcome":"success"}],"summary":"The reviewer inspected the patch and found the outcome useful."}
```"#]));
    let engine = LlmSkillEvolutionStageEngine::with_completion_client(
        Arc::clone(&client) as Arc<dyn SkillEvolutionCompletionClient>
    );

    let summary = engine
        .summarize(&sample_pipeline_session("sess-llm-summary"))
        .await
        .unwrap();

    assert_eq!(
        summary.summary,
        "The reviewer inspected the patch and found the outcome useful."
    );
    assert_eq!(
        summary.trajectory["steps"][0]["action"],
        json!("read patch")
    );
    assert_eq!(
        summary.trajectory["final_response"],
        json!("final answer from recorded trace")
    );
    let requests = client.requests.lock().unwrap();
    assert!(requests[0].0.contains("session analyst"));
    assert!(requests[0].1.contains("Skill: code-review"));
    assert!(requests[0].1.contains("Final response:"));
}

#[tokio::test]
async fn llm_skill_evolution_judges_weighted_scores() {
    let client = Arc::new(ScriptedCompletionClient::with_responses([r#"{
  "task_completion": 0.9,
  "response_quality": 0.8,
  "efficiency": 0.7,
  "tool_usage": 0.6,
  "rationale": "The patch review was accurate and concise."
}"#]));
    let engine = LlmSkillEvolutionStageEngine::with_completion_client(
        Arc::clone(&client) as Arc<dyn SkillEvolutionCompletionClient>
    );

    let score = engine
        .judge(&sample_pipeline_session("sess-llm-judge"))
        .await
        .unwrap();

    assert!((score.overall_score - 0.83).abs() < 0.000_001);
    assert_eq!(score.judge_scores["task_completion"], json!(0.9));
    assert_eq!(
        score.judge_scores["rationale"],
        json!("The patch review was accurate and concise.")
    );
}

#[tokio::test]
async fn llm_skill_evolution_falls_back_when_judge_json_is_invalid() {
    let client = Arc::new(ScriptedCompletionClient::with_responses([
        "The session looked decent, but this is not JSON.",
    ]));
    let engine = LlmSkillEvolutionStageEngine::with_completion_client(
        Arc::clone(&client) as Arc<dyn SkillEvolutionCompletionClient>
    );

    let score = engine
        .judge(&sample_pipeline_session("sess-llm-fallback"))
        .await
        .unwrap();

    assert!((score.overall_score - 0.6025).abs() < 0.000_001);
    assert!(score.judge_scores["rationale"]
        .as_str()
        .unwrap()
        .contains("Automatic fallback score"));
}

#[tokio::test]
async fn llm_skill_evolution_maps_description_action_to_candidate_content() {
    let client = Arc::new(ScriptedCompletionClient::with_responses([r#"{
  "action": "optimize_description",
  "rationale": "Users invoke this for patch reviews, not broad audits.",
  "description": "Use when reviewing a focused code patch for regressions."
}"#]));
    let engine = LlmSkillEvolutionStageEngine::with_completion_client(
        Arc::clone(&client) as Arc<dyn SkillEvolutionCompletionClient>
    );

    let decision = engine
        .evolve(&sample_evidence_group())
        .await
        .unwrap()
        .unwrap();

    assert_eq!(decision.action.as_str(), "optimize_description");
    assert_eq!(
        decision.candidate_content.as_deref(),
        Some("Use when reviewing a focused code patch for regressions.")
    );
    assert!(decision
        .rationale
        .as_deref()
        .unwrap_or_default()
        .contains("patch reviews"));
    let requests = client.requests.lock().unwrap();
    assert!(requests[0]
        .1
        .contains("# Code Review\nExisting managed guidance."));
}

#[tokio::test]
async fn llm_skill_evolution_skips_when_candidate_content_is_missing() {
    let client = Arc::new(ScriptedCompletionClient::with_responses([r#"{
  "action": "improve_skill",
  "rationale": "Evidence suggests better instructions."
}"#]));
    let engine = LlmSkillEvolutionStageEngine::with_completion_client(
        Arc::clone(&client) as Arc<dyn SkillEvolutionCompletionClient>
    );

    let decision = engine
        .evolve(&sample_evidence_group())
        .await
        .unwrap()
        .unwrap();

    assert_eq!(decision.action.as_str(), "skip");
    assert!(decision.candidate_content.is_none());
    assert!(decision
        .rationale
        .as_deref()
        .unwrap_or_default()
        .contains("without candidate content"));
}

fn sample_pipeline_session(id: &str) -> SkillEvolutionPipelineSessionRecord {
    SkillEvolutionPipelineSessionRecord {
        id: id.to_string(),
        skill_name: "code-review".to_string(),
        conversation_id: format!("conv-{id}"),
        project_id: Some("project-1".to_string()),
        user_query: "review this patch".to_string(),
        trajectory: Some(json!({
            "steps": [{"step": 1, "tool": "read_file"}],
            "final_response": "final answer from recorded trace",
            "trajectory_source": "agent_execution_events"
        })),
        summary: Some("The session reviewed a patch.".to_string()),
        judge_scores: None,
        overall_score: None,
        success: true,
        execution_time_ms: 100,
        tool_call_count: 2,
        processed: false,
        created_at: test_time(),
    }
}

fn sample_evidence_group() -> SkillEvolutionEvidenceGroup {
    SkillEvolutionEvidenceGroup {
        skill_name: "code-review".to_string(),
        project_id: Some("project-1".to_string()),
        current_skill_content: Some("# Code Review\nExisting managed guidance.".to_string()),
        session_count: 1,
        avg_score: 0.83,
        success_count: 1,
        sessions: vec![sample_pipeline_session("sess-evidence")],
    }
}

fn test_time() -> DateTime<Utc> {
    DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap()
}
