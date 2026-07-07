//! P7 system metadata strangler slice.
//!
//! Rust owns only authenticated `GET /api/v1/system/features` and
//! `GET /api/v1/system/info`. Maintenance status is owned by
//! `maintenance_api`; runtime mutation and unrelated `/system/*` siblings remain
//! Python-owned.

use axum::{routing::get, Json, Router};
use serde::Serialize;

use crate::AppState;

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/system/features", get(list_features))
        .route("/api/v1/system/features/", get(list_features))
        .route("/api/v1/system/info", get(get_system_info))
        .route("/api/v1/system/info/", get(get_system_info))
}

async fn list_features() -> Json<Vec<FeatureInfo>> {
    Json(features_for_edition(
        &system_runtime_config_from_env().edition,
    ))
}

async fn get_system_info() -> Json<SystemInfoResponse> {
    Json(system_info_response(system_runtime_config_from_env()))
}

fn system_info_response(config: SystemRuntimeConfig) -> SystemInfoResponse {
    SystemInfoResponse {
        features: features_for_edition(&config.edition),
        edition: config.edition,
        agent_runtime: AgentRuntimeInfo {
            mode: config.agent_runtime_mode,
        },
        memory_runtime: MemoryRuntimeInfo {
            mode: config.agent_memory_runtime_mode,
            tool_provider_mode: config.agent_memory_tool_provider_mode,
            failure_persistence_enabled: config.agent_memory_failure_persistence_enabled,
        },
    }
}

fn features_for_edition(edition: &str) -> Vec<FeatureInfo> {
    FEATURE_DEFINITIONS
        .iter()
        .map(|definition| FeatureInfo {
            id: definition.id,
            name: definition.name,
            description: definition.description,
            edition: definition.edition,
            enabled: definition.enabled && (definition.edition != "ee" || edition == "ee"),
        })
        .collect()
}

fn system_runtime_config_from_env() -> SystemRuntimeConfig {
    SystemRuntimeConfig {
        edition: env_lower("MEMSTACK_EDITION", "ce"),
        agent_runtime_mode: env_choice("AGENT_RUNTIME_MODE", "auto", &["auto", "ray", "local"]),
        agent_memory_runtime_mode: env_choice(
            "AGENT_MEMORY_RUNTIME_MODE",
            "plugin",
            &["legacy", "dual", "plugin", "disabled"],
        ),
        agent_memory_tool_provider_mode: env_memory_tool_provider_mode(),
        agent_memory_failure_persistence_enabled: env_bool(
            "AGENT_MEMORY_FAILURE_PERSISTENCE_ENABLED",
            true,
        ),
    }
}

fn env_lower(name: &str, default: &str) -> String {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_ascii_lowercase())
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| default.to_string())
}

fn env_choice(name: &str, default: &str, allowed: &[&str]) -> String {
    let value = env_lower(name, default);
    if allowed.contains(&value.as_str()) {
        value
    } else {
        default.to_string()
    }
}

fn env_memory_tool_provider_mode() -> String {
    let value = env_lower("AGENT_MEMORY_TOOL_PROVIDER_MODE", "plugin");
    match value.as_str() {
        "legacy" => "plugin".to_string(),
        "plugin" | "disabled" => value,
        _ => "plugin".to_string(),
    }
}

fn env_bool(name: &str, default: bool) -> bool {
    match env_lower(name, if default { "true" } else { "false" }).as_str() {
        "1" | "true" | "t" | "yes" | "y" | "on" => true,
        "0" | "false" | "f" | "no" | "n" | "off" => false,
        _ => default,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct SystemRuntimeConfig {
    edition: String,
    agent_runtime_mode: String,
    agent_memory_runtime_mode: String,
    agent_memory_tool_provider_mode: String,
    agent_memory_failure_persistence_enabled: bool,
}

impl Default for SystemRuntimeConfig {
    fn default() -> Self {
        Self {
            edition: "ce".to_string(),
            agent_runtime_mode: "auto".to_string(),
            agent_memory_runtime_mode: "plugin".to_string(),
            agent_memory_tool_provider_mode: "plugin".to_string(),
            agent_memory_failure_persistence_enabled: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct SystemInfoResponse {
    edition: String,
    features: Vec<FeatureInfo>,
    agent_runtime: AgentRuntimeInfo,
    memory_runtime: MemoryRuntimeInfo,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct AgentRuntimeInfo {
    mode: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct MemoryRuntimeInfo {
    mode: String,
    tool_provider_mode: String,
    failure_persistence_enabled: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct FeatureInfo {
    id: &'static str,
    name: &'static str,
    description: &'static str,
    edition: &'static str,
    enabled: bool,
}

struct FeatureDefinition {
    id: &'static str,
    name: &'static str,
    description: &'static str,
    edition: &'static str,
    enabled: bool,
}

const FEATURE_DEFINITIONS: &[FeatureDefinition] = &[
    FeatureDefinition {
        id: "gene_market",
        name: "Gene Market",
        description: "Gene marketplace",
        edition: "ce",
        enabled: true,
    },
    FeatureDefinition {
        id: "knowledge_graph",
        name: "Knowledge Graph",
        description: "Neo4j knowledge graph",
        edition: "ce",
        enabled: true,
    },
    FeatureDefinition {
        id: "agent_pool",
        name: "Agent Pool",
        description: "Agent pool management",
        edition: "ce",
        enabled: true,
    },
    FeatureDefinition {
        id: "mcp_tools",
        name: "MCP Tools",
        description: "Model Context Protocol tools",
        edition: "ce",
        enabled: true,
    },
    FeatureDefinition {
        id: "webhooks",
        name: "Webhooks",
        description: "Outbound webhook management",
        edition: "ce",
        enabled: true,
    },
    FeatureDefinition {
        id: "events",
        name: "Events",
        description: "System event logging",
        edition: "ce",
        enabled: true,
    },
    FeatureDefinition {
        id: "advanced_analytics",
        name: "Advanced Analytics",
        description: "Advanced analytics dashboard",
        edition: "ee",
        enabled: true,
    },
    FeatureDefinition {
        id: "sso",
        name: "SSO",
        description: "Single Sign-On",
        edition: "ee",
        enabled: true,
    },
];

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::*;

    #[test]
    fn default_features_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/system_features_response.json"
        ))
        .expect("system features golden must be valid JSON");

        let value = serde_json::to_value(features_for_edition("ce"))
            .expect("system features response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn default_system_info_response_matches_python_shape() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/system_info_response.json"))
                .expect("system info golden must be valid JSON");

        let value = serde_json::to_value(system_info_response(SystemRuntimeConfig::default()))
            .expect("system info response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn ee_features_enable_enterprise_only_items() {
        let features = features_for_edition("ee");
        assert!(features
            .iter()
            .filter(|feature| feature.edition == "ee")
            .all(|feature| feature.enabled));
    }

    #[test]
    fn legacy_memory_tool_provider_mode_normalizes_like_python() {
        assert_eq!(env_choice("AGENT_RUNTIME_MODE", "auto", &["auto"]), "auto");
        assert!(env_bool("__AGISTACK_MISSING_BOOL_FOR_TEST__", true));
    }

    #[test]
    fn router_builds() {
        let _ = router();
    }
}
