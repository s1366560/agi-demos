use super::Fixture;
use crate::local_runtime::mcp_supervisor::{McpScope, McpServerDefinitionInput};
use serde_json::json;

fn stage(f: &Fixture) {
    f.supervisor
        .stage_marketplace_server(&f.scope, &f.server_id)
        .unwrap();
}

fn input(f: &Fixture, enabled: bool) -> McpServerDefinitionInput {
    let server = f
        .supervisor
        .server(&f.scope, &f.server_id)
        .unwrap()
        .unwrap();
    McpServerDefinitionInput {
        name: server.name,
        description: Some("updated fixture configuration".into()),
        transport: server.transport,
        command: server.command,
        cwd: server.cwd,
        vault_env_refs: server.vault_env_refs,
        enabled,
    }
}

async fn assert_ordinary_calls_rejected(f: &Fixture) {
    let errors = [
        f.supervisor
            .list_tools(&f.scope, &f.server_id)
            .await
            .unwrap_err(),
        f.supervisor
            .list_resources(&f.scope, Some(&f.server_id))
            .await
            .unwrap_err(),
        f.supervisor
            .list_resource_templates(&f.scope, &f.server_id)
            .await
            .unwrap_err(),
        f.supervisor
            .list_prompts(&f.scope, &f.server_id)
            .await
            .unwrap_err(),
        f.supervisor
            .get_prompt(&f.scope, &f.server_id, "summarize", json!({}))
            .await
            .unwrap_err(),
        f.supervisor
            .call_tool(
                &f.scope,
                &f.server_id,
                "read_record",
                json!({}),
                "candidate-call",
            )
            .await
            .unwrap_err(),
        f.supervisor
            .read_resource(&f.scope, &f.server_id, "fixture://first")
            .await
            .unwrap_err(),
    ];
    for error in errors {
        assert_eq!(error.reason_code(), "local_mcp_generation_inactive");
    }
}

#[tokio::test]
async fn candidate_verification_does_not_admit_ordinary_calls_before_or_after_collection() {
    let f = Fixture::new("normal", 4 * 1024 * 1024);
    stage(&f);
    assert_ordinary_calls_rejected(&f).await;
    assert!(!f.root.join("requests.jsonl").exists());
    let tools = f
        .supervisor
        .list_tools_for_marketplace_verification(&f.scope, &f.server_id)
        .await
        .unwrap();
    assert_eq!(tools.len(), 2);
    let requests = std::fs::read_to_string(f.root.join("requests.jsonl")).unwrap();
    assert_eq!(requests.lines().count(), 2);
    assert_ordinary_calls_rejected(&f).await;
    assert_eq!(
        std::fs::read_to_string(f.root.join("requests.jsonl")).unwrap(),
        requests
    );
    assert!(f.supervisor.list_servers(&f.scope).unwrap().is_empty());
    assert!(f.supervisor.list_apps(&f.scope).unwrap().is_empty());
}

