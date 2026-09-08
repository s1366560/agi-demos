use super::*;
use agistack_core::{
    knowledge::{
        index::DesiredEmbeddingConfig, processing::ProcessingSource, retrieval::RetrievalRequest,
    },
    ports::{CoreError, CoreResult, ToolDefinition},
};
use serde::Deserialize;
use std::time::Instant;

const TOOLS: &[&str] = &["knowledge_search", "knowledge_source"];

#[derive(Clone)]
struct Reference {
    source: ProcessingSource,
    audit_attempt: u32,
    config: Option<DesiredEmbeddingConfig>,
    input_digest: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Search {
    mode: Mode,
    query: String,
    limit: usize,
    rationale: String,
}
#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Mode {
    Literal,
    Semantic,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    reference: String,
    rationale: String,
}

pub(super) struct KnowledgeToolHost {
    agent_id: String,
    run_revision: Option<u64>,
    state: Arc<LocalRuntimeState>,
    authorization: Arc<RunAuthorization>,
    returned: Mutex<BTreeMap<String, Reference>>,
}

impl KnowledgeToolHost {
    pub(super) fn new(
        state: Arc<LocalRuntimeState>,
        authorization: Arc<RunAuthorization>,
        agent_id: String,
        run_revision: Option<u64>,
    ) -> Self {
        Self {
            agent_id,
            run_revision,
            state,
            authorization,
            returned: Mutex::new(BTreeMap::new()),
        }
    }

    fn admit(
        &self,
        action: &'static str,
    ) -> Result<KnowledgeOperationV2, KnowledgeAuthorityErrorV2> {
        self.authorization.ensure_current(&self.state)?;
        if let Some(id) = &self.authorization.run_id {
            let run = self
                .state
                .session_store
                .run(id)
                .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?
                .ok_or(KnowledgeAuthorityErrorV2::Forbidden)?;
            if Some(run.revision) != self.run_revision {
                return Err(KnowledgeAuthorityErrorV2::ScopeMismatch);
            }
        }

        self.authorization.operation()?.admit_capability(
            &self.state,
            &self.authorization.auth,
            action,
        )
    }

    async fn search(
        &self,
        input: Search,
    ) -> Result<(Value, Vec<(String, Reference)>), KnowledgeAuthorityErrorV2> {
        let action = match input.mode {
            Mode::Literal => "text",
            Mode::Semantic => "semantic",
        };
        let op = self.admit(action)?;
        let auth = &self.authorization.auth;
        let mut references = Vec::new();
        let mut hits = Vec::new();
        match input.mode {
            Mode::Literal => {
                let page = op.search_text(
                    &self.state,
                    auth,
                    &input.query,
                    &RetrievalRequest {
                        source: None,
                        cursor: None,
                        limit: input.limit,
                    },
                )?;
                for hit in page.items {
                    let id = uuid::Uuid::new_v4().to_string();
                    hits.push(json!({"reference":id,"source":hit.source,"audit_attempt":hit.audit_attempt,"title":hit.title}));
                    references.push((
                        id,
                        Reference {
                            source: hit.source,
                            audit_attempt: hit.audit_attempt,
                            config: None,
                            input_digest: None,
                        },
                    ));
                }
            }
            Mode::Semantic => {
                let config =
                    processing_context::with_read_current(&op, &self.state, auth, |clock| {
                        op.authority
                            .repository()
                            .map_err(|_| KnowledgeError::Conflict)?
                            .desired_index_config_durable(&op.scope, clock)?
                            .ok_or(KnowledgeError::Conflict)
                    })?;
                let result = op
                    .semantic_query(&self.state, auth, &config, &input.query, input.limit)
                    .await?;
                for hit in result.hits {
                    let id = uuid::Uuid::new_v4().to_string();
                    hits.push(json!({"reference":id,"source":hit.input.source,"audit_attempt":hit.input.audit_attempt,
                        "input_digest":hit.input.input_digest,"score":hit.score,"build_id":config.build.build_id,"config_revision":config.revision}));
                    references.push((
                        id,
                        Reference {
                            source: hit.input.source,
                            audit_attempt: hit.input.audit_attempt,
                            config: Some(config.clone()),
                            input_digest: Some(hit.input.input_digest),
                        },
                    ));
                }
            }
        }
        self.authorization.ensure_current(&self.state)?;
        Ok((json!({"hits":hits}), references))
    }

