use std::sync::Arc;

use agistack_adapters_http_llm::HttpLlm;
use agistack_adapters_postgres::{PgSkillEvolutionRepository, PgSkillRepository};

use crate::skill_api::{
    EngineUnavailableSkillEvolutionExecutor, LlmSkillEvolutionStageEngine,
    PgSkillEvolutionPipelineExecutor, PgSkillEvolutionPipelineStore, SkillEvolutionRunExecutor,
    SkillEvolutionStageEngine,
};

pub(crate) fn skill_evolution_executor_from_env(
    evolution_repo: PgSkillEvolutionRepository,
    skill_repo: PgSkillRepository,
) -> Arc<dyn SkillEvolutionRunExecutor> {
    let Some(engine) = select_skill_evolution_stage_engine() else {
        return Arc::new(EngineUnavailableSkillEvolutionExecutor);
    };
    Arc::new(PgSkillEvolutionPipelineExecutor::with_store(
        Arc::new(PgSkillEvolutionPipelineStore::new(
            evolution_repo,
            skill_repo,
        )),
        engine,
    ))
}

fn select_skill_evolution_stage_engine() -> Option<Arc<dyn SkillEvolutionStageEngine>> {
    if !bool_env("AGISTACK_SKILL_EVOLUTION_ENGINE_READY", false) {
        return None;
    }
    let Some(base) = non_empty_env("AGISTACK_SKILL_EVOLUTION_LLM_BASE_URL")
        .or_else(|| non_empty_env("AGISTACK_LLM_BASE_URL"))
    else {
        eprintln!(
            "[agistack] skill evolution engine readiness requested but no LLM base URL is configured"
        );
        return None;
    };
    let model = non_empty_env("AGISTACK_SKILL_EVOLUTION_LLM_MODEL")
        .or_else(|| non_empty_env("AGISTACK_LLM_MODEL"))
        .unwrap_or_else(|| "gpt-4o-mini".to_string());
    let key = non_empty_env("AGISTACK_SKILL_EVOLUTION_LLM_API_KEY")
        .or_else(|| non_empty_env("AGISTACK_LLM_API_KEY"));
    let mut llm = HttpLlm::new(base, model);
    if let Some(key) = key {
        llm = llm.with_api_key(key);
    }
    eprintln!("[agistack] skill evolution engine: HTTP LLM stage engine enabled");
    Some(Arc::new(LlmSkillEvolutionStageEngine::new(llm)))
}

fn non_empty_env(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn bool_env(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<bool>().ok())
        .unwrap_or(default)
}
