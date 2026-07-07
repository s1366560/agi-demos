use std::sync::Arc;

use agistack_adapters_http_llm::HttpLlm;
use agistack_adapters_postgres::SkillEvolutionPipelineSessionRecord;
use async_trait::async_trait;
use serde::de::DeserializeOwned;
use serde::Deserialize;
use serde_json::{json, Value};

use super::evolution_pipeline::{
    SkillEvolutionDecision, SkillEvolutionDecisionAction, SkillEvolutionEvidenceGroup,
    SkillEvolutionSessionScore, SkillEvolutionSessionSummary, SkillEvolutionStageEngine,
};
use super::SkillApiError;

const SUMMARIZE_SYSTEM_PROMPT: &str = r#"You are a session analyst. Given an agent session trace for a skill execution,
produce a compact JSON summary with two fields:

1. "trajectory": A concise step-by-step trace of what the agent did. Each step is
   { "step": N, "action": "...", "tool": "tool_name or null", "outcome": "success|error|partial" }.
   Include only significant actions (max 15 steps).

2. "summary": A 3-5 sentence analytical summary covering:
   - What was the user's goal?
   - How did the skill help or hinder?
   - What went well and what went wrong?
   - The final outcome.

Return ONLY valid JSON, no markdown fences or extra text.

Example output:
{"trajectory": [{"step": 1, "action": "Read the target file", "tool": "read_file", "outcome": "success"}], "summary": "The user wanted to..."}"#;

const JUDGE_SYSTEM_PROMPT: &str = r#"You are a session quality judge. Evaluate the agent session and score it
on four dimensions (each 0.0-1.0):

1. task_completion (0.55): Did the agent complete the user's request?
2. response_quality (0.30): Was the final response helpful, accurate, and well-structured?
3. efficiency (0.05): Was the task completed with minimal unnecessary steps?
4. tool_usage (0.10): Were tools used appropriately and effectively?

Return ONLY valid JSON with no markdown fences:
{"task_completion": 0.8, "response_quality": 0.7, "efficiency": 0.9, "tool_usage": 0.85, "rationale": "Brief explanation"}"#;

const EVOLVE_SYSTEM_PROMPT: &str = r#"You are a skill evolution specialist. Your job is to analyze real agent usage data
and improve SKILL.md files to make them more effective.

You will receive:
1. The current SKILL.md content for a skill, or a note that no managed skill exists yet
2. Session evidence: summaries of real agent sessions that used this skill, with quality scores

Based on the evidence, decide ONE of these actions:

- "create_skill": No managed skill exists yet, but the session evidence shows a reusable
  workflow worth preserving. Write a complete new SKILL.md.
- "improve_skill": The skill has issues (unclear instructions, missing edge cases, wrong tool choices).
  Rewrite the FULL SKILL.md to address the problems while preserving what works.
- "optimize_description": The skill content is good but the description/trigger patterns
  don't match what users actually need. Only update the description and trigger_patterns.
- "skip": The skill is working well and no changes are needed. This is the DEFAULT -
  only suggest changes when there is CLEAR evidence of problems.

Rules:
1. Be conservative. Only change what needs changing.
2. Preserve the original voice, structure, and formatting conventions.
3. If the evidence shows the skill works well, choose "skip".
4. Keep SKILL.md frontmatter (--- ... ---) intact unless changing description/triggers.
5. Never remove working instructions - only add or refine.
6. If no managed skill exists, choose either "create_skill" or "skip"; do not choose
   "improve_skill" or "optimize_description".

Return ONLY valid JSON (no markdown fences):
{
  "action": "create_skill" | "improve_skill" | "optimize_description" | "skip",
  "rationale": "Why this decision - cite specific session evidence",
  "skill_content": "Full SKILL.md content (for create_skill or improve_skill)",
  "description": "Updated description line (only for optimize_description)"
}"#;

const NO_MANAGED_SKILL_CONTENT: &str = "No managed or file-system SKILL.md exists for this skill name yet. Use action=create_skill only if the evidence supports a reusable workflow.";

const TASK_COMPLETION_WEIGHT: f64 = 0.55;
const RESPONSE_QUALITY_WEIGHT: f64 = 0.30;
const EFFICIENCY_WEIGHT: f64 = 0.05;
const TOOL_USAGE_WEIGHT: f64 = 0.10;