    fn source(&self, id: &str) -> Result<Value, KnowledgeAuthorityErrorV2> {
        let reference = self
            .returned
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Forbidden)?
            .get(id)
            .cloned()
            .ok_or(KnowledgeAuthorityErrorV2::Forbidden)?;
        let op = self.admit(if reference.config.is_some() {
            "semantic"
        } else {
            "text"
        })?;
        let auth = &self.authorization.auth;
        let read = |clock: &dyn Fn() -> agistack_core::knowledge::KnowledgeResult<i64>| {
            let repo = op
                .authority
                .repository()
                .map_err(|_| KnowledgeError::Conflict)?;
            if let Some(config) = &reference.config {
                let active = repo.read_active_index_durable(config, clock)?;
                if !active.vectors.iter().any(|vector| {
                    vector.input.source == reference.source
                        && vector.input.audit_attempt == reference.audit_attempt
                        && Some(vector.input.input_digest.as_str())
                            == reference.input_digest.as_deref()
                }) {
                    return Err(KnowledgeError::Conflict);
                }
            }
            repo.source_durable(&op.scope, &reference.source, reference.audit_attempt, clock)
        };
        let hit = if let Some(config) = &reference.config {
            let provider = super::super::indexing::resolve_build(
                &op,
                &self.state,
                auth,
                &config.build,
                false,
            )?;
            super::super::embedding_provider::with_current(
                &op,
                &self.state,
                auth,
                &provider,
                false,
                read,
            )?
        } else {
            processing_context::with_read_current(&op, &self.state, auth, read)?
        };
        self.authorization.ensure_current(&self.state)?;
        Ok(
            json!({"reference":id,"source":hit.source,"audit_attempt":hit.audit_attempt,"title":hit.title,"content":hit.content,
                "input_digest":reference.input_digest,"build_id":reference.config.as_ref().map(|c|&c.build.build_id),
                "config_revision":reference.config.as_ref().map(|c|c.revision)}),
        )
    }

    fn audit(
        &self,
        tool: &str,
        rationale: &str,
        input_reference: Option<&str>,
        input: &Value,
        output: &Value,
        started: Instant,
    ) {
        let sources: Vec<&Value> = match output.get("hits").and_then(Value::as_array) {
            Some(hits) => hits.iter().collect(),
            None if output.get("reference").is_some() => vec![output],
            None => Vec::new(),
        };
        let refs: Vec<_> = sources.into_iter().map(|hit| json!({
            "reference":hit["reference"],"source":hit["source"],"audit_attempt":hit["audit_attempt"],
            "input_digest":hit.get("input_digest"),"build_id":hit.get("build_id"),"config_revision":hit.get("config_revision")
        })).collect();
        let descriptor = self.authorization.lease.descriptor();
        let item = self.state.timeline_item("knowledge_tool_audit", self.authorization.conversation_id.clone(),
            Some(self.authorization.message_id.clone()), None, None,
            json!({"agent_id":self.agent_id,"actor_id":self.authorization.auth.user.user_id,"tool_name":tool,
                "input":input,"input_reference":input_reference,"output_references":refs,"rationale":rationale,
                "status":output.get("status").and_then(Value::as_str).unwrap_or("returned"),
                "scope":{"tenant_id":self.authorization.auth.workspace.tenant_id,"project_id":self.authorization.auth.workspace.project_id,
                    "context_revision":self.authorization.auth.workspace.revision,"generation":descriptor.generation,"digest":descriptor.digest},
                "latency_ms":started.elapsed().as_millis(),"run_id":self.authorization.run_id}));
        self.state
            .append_timeline(&self.authorization.conversation_id, item);
    }
}

#[async_trait]
impl ToolHost for KnowledgeToolHost {
    fn list_tools(&self) -> Vec<String> {
        TOOLS.iter().map(|name| (*name).to_owned()).collect()
    }
    fn tool_definition(&self, name: &str) -> Option<ToolDefinition> {
        let schema = match name {
            "knowledge_search" => json!({"type":"object","additionalProperties":false,
                "properties":{"mode":{"type":"string","enum":["literal","semantic"]},"query":{"type":"string","minLength":1,"maxLength":4096},
                "limit":{"type":"integer","minimum":1,"maximum":100},"rationale":{"type":"string","minLength":1,"maxLength":2000}},
                "required":["mode","query","limit","rationale"]}),
            "knowledge_source" => json!({"type":"object","additionalProperties":false,
                "properties":{"reference":{"type":"string"},"rationale":{"type":"string","minLength":1,"maxLength":2000}},
                "required":["reference","rationale"]}),
            _ => return None,
        };
        Some(ToolDefinition::new(name, "Read current project knowledge. Choose literal or semantic retrieval explicitly; hydrate only a reference returned by this agent in the current run. Explain your decision in rationale.", schema))
    }
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        let started = Instant::now();
        let parse = |e: serde_json::Error| CoreError::Tool(e.to_string());
        let (rationale, input_reference, action, result) = match tool {
            "knowledge_search" => {
                let input: Search = serde_json::from_str(input_json).map_err(parse)?;
                validate_rationale(&input.rationale)?;
                let rationale = input.rationale.clone();
                (
                    rationale,
                    None,
                    match input.mode {
                        Mode::Literal => "text",
                        Mode::Semantic => "semantic",
                    },
                    self.search(input).await,
                )
            }
            "knowledge_source" => {
                let input: Source = serde_json::from_str(input_json).map_err(parse)?;
                validate_rationale(&input.rationale)?;
                let action = self
                    .returned
                    .lock()
                    .map_err(|_| CoreError::Tool("knowledge reference store unavailable".into()))?
                    .get(&input.reference)
                    .map(|r| {
                        if r.config.is_some() {
                            "semantic"
                        } else {
                            "text"
                        }
                    })
                    .unwrap_or("text");
                let result = self
                    .source(&input.reference)
                    .map(|value| (value, Vec::new()));
                (input.rationale, Some(input.reference), action, result)
            }
            _ => return Err(CoreError::Tool("unknown knowledge tool".into())),
        };
        let result = result.and_then(|value| {
            self.admit(action)?;
            Ok(value)
        });
        let audit_result = match &result {
            Ok((v, _)) => v.clone(),
            Err(_) => json!({"status":"rejected"}),
        };
        self.audit(
            tool,
            &rationale,
            input_reference.as_deref(),
            &serde_json::from_str::<Value>(input_json).map_err(parse)?,
            &audit_result,
            started,
        );
        let (value, references) = result.map_err(|e| CoreError::Tool(e.to_string()))?;
        let output = serde_json::to_string(&value).map_err(parse)?;
        self.admit(action)
            .map_err(|e| CoreError::Tool(e.to_string()))?;
        self.returned
            .lock()
            .map_err(|_| CoreError::Tool("knowledge reference store unavailable".into()))?
            .extend(references);
        Ok(output)
    }
}

fn validate_rationale(rationale: &str) -> CoreResult<()> {
    if rationale.trim().is_empty() || rationale.len() > 2000 {
        return Err(CoreError::Tool(
            "rationale must contain 1 to 2000 bytes".into(),
        ));
    }
    Ok(())
}
