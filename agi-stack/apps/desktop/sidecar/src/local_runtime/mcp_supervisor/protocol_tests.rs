use std::{collections::BTreeMap, path::PathBuf};

use serde_json::json;

use super::{McpScope, McpServerDefinitionInput, McpSupervisor, McpTransport, SupervisorLimits};
use crate::local_runtime::DesktopSessionStore;

#[path = "protocol_candidate_tests.rs"]
mod candidates;

struct Fixture {
    root: PathBuf,
    supervisor: McpSupervisor,
    scope: McpScope,
    server_id: String,
}

impl Fixture {
    fn new(mode: &str, aggregate_limit: usize) -> Self {
        let root = std::env::temp_dir().join(format!("mcp-protocol-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&root).unwrap();
        let script = root.join("server.py");
        std::fs::write(&script, include_str!("protocol_fixture.py")).unwrap();
        let python = std::env::split_paths(&std::env::var_os("PATH").unwrap())
            .map(|entry| entry.join("python3"))
            .find(|path| path.is_file())
            .unwrap()
            .canonicalize()
            .unwrap();
        let supervisor = McpSupervisor::new(
            DesktopSessionStore::in_memory().unwrap(),
            root.clone(),
            None,
            SupervisorLimits {
                max_aggregate_bytes: aggregate_limit,
                ..Default::default()
            },
        )
        .unwrap();
        let scope = McpScope {
            tenant_id: "test-tenant".into(),
            project_id: "test-project".into(),
        };
        let server = supervisor
            .create_server(
                &scope,
                McpServerDefinitionInput {
                    name: "pagination-fixture".into(),
                    description: None,
                    transport: McpTransport::Stdio,
                    command: vec![
                        python.to_string_lossy().into_owned(),
                        script.to_string_lossy().into_owned(),
                        mode.into(),
                    ],
                    cwd: Some(".".into()),
                    vault_env_refs: BTreeMap::new(),
                    enabled: true,
                },
                "create",
            )
            .unwrap();
        Self {
            root,
            supervisor,
            scope,
            server_id: server.id,
        }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        if let Ok(Some(server)) = self.supervisor.server(&self.scope, &self.server_id) {
            let _ = self.supervisor.delete_server(
                &self.scope,
                &self.server_id,
                server.revision,
                "cleanup",
            );
        }
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[tokio::test]
async fn real_stdio_collections_follow_opaque_cursors_and_preserve_prompt_content() {
    let f = Fixture::new("normal", 4 * 1024 * 1024);
    let tools = f
        .supervisor
        .list_tools(&f.scope, &f.server_id)
        .await
        .unwrap();
    assert_eq!(
        tools
            .iter()
            .map(|v| v["name"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["read_record", "write_record"]
    );
    let stored = f
        .supervisor
        .server(&f.scope, &f.server_id)
        .unwrap()
        .unwrap();
    assert_eq!(stored.discovered_tools, tools);
    let resources = f
        .supervisor
        .list_resources(&f.scope, Some(&f.server_id))
        .await
        .unwrap();
    assert_eq!(resources.len(), 2);
    let templates = f
        .supervisor
        .list_resource_templates(&f.scope, &f.server_id)
        .await
        .unwrap();
    assert_eq!(templates[1]["uriTemplate"], "fixture://record/{id}");
    let prompts = f
        .supervisor
        .list_prompts(&f.scope, &f.server_id)
        .await
        .unwrap();
    assert_eq!(prompts[1]["name"], "summarize");
    let prompt = f
        .supervisor
        .get_prompt(
            &f.scope,
            &f.server_id,
            "summarize",
            json!({"text":"fixture value"}),
        )
        .await
        .unwrap();
    assert_eq!(prompt["messages"][0]["content"]["text"], "fixture value");
    assert_eq!(
        prompt["messages"][1]["content"]["resource"]["uri"],
        "fixture://source"
    );
    assert!(
        f.supervisor
            .get_prompt(&f.scope, &f.server_id, "summarize", json!({"text":42}))
            .await
            .is_err()
    );
    assert!(
        f.supervisor
            .resolve_tool(&f.scope, &f.server_id, "unknown")
            .is_err()
    );
    let other = McpScope {
        tenant_id: f.scope.tenant_id.clone(),
        project_id: "other-project".into(),
    };
    assert!(
        f.supervisor
            .list_prompts(&other, &f.server_id)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn repeated_or_malformed_cursor_never_publishes_a_partial_catalog() {
    for mode in ["repeated", "malformed"] {
        let f = Fixture::new(mode, 4 * 1024 * 1024);
        let error = f
            .supervisor
            .list_tools(&f.scope, &f.server_id)
            .await
            .unwrap_err();
        assert_eq!(
            error.reason_code(),
            if mode == "repeated" {
                "local_mcp_cursor_repeated"
            } else {
                "local_mcp_malformed_response"
            }
        );
        assert!(
            f.supervisor
                .server(&f.scope, &f.server_id)
                .unwrap()
                .unwrap()
                .discovered_tools
                .is_empty()
        );
    }
}

#[tokio::test]
async fn aggregate_limit_applies_across_pages_and_prompt_roles_are_validated() {
    let f = Fixture::new("normal", 100);
    assert_eq!(
        f.supervisor
            .list_tools(&f.scope, &f.server_id)
            .await
            .unwrap_err()
            .reason_code(),
        "local_mcp_collection_too_large"
    );
    let bad = Fixture::new("bad_prompt", 4 * 1024 * 1024);
    assert_eq!(
        bad.supervisor
            .get_prompt(&bad.scope, &bad.server_id, "summarize", json!({}))
            .await
            .unwrap_err()
            .reason_code(),
        "local_mcp_malformed_response"
    );
}