pub(crate) struct LlmSkillEvolutionStageEngine {
    completion: Arc<dyn SkillEvolutionCompletionClient>,
}

impl LlmSkillEvolutionStageEngine {
    pub(crate) fn new(llm: HttpLlm) -> Self {
        Self {
            completion: Arc::new(llm),
        }
    }

    #[cfg(test)]
    pub(crate) fn with_completion_client(
        completion: Arc<dyn SkillEvolutionCompletionClient>,
    ) -> Self {
        Self { completion }
    }
}

#[async_trait]
pub(crate) trait SkillEvolutionCompletionClient: Send + Sync {
    async fn complete(&self, system: &str, user: String) -> Result<String, SkillApiError>;
}

#[async_trait]
impl SkillEvolutionCompletionClient for HttpLlm {
    async fn complete(&self, system: &str, user: String) -> Result<String, SkillApiError> {
        HttpLlm::complete(self, system, user)
            .await
            .map_err(SkillApiError::internal)
    }
}

#[async_trait]
impl SkillEvolutionStageEngine for LlmSkillEvolutionStageEngine {
    async fn summarize(
        &self,
        session: &SkillEvolutionPipelineSessionRecord,
    ) -> Result<SkillEvolutionSessionSummary, SkillApiError> {
        let raw_trajectory = session_trajectory(session);
        let final_response = final_response_from_trajectory(&raw_trajectory);
        let prompt = summarize_prompt(session, &raw_trajectory, &final_response);
        let content = self
            .completion
            .complete(SUMMARIZE_SYSTEM_PROMPT, prompt)
            .await?;
        Ok(
            parse_summary_response(&content, &raw_trajectory, &final_response)
                .unwrap_or_else(|| fallback_summary(session, &raw_trajectory, &content)),
        )
    }

    async fn judge(
        &self,
        session: &SkillEvolutionPipelineSessionRecord,
    ) -> Result<SkillEvolutionSessionScore, SkillApiError> {
        let raw_trajectory = session_trajectory(session);
        let final_response = final_response_from_trajectory(&raw_trajectory);
        let prompt = judge_prompt(session, &raw_trajectory, &final_response);
        let content = self
            .completion
            .complete(JUDGE_SYSTEM_PROMPT, prompt)
            .await?;
        Ok(parse_judge_response(&content).unwrap_or_else(|| fallback_scores(session, &content)))
    }

    async fn evolve(
        &self,
        group: &SkillEvolutionEvidenceGroup,
    ) -> Result<Option<SkillEvolutionDecision>, SkillApiError> {
        let prompt = evolve_prompt(group);
        let content = self
            .completion
            .complete(EVOLVE_SYSTEM_PROMPT, prompt)
            .await?;
        Ok(Some(parse_evolution_response(&content).unwrap_or_else(|| {
            SkillEvolutionDecision {
                action: SkillEvolutionDecisionAction::Skip,
                rationale: Some(format!(
                    "Model response was not valid evolution JSON; no change proposed. Raw model response: {}",
                    truncate_chars(&content, 300)
                )),
                candidate_content: None,
            }
        })))
    }
}

#[derive(Debug, Deserialize)]
struct SummaryPayload {
    #[serde(default)]
    trajectory: Option<Value>,
    #[serde(default)]
    summary: Option<String>,
}

#[derive(Debug, Deserialize)]
struct JudgePayload {
    #[serde(default)]
    task_completion: Option<f64>,
    #[serde(default)]
    response_quality: Option<f64>,
    #[serde(default)]
    efficiency: Option<f64>,
    #[serde(default)]
    tool_usage: Option<f64>,
    #[serde(default)]
    rationale: Option<String>,
}

#[derive(Debug, Deserialize)]
struct EvolutionPayload {
    #[serde(default)]
    action: Option<String>,
    #[serde(default)]
    rationale: Option<String>,
    #[serde(default)]
    skill_content: Option<String>,
    #[serde(default)]
    description: Option<String>,
}

#[derive(Debug, Clone, Copy)]
struct ScoreDimension(f64);

impl ScoreDimension {
    fn parse(raw: Option<f64>, default: f64) -> Option<Self> {
        let value = raw.unwrap_or(default);
        if value.is_finite() && (0.0..=1.0).contains(&value) {
            Some(Self(value))
        } else {
            None
        }
    }

