//! P7 runtime engine catalog strangler slice.
//!
//! Rust owns only the public static `GET /api/v1/engines` catalog. Sandbox
//! lifecycle, image management, and engine execution remain Python-owned.

use axum::{routing::get, Json, Router};
use serde::Serialize;

use crate::AppState;

pub(crate) fn router_public() -> Router<AppState> {
    Router::new()
        .route("/api/v1/engines", get(list_engines))
        .route("/api/v1/engines/", get(list_engines))
}

async fn list_engines() -> Json<Vec<RuntimeEngineInfo>> {
    Json(RUNTIME_ENGINES.to_vec())
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
struct RuntimeEngineInfo {
    runtime_id: &'static str,
    display_name: &'static str,
    display_description: &'static str,
    display_tags: &'static [&'static str],
    display_powered_by: &'static str,
    order: u8,
    image_registry_key: &'static str,
    default_registry_url: &'static str,
}

const RUNTIME_ENGINES: &[RuntimeEngineInfo] = &[
    RuntimeEngineInfo {
        runtime_id: "python-3.12",
        display_name: "Python 3.12",
        display_description: "CPython 3.12 runtime with scientific computing packages",
        display_tags: &["python", "data-science", "general"],
        display_powered_by: "Docker",
        order: 1,
        image_registry_key: "python",
        default_registry_url: "docker.io/library/python:3.12-slim",
    },
    RuntimeEngineInfo {
        runtime_id: "node-22",
        display_name: "Node.js 22",
        display_description: "Node.js 22 LTS runtime for JavaScript/TypeScript",
        display_tags: &["javascript", "typescript", "web"],
        display_powered_by: "Docker",
        order: 2,
        image_registry_key: "node",
        default_registry_url: "docker.io/library/node:22-slim",
    },
    RuntimeEngineInfo {
        runtime_id: "sandbox-base",
        display_name: "MemStack Sandbox",
        display_description: "Full-featured sandbox with terminal, desktop, and MCP tools",
        display_tags: &["sandbox", "full-stack", "mcp"],
        display_powered_by: "Docker + noVNC",
        order: 3,
        image_registry_key: "sandbox",
        default_registry_url: "memstack/sandbox:latest",
    },
];

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::*;

    #[tokio::test]
    async fn runtime_engine_catalog_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/runtime_engines_response.json"
        ))
        .expect("runtime engines golden must be valid JSON");

        let value =
            serde_json::to_value(list_engines().await.0).expect("runtime engines serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn runtime_engines_are_sorted_and_unique() {
        let mut ids = RUNTIME_ENGINES
            .iter()
            .map(|engine| engine.runtime_id)
            .collect::<Vec<_>>();
        ids.sort_unstable();
        ids.dedup();
        assert_eq!(ids.len(), RUNTIME_ENGINES.len());
        assert!(RUNTIME_ENGINES
            .windows(2)
            .all(|engines| engines[0].order < engines[1].order));
    }

    #[test]
    fn router_builds() {
        let _ = router_public();
    }
}