#[tokio::test]
async fn verification_rejects_unregistered_wrong_scope_disabled_and_retired_servers() {
    let f = Fixture::new("normal", 4 * 1024 * 1024);
    for id in [&f.server_id, "unknown-server"] {
        assert_eq!(
            f.supervisor
                .list_tools_for_marketplace_verification(&f.scope, id)
                .await
                .unwrap_err()
                .reason_code(),
            "local_mcp_generation_inactive"
        );
    }
    stage(&f);
    let other = McpScope {
        tenant_id: f.scope.tenant_id.clone(),
        project_id: "other-project".into(),
    };
    assert_eq!(
        f.supervisor
            .list_tools_for_marketplace_verification(&other, &f.server_id)
            .await
            .unwrap_err()
            .reason_code(),
        "local_mcp_generation_inactive"
    );
    let revision = f
        .supervisor
        .server(&f.scope, &f.server_id)
        .unwrap()
        .unwrap()
        .revision;
    f.supervisor
        .update_server(
            &f.scope,
            &f.server_id,
            input(&f, false),
            revision,
            "disable",
        )
        .unwrap();
    assert_eq!(
        f.supervisor
            .list_tools_for_marketplace_verification(&f.scope, &f.server_id)
            .await
            .unwrap_err()
            .reason_code(),
        "local_mcp_server_disabled"
    );
    f.supervisor
        .publish_marketplace_generation(&f.scope, &[f.server_id.clone()], &[])
        .unwrap();
    let (_, lease) = f.supervisor.acquire_catalog(&f.scope).unwrap();
    f.supervisor
        .publish_marketplace_generation(&f.scope, &[], &[f.server_id.clone()])
        .unwrap();
    assert_eq!(
        f.supervisor
            .list_tools_for_marketplace_verification(&f.scope, &f.server_id)
            .await
            .unwrap_err()
            .reason_code(),
        "local_mcp_generation_inactive"
    );
    assert!(!f.root.join("requests.jsonl").exists());
    drop(lease);
    assert!(f
        .supervisor
        .server(&f.scope, &f.server_id)
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn candidate_verification_never_records_incomplete_or_oversized_collections() {
    for (mode, limit, reason) in [
        ("repeated", 4 * 1024 * 1024, "local_mcp_cursor_repeated"),
        ("malformed", 4 * 1024 * 1024, "local_mcp_malformed_response"),
        ("normal", 100, "local_mcp_collection_too_large"),
    ] {
        let f = Fixture::new(mode, limit);
        stage(&f);
        let error = f
            .supervisor
            .list_tools_for_marketplace_verification(&f.scope, &f.server_id)
            .await
            .unwrap_err();
        assert_eq!(error.reason_code(), reason);
        assert!(f
            .supervisor
            .server(&f.scope, &f.server_id)
            .unwrap()
            .unwrap()
            .discovered_tools
            .is_empty());
        assert!(!f.supervisor.marketplace_server_active(&f.server_id));
    }
}

async fn wait_for_first_page(f: &Fixture) {
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while !f.root.join("page-started").exists() {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("owned fixture first page");
}

#[tokio::test]
async fn candidate_verification_rejects_server_revision_changes_without_recording_pages() {
    let f = Fixture::new("slow_page", 4 * 1024 * 1024);
    stage(&f);
    let (supervisor, scope, id) = (f.supervisor.clone(), f.scope.clone(), f.server_id.clone());
    let work = tokio::spawn(async move {
        supervisor
            .list_tools_for_marketplace_verification(&scope, &id)
            .await
    });
    wait_for_first_page(&f).await;
    let revision = f
        .supervisor
        .server(&f.scope, &f.server_id)
        .unwrap()
        .unwrap()
        .revision;
    f.supervisor
        .update_server(&f.scope, &f.server_id, input(&f, true), revision, "update")
        .unwrap();
    std::fs::write(f.root.join("page-release"), "release").unwrap();
    assert_eq!(
        work.await.unwrap().unwrap_err().reason_code(),
        "local_mcp_catalog_changed"
    );
    assert!(f
        .supervisor
        .server(&f.scope, &f.server_id)
        .unwrap()
        .unwrap()
        .discovered_tools
        .is_empty());
    assert_eq!(
        std::fs::read_to_string(f.root.join("requests.jsonl"))
            .unwrap()
            .lines()
            .count(),
        1
    );
}

#[tokio::test]
async fn admitted_collection_keeps_generation_until_all_pages_and_app_recording_finish() {
    for verification in [false, true] {
        let f = Fixture::new("slow_page", 4 * 1024 * 1024);
        stage(&f);
        if !verification {
            f.supervisor
                .publish_marketplace_generation(&f.scope, &[f.server_id.clone()], &[])
                .unwrap();
        }
        let (supervisor, scope, id) = (f.supervisor.clone(), f.scope.clone(), f.server_id.clone());
        let work = tokio::spawn(async move {
            if verification {
                supervisor
                    .list_tools_for_marketplace_verification(&scope, &id)
                    .await
            } else {
                supervisor.list_tools(&scope, &id).await
            }
        });
        wait_for_first_page(&f).await;
        f.supervisor
            .publish_marketplace_generation(&f.scope, &[], &[f.server_id.clone()])
            .unwrap();
        assert!(f
            .supervisor
            .server(&f.scope, &f.server_id)
            .unwrap()
            .is_some());
        assert_ordinary_calls_rejected(&f).await;
        assert_eq!(
            f.supervisor
                .list_tools_for_marketplace_verification(&f.scope, &f.server_id)
                .await
                .unwrap_err()
                .reason_code(),
            "local_mcp_generation_inactive"
        );
        std::fs::write(f.root.join("page-release"), "release").unwrap();
        assert_eq!(work.await.unwrap().unwrap().len(), 2);
        assert_eq!(
            std::fs::read_to_string(f.root.join("requests.jsonl"))
                .unwrap()
                .lines()
                .count(),
            2
        );
        assert!(f
            .supervisor
            .server(&f.scope, &f.server_id)
            .unwrap()
            .is_none());
    }
}