    fn value(self) -> f64 {
        self.0
    }
}

fn summarize_prompt(
    session: &SkillEvolutionPipelineSessionRecord,
    raw_trajectory: &Value,
    final_response: &str,
) -> String {
    format!(
        "Skill: {}\nUser query: {}\nSuccess: {}\nTool calls: {}\nExecution time: {}ms\n\nFinal response:\n{}\n\nRaw trace steps:\n{}",
        session.skill_name,
        truncate_chars(&session.user_query, 1000),
        session.success,
        session.tool_call_count,
        session.execution_time_ms,
        truncate_chars(final_response, 2000),
        steps_json(raw_trajectory)
    )
}

fn judge_prompt(
    session: &SkillEvolutionPipelineSessionRecord,
    raw_trajectory: &Value,
    final_response: &str,
) -> String {
    format!(
        "Skill: {}\nUser query: {}\nSuccess: {}\nTool calls: {}\nExecution time: {}ms\n\nSummary: {}\n\nFinal response:\n{}\n\nTrajectory: {}",
        session.skill_name,
        truncate_chars(&session.user_query, 1000),
        session.success,
        session.tool_call_count,
        session.execution_time_ms,
        session.summary.as_deref().unwrap_or_default(),
        truncate_chars(final_response, 2000),
        steps_json(raw_trajectory)
    )
}

fn evolve_prompt(group: &SkillEvolutionEvidenceGroup) -> String {
    let success_rate = if group.session_count > 0 {
        (group.success_count as f64 / group.session_count as f64) * 100.0
    } else {
        0.0
    };
    let current_skill_content = group
        .current_skill_content
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(|value| truncate_chars(value, 12_000))
        .unwrap_or_else(|| NO_MANAGED_SKILL_CONTENT.to_string());
    format!(
        "Current SKILL.md for '{}':\n```markdown\n{}\n```\n\nSession evidence ({} sessions, avg score {:.2}, success rate {:.1}%):\n{}\n\nExisting skill names (avoid conflicts):\n",
        group.skill_name,
        current_skill_content,
        group.session_count,
        group.avg_score,
        success_rate,
        evidence_text(group)
    )
}

fn evidence_text(group: &SkillEvolutionEvidenceGroup) -> String {
    let mut lines = String::new();
    for (index, session) in group.sessions.iter().take(20).enumerate() {
        let score = session
            .overall_score
            .map(|value| format!("{value:.2}"))
            .unwrap_or_else(|| "n/a".to_string());
        let summary = session
            .summary
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(|value| truncate_chars(value, 600))
            .unwrap_or_else(|| "No summary recorded.".to_string());
        lines.push_str(&format!(
            "- Session {}: score={}, success={}, tools={}, query=\"{}\"\n  Summary: {}\n",
            index + 1,
            score,
            session.success,
            session.tool_call_count,
            truncate_chars(&session.user_query, 300),
            summary
        ));
    }
    if group.sessions.len() > 20 {
        lines.push_str(&format!(
            "- Additional sessions omitted from prompt: {}\n",
            group.sessions.len() - 20
        ));
    }
    lines
}

fn parse_summary_response(
    content: &str,
    raw_trajectory: &Value,
    final_response: &str,
) -> Option<SkillEvolutionSessionSummary> {
    let payload: SummaryPayload = parse_json_payload(content)?;
    let mut trajectory = normalize_trajectory(
        payload.trajectory.unwrap_or_else(|| raw_trajectory.clone()),
        raw_trajectory,
    );
    preserve_trajectory_metadata(&mut trajectory, raw_trajectory, final_response);
    Some(SkillEvolutionSessionSummary {
        trajectory,
        summary: payload.summary.unwrap_or_default(),
    })
}

fn fallback_summary(
    session: &SkillEvolutionPipelineSessionRecord,
    raw_trajectory: &Value,
    content: &str,
) -> SkillEvolutionSessionSummary {
    let final_response = final_response_from_trajectory(raw_trajectory);
    let mut trajectory = normalize_trajectory(raw_trajectory.clone(), raw_trajectory);
    preserve_trajectory_metadata(&mut trajectory, raw_trajectory, &final_response);
    SkillEvolutionSessionSummary {
        trajectory,
        summary: format!(
            "Automatic fallback summary: the summarizer model did not return valid JSON for skill '{}' on conversation '{}'. Success={}, tool calls={}, execution time={}ms. Raw model response: {}",
            session.skill_name,
            session.conversation_id,
            session.success,
            session.tool_call_count,
            session.execution_time_ms,
            truncate_chars(content, 300)
        ),
    }
}

fn parse_judge_response(content: &str) -> Option<SkillEvolutionSessionScore> {
    let payload: JudgePayload = parse_json_payload(content)?;
    let task_completion = ScoreDimension::parse(payload.task_completion, 0.5)?;
    let response_quality = ScoreDimension::parse(payload.response_quality, 0.5)?;
    let efficiency = ScoreDimension::parse(payload.efficiency, 0.5)?;
    let tool_usage = ScoreDimension::parse(payload.tool_usage, 0.5)?;
    let rationale = payload.rationale.unwrap_or_default();
    score_from_dimensions(
        task_completion,
        response_quality,
        efficiency,
        tool_usage,
        rationale,
    )
}

fn fallback_scores(
    session: &SkillEvolutionPipelineSessionRecord,
    content: &str,
) -> SkillEvolutionSessionScore {
    let (task_completion, response_quality, efficiency, tool_usage, rationale) = if session.success
    {
        (
            ScoreDimension(0.65),
            ScoreDimension(0.55),
            ScoreDimension(0.50),
            ScoreDimension(if session.tool_call_count > 0 { 0.55 } else { 0.40 }),
            format!(
                "Automatic fallback score: judge model did not return valid JSON; score derived conservatively from recorded success/tool metadata. Raw model response: {}",
                truncate_chars(content, 300)
            ),
        )
    } else {
        (
            ScoreDimension(0.25),
            ScoreDimension(0.25),
            ScoreDimension(0.35),
            ScoreDimension(if session.tool_call_count > 0 { 0.35 } else { 0.20 }),
            format!(
                "Automatic fallback score: judge model did not return valid JSON and the session was recorded as unsuccessful. Raw model response: {}",
                truncate_chars(content, 300)
            ),
        )
    };
    score_from_dimensions(
        task_completion,
        response_quality,
        efficiency,
        tool_usage,
        rationale,
    )
    .unwrap_or_else(|| SkillEvolutionSessionScore {
        judge_scores: json!({}),
        overall_score: 0.0,
    })
}

fn score_from_dimensions(
    task_completion: ScoreDimension,
    response_quality: ScoreDimension,
    efficiency: ScoreDimension,
    tool_usage: ScoreDimension,
    rationale: String,
) -> Option<SkillEvolutionSessionScore> {
    let overall = task_completion.value() * TASK_COMPLETION_WEIGHT
        + response_quality.value() * RESPONSE_QUALITY_WEIGHT
        + efficiency.value() * EFFICIENCY_WEIGHT
        + tool_usage.value() * TOOL_USAGE_WEIGHT;
    SkillEvolutionSessionScore::new(
        json!({
            "task_completion": task_completion.value(),
            "response_quality": response_quality.value(),
            "efficiency": efficiency.value(),
            "tool_usage": tool_usage.value(),
            "rationale": rationale,
        }),
        overall,
    )
    .ok()
}

fn parse_evolution_response(content: &str) -> Option<SkillEvolutionDecision> {
    let payload: EvolutionPayload = parse_json_payload(content)?;
    let action = action_from_wire(payload.action.as_deref());
    let rationale = clean_optional_text(payload.rationale);
    let candidate_content = match action {
        SkillEvolutionDecisionAction::CreateSkill | SkillEvolutionDecisionAction::ImproveSkill => {
            clean_optional_text(payload.skill_content)
        }
        SkillEvolutionDecisionAction::OptimizeDescription => {
            clean_optional_text(payload.description)
        }
        SkillEvolutionDecisionAction::Skip => None,
    };
    if requires_candidate(action) && candidate_content.is_none() {
        return Some(SkillEvolutionDecision {
            action: SkillEvolutionDecisionAction::Skip,
            rationale: Some(format!(
                "Model selected '{}' without candidate content; skipping until a complete candidate is produced.{}",
                action.as_str(),
                rationale
                    .as_deref()
                    .map(|value| format!(" Model rationale: {value}"))
                    .unwrap_or_default()
            )),
            candidate_content: None,
        });
    }
    Some(SkillEvolutionDecision {
        action,
        rationale,
        candidate_content,
    })
}

fn requires_candidate(action: SkillEvolutionDecisionAction) -> bool {
    matches!(
        action,
        SkillEvolutionDecisionAction::CreateSkill
            | SkillEvolutionDecisionAction::ImproveSkill
            | SkillEvolutionDecisionAction::OptimizeDescription
    )
}

fn action_from_wire(raw: Option<&str>) -> SkillEvolutionDecisionAction {
    match raw {
        Some("create_skill") => SkillEvolutionDecisionAction::CreateSkill,
        Some("improve_skill") => SkillEvolutionDecisionAction::ImproveSkill,
        Some("optimize_description") => SkillEvolutionDecisionAction::OptimizeDescription,
        Some("skip") | None => SkillEvolutionDecisionAction::Skip,
        Some(_) => SkillEvolutionDecisionAction::Skip,
    }
}

fn clean_optional_text(raw: Option<String>) -> Option<String> {
    raw.map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn parse_json_payload<T>(content: &str) -> Option<T>
where
    T: DeserializeOwned,
{
    serde_json::from_str(&clean_json_payload(content)).ok()
}

fn clean_json_payload(content: &str) -> String {
    let mut text = content.trim().to_string();
    while let Some(after_think) = strip_leading_think_block(&text) {
        text = after_think.trim().to_string();
    }
    if text.starts_with("```") {
        let mut lines: Vec<&str> = text.lines().collect();
        if lines
            .first()
            .is_some_and(|line| line.trim_start().starts_with("```"))
        {
            lines.remove(0);
        }
        if lines.last().is_some_and(|line| line.trim() == "```") {
            lines.pop();
        }
        text = lines.join("\n").trim().to_string();
    }
    match (text.find('{'), text.rfind('}')) {
        (Some(start), Some(end)) if end > start => text[start..=end].to_string(),
        _ => text,
    }
}

fn strip_leading_think_block(text: &str) -> Option<&str> {
    let rest = text.trim_start().strip_prefix("<think>")?;
    let (_, after) = rest.split_once("</think>")?;
    Some(after)
}

fn session_trajectory(session: &SkillEvolutionPipelineSessionRecord) -> Value {
    session.trajectory.clone().unwrap_or_else(|| json!({}))
}

fn normalize_trajectory(candidate: Value, raw_trajectory: &Value) -> Value {
    match candidate {
        Value::Array(steps) => json!({ "steps": steps }),
        Value::Object(_) => candidate,
        _ => match raw_trajectory {
            Value::Object(_) => raw_trajectory.clone(),
            _ => json!({}),
        },
    }
}

fn preserve_trajectory_metadata(
    trajectory: &mut Value,
    raw_trajectory: &Value,
    final_response: &str,
) {
    let Some(object) = trajectory.as_object_mut() else {
        return;
    };
    let has_final_response = object
        .get("final_response")
        .map(value_to_trimmed_string)
        .is_some_and(|value| !value.is_empty());
    if !has_final_response && !final_response.is_empty() {
        object.insert(
            "final_response".to_string(),
            Value::String(truncate_chars(final_response, 2000)),
        );
    }
    if let Some(source) = raw_trajectory.get("trajectory_source") {
        object
            .entry("trajectory_source".to_string())
            .or_insert_with(|| source.clone());
    }
}

fn final_response_from_trajectory(trajectory: &Value) -> String {
    trajectory
        .get("final_response")
        .map(value_to_trimmed_string)
        .unwrap_or_default()
}

fn steps_json(trajectory: &Value) -> String {
    trajectory
        .get("steps")
        .map(|steps| serde_json::to_string(steps).unwrap_or_else(|_| "[]".to_string()))
        .unwrap_or_else(|| "[]".to_string())
}

fn value_to_trimmed_string(value: &Value) -> String {
    match value {
        Value::String(text) => text.trim().to_string(),
        Value::Null => String::new(),
        other => other.to_string(),
    }
}

fn truncate_chars(value: &str, max_chars: usize) -> String {
    value.chars().take(max_chars).collect()
}
