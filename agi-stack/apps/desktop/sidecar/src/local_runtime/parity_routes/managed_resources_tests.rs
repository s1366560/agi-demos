use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::*;

fn test_state(credential: &str) -> Arc<LocalRuntimeState> {
    let root: PathBuf =
        std::env::temp_dir().join(format!("agistack-managed-resource-v2-{}", Uuid::new_v4()));
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root,
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    state
}

fn request(method: Method, uri: &str, credential: &str, body: Value) -> Request<Body> {
    Request::builder()
        .method(method)
        .uri(uri)
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .expect("managed resource request")
}

async fn json_response(response: axum::response::Response) -> Value {
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response bytes");
    serde_json::from_slice(&bytes).expect("response JSON")
}

fn mutation(
    key: &str,
    expected_revision: u64,
    resource_id: Option<&str>,
    value: Option<Value>,
) -> Value {
    json!({
        "contract_version": 2,
        "expected_revision": expected_revision,
        "idempotency_key": key,
        "resource_id": resource_id,
        "value": value,
        "vault_refs": [],
    })
}

#[tokio::test]
async fn local_skill_import_is_identity_bound_overwrite_safe_and_idempotent() {
    let credential = "managed-skill-import-secret";
    let app = local_router(test_state(credential));
    let package = concat!(
        "---\n",
        "name: imported-skill\n",
        "description: Imported safely.\n",
        "---\n\n",
        "# Imported skill"
    );
    let create_body = mutation(
        "import-skill-create",
        0,
        Some("imported-skill"),
        Some(json!({
            "scope": "tenant",
            "overwrite": false,
            "skill_md_content": package,
            "resource_files": {},
        })),
    );

    let created = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/import?tenant_id=local",
            credential,
            create_body.clone(),
        ))
        .await
        .expect("create imported skill");
    assert_eq!(created.status(), StatusCode::OK);
    let created = json_response(created).await;
    assert_eq!(created["action"], "imported");
    assert_eq!(created["skill"]["revision"], 0);
    assert_eq!(created["skill"].get("overwrite"), None);

    let replayed = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/import?tenant_id=local",
            credential,
            create_body,
        ))
        .await
        .expect("replay imported skill");
    assert_eq!(replayed.status(), StatusCode::OK);
    assert_eq!(
        json_response(replayed).await["mutation_receipt"]["duplicate"],
        true
    );

    let implicit_overwrite = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/import?tenant_id=local",
            credential,
            mutation(
                "import-skill-without-overwrite",
                0,
                Some("imported-skill"),
                Some(json!({
                    "scope": "tenant",
                    "overwrite": false,
                    "skill_md_content": package,
                    "resource_files": {},
                })),
            ),
        ))
        .await
        .expect("reject implicit overwrite");
    assert_eq!(implicit_overwrite.status(), StatusCode::CONFLICT);
    assert_eq!(
        json_response(implicit_overwrite).await["code"],
        "managed_resource_already_exists"
    );

    let overwritten = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/import?tenant_id=local",
            credential,
            mutation(
                "import-skill-overwrite",
                0,
                Some("imported-skill"),
                Some(json!({
                    "scope": "tenant",
                    "overwrite": true,
                    "skill_md_content": package,
                    "resource_files": {},
                })),
            ),
        ))
        .await
        .expect("overwrite imported skill");
    assert_eq!(overwritten.status(), StatusCode::OK);
    let overwritten = json_response(overwritten).await;
    assert_eq!(overwritten["action"], "updated");
    assert_eq!(overwritten["skill"]["revision"], 1);
    assert_eq!(overwritten["skill"].get("overwrite"), None);

    let mismatched_identity = app
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/import?tenant_id=local",
            credential,
            mutation(
                "import-skill-mismatched-identity",
                0,
                Some("different-skill"),
                Some(json!({
                    "scope": "tenant",
                    "overwrite": false,
                    "skill_md_content": package,
                    "resource_files": {},
                })),
            ),
        ))
        .await
        .expect("reject mismatched import identity");
    assert_eq!(
        mismatched_identity.status(),
        StatusCode::UNPROCESSABLE_ENTITY
    );
    assert_eq!(
        json_response(mismatched_identity).await["detail"],
        "managed skill package name must match resource_id"
    );
}

#[tokio::test]
async fn local_skill_crud_versions_rollback_export_and_idempotency_are_authoritative() {
    let credential = "managed-skill-v2-secret";
    let app = local_router(test_state(credential));
    let create_body = mutation(
        "create-custom-skill",
        0,
        Some("custom-skill"),
        Some(json!({
            "name": "Custom skill",
            "description": "A local custom skill.",
            "tools": ["read"],
            "scope": "tenant",
            "full_content": "# Custom skill",
            "metadata": {},
        })),
    );

    let created = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/?tenant_id=local",
            credential,
            create_body.clone(),
        ))
        .await
        .expect("create skill");
    assert_eq!(created.status(), StatusCode::OK);
    let created = json_response(created).await;
    assert_eq!(created["id"], "custom-skill");
    assert_eq!(created["revision"], 0);
    assert_eq!(created["mutation_receipt"]["duplicate"], false);

    let replayed = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/?tenant_id=local",
            credential,
            create_body,
        ))
        .await
        .expect("replay create skill");
    assert_eq!(replayed.status(), StatusCode::OK);
    let replayed = json_response(replayed).await;
    assert_eq!(replayed["mutation_receipt"]["duplicate"], true);
    assert_eq!(
        replayed["mutation_receipt"]["receipt_id"],
        created["mutation_receipt"]["receipt_id"]
    );

    let updated = app
        .clone()
        .oneshot(request(
            Method::PUT,
            "/api/v1/skills/custom-skill?tenant_id=local",
            credential,
            mutation(
                "update-custom-skill",
                0,
                None,
                Some(json!({
                    "name": "Custom skill",
                    "description": "Updated locally.",
                    "tools": ["read", "grep"],
                    "scope": "tenant",
                    "full_content": "# Custom skill\n\nUpdated locally.",
                    "metadata": {},
                })),
            ),
        ))
        .await
        .expect("update skill");
    assert_eq!(updated.status(), StatusCode::OK);
    assert_eq!(json_response(updated).await["revision"], 1);

    let versions = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/skills/custom-skill/versions?tenant_id=local",
            credential,
            json!({}),
        ))
        .await
        .expect("skill versions");
    assert_eq!(versions.status(), StatusCode::OK);
    let versions = json_response(versions).await;
    assert_eq!(versions["total"], 2);
    assert_eq!(versions["versions"][0]["version_number"], 1);

    let rolled_back = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/custom-skill/rollback?tenant_id=local",
            credential,
            json!({
                "contract_version": 2,
                "expected_revision": 1,
                "idempotency_key": "rollback-custom-skill",
                "target_revision": 0,
                "vault_refs": [],
            }),
        ))
        .await
        .expect("rollback skill");
    assert_eq!(rolled_back.status(), StatusCode::OK);
    let rolled_back = json_response(rolled_back).await;
    assert_eq!(rolled_back["revision"], 2);
    assert_eq!(rolled_back["description"], "A local custom skill.");

    let exported = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/skills/custom-skill/export?tenant_id=local",
            credential,
            json!({}),
        ))
        .await
        .expect("export skill");
    assert_eq!(exported.status(), StatusCode::OK);
    let exported = json_response(exported).await;
    assert_eq!(exported["format"], "agentskills.io/skill-package");
    assert_eq!(exported["skill"]["id"], "custom-skill");

    let deleted = app
        .clone()
        .oneshot(request(
            Method::DELETE,
            "/api/v1/skills/custom-skill?tenant_id=local",
            credential,
            mutation("delete-custom-skill", 2, None, None),
        ))
        .await
        .expect("delete skill");
    assert_eq!(deleted.status(), StatusCode::OK);
    assert_eq!(json_response(deleted).await["deleted"], true);
}

#[tokio::test]
async fn local_agent_subagent_and_prompt_template_mutations_are_scope_and_revision_guarded() {
    let credential = "managed-agent-v2-secret";
    let app = local_router(test_state(credential));
    let fixtures = [
        (
            "/api/v1/agent/definitions?tenant_id=local",
            "agent-create",
            "custom-agent",
            json!({
                "name": "custom-agent",
                "display_name": "Custom Agent",
                "system_prompt": "Work carefully.",
                "project_id": "local-project",
                "enabled": true,
            }),
        ),
        (
            "/api/v1/subagents/?tenant_id=local",
            "subagent-create",
            "custom-subagent",
            json!({
                "name": "custom-subagent",
                "display_name": "Custom SubAgent",
                "system_prompt": "Review carefully.",
                "project_id": "local-project",
                "enabled": true,
            }),
        ),
        (
            "/api/v1/agent/templates?tenant_id=local",
            "template-create",
            "custom-template",
            json!({
                "title": "Custom template",
                "content": "Summarize {{input}}.",
                "category": "custom",
            }),
        ),
    ];
    for (uri, key, resource_id, value) in fixtures {
        let response = app
            .clone()
            .oneshot(request(
                Method::POST,
                uri,
                credential,
                mutation(key, 0, Some(resource_id), Some(value)),
            ))
            .await
            .expect("create managed resource");
        assert_eq!(response.status(), StatusCode::OK, "{uri}");
        let payload = json_response(response).await;
        assert_eq!(payload["id"], resource_id);
        assert_eq!(payload["revision"], 0);
    }

    let subagents = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/subagents/?tenant_id=local",
            credential,
            json!({}),
        ))
        .await
        .expect("list subagents");
    assert_eq!(subagents.status(), StatusCode::OK);
    assert_eq!(
        json_response(subagents).await["items"]
            .as_array()
            .map(Vec::len),
        Some(1)
    );

    let templates = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/agent/templates?tenant_id=local&limit=100&offset=0",
            credential,
            json!({}),
        ))
        .await
        .expect("list templates");
    assert_eq!(templates.status(), StatusCode::OK);
    assert_eq!(
        json_response(templates).await.as_array().map(Vec::len),
        Some(1)
    );

    let conflict = app
        .clone()
        .oneshot(request(
            Method::PUT,
            "/api/v1/subagents/custom-subagent?tenant_id=local",
            credential,
            mutation(
                "subagent-stale-update",
                9,
                None,
                Some(json!({
                    "name": "custom-subagent",
                    "display_name": "Changed",
                    "system_prompt": "Review carefully.",
                    "enabled": true,
                })),
            ),
        ))
        .await
        .expect("stale subagent update");
    assert_eq!(conflict.status(), StatusCode::CONFLICT);
}

#[tokio::test]
async fn local_agent_definition_trigger_fields_round_trip() {
    let credential = "managed-agent-trigger-secret";
    let app = local_router(test_state(credential));
    let create = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/agent/definitions?tenant_id=local",
            credential,
            mutation(
                "agent-trigger-create",
                0,
                Some("trigger-agent"),
                Some(json!({
                    "name": "trigger-agent",
                    "display_name": "Trigger Agent",
                    "system_prompt": "Route meaningful requests.",
                    "trigger_description": "Use for acceptance testing.",
                    "trigger_keywords": ["acceptance"],
                    "trigger_examples": ["Verify this acceptance flow"],
                })),
            ),
        ))
        .await
        .expect("create Agent definition");
    assert_eq!(create.status(), StatusCode::OK);
    let created = json_response(create).await;
    assert_eq!(created["revision"], 0);
    assert_eq!(
        created["trigger"],
        json!({
            "description": "Use for acceptance testing.",
            "keywords": ["acceptance"],
            "examples": ["Verify this acceptance flow"],
        })
    );
    assert!(created.get("trigger_description").is_none());

    let update = app
        .clone()
        .oneshot(request(
            Method::PUT,
            "/api/v1/agent/definitions/trigger-agent?tenant_id=local",
            credential,
            mutation(
                "agent-trigger-update",
                0,
                None,
                Some(json!({
                    "trigger_description": "Use for edited acceptance testing.",
                    "trigger_keywords": ["acceptance", "edited"],
                    "trigger_examples": ["Verify this edited acceptance flow"],
                })),
            ),
        ))
        .await
        .expect("update Agent definition");
    assert_eq!(update.status(), StatusCode::OK);
    let updated = json_response(update).await;
    assert_eq!(updated["revision"], 1);
    assert_eq!(
        updated["trigger"],
        json!({
            "description": "Use for edited acceptance testing.",
            "keywords": ["acceptance", "edited"],
            "examples": ["Verify this edited acceptance flow"],
        })
    );

    let fetched = app
        .oneshot(request(
            Method::GET,
            "/api/v1/agent/definitions/trigger-agent?tenant_id=local",
            credential,
            json!({}),
        ))
        .await
        .expect("read Agent definition");
    assert_eq!(fetched.status(), StatusCode::OK);
    assert_eq!(json_response(fetched).await["trigger"], updated["trigger"]);
}

#[tokio::test]
async fn local_subagents_are_structurally_scoped_to_the_active_project() {
    let credential = "managed-subagent-scope-secret";
    let state = test_state(credential);
    for (id, project_id, status, enabled) in [
        ("tenant-reviewer", Value::Null, "active", true),
        ("project-reviewer", json!("local-project"), "active", true),
        (
            "disabled-project-reviewer",
            json!("local-project"),
            "disabled",
            false,
        ),
        (
            "foreign-project-reviewer",
            json!("desktop-client"),
            "active",
            true,
        ),
        ("malformed-project-reviewer", json!(7), "active", true),
    ] {
        state
            .session_store
            .put_managed_resource(
                ManagedResourceKind::SubAgent,
                "tenant",
                "local",
                id,
                status,
                None,
                json!({
                    "id": id,
                    "tenant_id": "local",
                    "project_id": project_id,
                    "name": id,
                    "display_name": id,
                    "system_prompt": "Review the active project.",
                    "enabled": enabled,
                    "status": status,
                    "source": "database",
                    "allowed_tools": ["read"],
                    "allowed_skills": [],
                    "allowed_mcp_servers": [],
                }),
                Utc::now().timestamp_millis(),
            )
            .expect("seed scoped SubAgent");
    }
    let app = local_router(Arc::clone(&state));

    let listed = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/subagents/?tenant_id=local",
            credential,
            json!({}),
        ))
        .await
        .expect("list scoped SubAgents");
    assert_eq!(listed.status(), StatusCode::OK);
    let listed_payload = json_response(listed).await;
    let mut listed_ids = listed_payload["items"]
        .as_array()
        .expect("SubAgent items")
        .iter()
        .filter_map(|item| item["id"].as_str())
        .collect::<Vec<_>>();
    listed_ids.sort_unstable();
    assert_eq!(
        listed_ids,
        [
            "disabled-project-reviewer",
            "project-reviewer",
            "tenant-reviewer",
        ]
    );

    for (key, project_id) in [
        ("cross-project-create", json!("desktop-client")),
        ("malformed-project-create", json!(7)),
    ] {
        let rejected = app
            .clone()
            .oneshot(request(
                Method::POST,
                "/api/v1/subagents/?tenant_id=local",
                credential,
                mutation(
                    key,
                    0,
                    Some(key),
                    Some(json!({
                        "name": key,
                        "display_name": key,
                        "system_prompt": "Must not cross project authority.",
                        "project_id": project_id,
                        "enabled": true,
                    })),
                ),
            ))
            .await
            .expect("reject invalid SubAgent project scope");
        assert_eq!(rejected.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    let rejected_update = app
        .clone()
        .oneshot(request(
            Method::PUT,
            "/api/v1/subagents/project-reviewer?tenant_id=local",
            credential,
            mutation(
                "cross-project-update",
                0,
                None,
                Some(json!({
                    "display_name": "Rebound reviewer",
                    "project_id": "desktop-client",
                })),
            ),
        ))
        .await
        .expect("reject SubAgent project rebind");
    assert_eq!(rejected_update.status(), StatusCode::UNPROCESSABLE_ENTITY);

    let foreign_get = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/subagents/foreign-project-reviewer?tenant_id=local",
            credential,
            json!({}),
        ))
        .await
        .expect("reject cross-project SubAgent read");
    assert_eq!(foreign_get.status(), StatusCode::NOT_FOUND);

    let foreign_delete = app
        .clone()
        .oneshot(request(
            Method::DELETE,
            "/api/v1/subagents/foreign-project-reviewer?tenant_id=local",
            credential,
            mutation("cross-project-delete", 0, None, None),
        ))
        .await
        .expect("reject cross-project SubAgent delete");
    assert_eq!(foreign_delete.status(), StatusCode::NOT_FOUND);

    let foreign_toggle = app
        .oneshot(request(
            Method::PATCH,
            "/api/v1/subagents/foreign-project-reviewer/enable?tenant_id=local&enabled=false",
            credential,
            mutation(
                "cross-project-toggle",
                0,
                None,
                Some(json!({ "enabled": false })),
            ),
        ))
        .await
        .expect("reject cross-project SubAgent toggle");
    assert_eq!(foreign_toggle.status(), StatusCode::NOT_FOUND);

    let persisted = state
        .session_store
        .managed_resource(
            ManagedResourceKind::SubAgent,
            "tenant",
            "local",
            "project-reviewer",
        )
        .expect("load scoped SubAgent")
        .expect("scoped SubAgent");
    assert_eq!(persisted["project_id"], "local-project");
    assert_eq!(persisted["revision"], 0);
}

#[tokio::test]
async fn managed_resource_v2_rejects_builtin_mutation_and_malformed_or_rebound_commands() {
    let credential = "managed-resource-guard-secret";
    let app = local_router(test_state(credential));

    let malformed = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/?tenant_id=local",
            credential,
            json!({"name": "missing contract"}),
        ))
        .await
        .expect("malformed mutation");
    assert_eq!(malformed.status(), StatusCode::UNPROCESSABLE_ENTITY);

    let invalid_package = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/import?tenant_id=local",
            credential,
            mutation(
                "invalid-skill-package",
                0,
                Some("invalid-package"),
                Some(json!({
                    "scope": "tenant",
                    "skill_md_content": "# Missing frontmatter",
                    "resource_files": {},
                })),
            ),
        ))
        .await
        .expect("invalid skill package");
    assert_eq!(invalid_package.status(), StatusCode::UNPROCESSABLE_ENTITY);

    let traversal_package = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/import?tenant_id=local",
            credential,
            mutation(
                "traversal-skill-package",
                0,
                Some("traversal-package"),
                Some(json!({
                    "scope": "tenant",
                    "skill_md_content": concat!(
                        "---\n",
                        "name: traversal-package\n",
                        "description: Must reject traversal.\n",
                        "---\n\n",
                        "# Traversal package"
                    ),
                    "resource_files": {
                        "../outside.md": "must not escape",
                    },
                })),
            ),
        ))
        .await
        .expect("traversal skill package");
    assert_eq!(traversal_package.status(), StatusCode::UNPROCESSABLE_ENTITY);

    let immutable = app
        .clone()
        .oneshot(request(
            Method::PUT,
            "/api/v1/skills/implementation?tenant_id=local",
            credential,
            mutation(
                "mutate-builtin",
                0,
                None,
                Some(json!({
                    "name": "Implementation",
                    "description": "Changed",
                    "tools": ["read"],
                    "scope": "tenant",
                })),
            ),
        ))
        .await
        .expect("immutable mutation");
    assert_eq!(immutable.status(), StatusCode::CONFLICT);
    assert_eq!(json_response(immutable).await["code"], "immutable_resource");

    let create = mutation(
        "rebound-key",
        0,
        Some("first-skill"),
        Some(json!({
            "name": "First",
            "description": "First.",
            "tools": ["read"],
            "scope": "tenant",
        })),
    );
    let first = app
        .clone()
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/?tenant_id=local",
            credential,
            create,
        ))
        .await
        .expect("first keyed mutation");
    assert_eq!(first.status(), StatusCode::OK);
    let rebound = app
        .oneshot(request(
            Method::POST,
            "/api/v1/skills/?tenant_id=local",
            credential,
            mutation(
                "rebound-key",
                0,
                Some("second-skill"),
                Some(json!({
                    "name": "Second",
                    "description": "Second.",
                    "tools": ["read"],
                    "scope": "tenant",
                })),
            ),
        ))
        .await
        .expect("rebound keyed mutation");
    assert_eq!(rebound.status(), StatusCode::CONFLICT);
    assert_eq!(
        json_response(rebound).await["code"],
        "managed_resource_idempotency_conflict"
    );
}

#[tokio::test]
async fn skill_mutation_fails_closed_when_resource_id_is_ambiguous_across_scopes() {
    let credential = "managed-resource-ambiguous-scope-secret";
    let state = test_state(credential);
    for (scope_kind, scope_id) in [("tenant", "local"), ("project", "local-project")] {
        state
            .session_store
            .put_managed_resource(
                ManagedResourceKind::Skill,
                scope_kind,
                scope_id,
                "shared-skill-id",
                "active",
                None,
                json!({
                    "name": "Shared skill",
                    "description": format!("{scope_kind} scoped fixture"),
                    "tools": ["read"],
                    "scope": scope_kind,
                }),
                1_727_000_000_000,
            )
            .expect("seed scoped skill");
    }
    let app = local_router(state);

    let listed = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/skills/?tenant_id=local&project_id=local-project",
            credential,
            json!({}),
        ))
        .await
        .expect("list scoped skills");
    assert_eq!(listed.status(), StatusCode::OK);
    let scoped = json_response(listed).await;
    let shared = scoped["items"]
        .as_array()
        .expect("managed skill items")
        .iter()
        .filter(|skill| skill["id"] == "shared-skill-id")
        .collect::<Vec<_>>();
    assert_eq!(shared.len(), 2);
    assert!(shared.iter().any(|skill| skill["scope"] == "tenant"));
    assert!(shared.iter().any(|skill| skill["scope"] == "project"));

    let response = app
        .oneshot(request(
            Method::PUT,
            "/api/v1/skills/shared-skill-id?tenant_id=local",
            credential,
            mutation(
                "ambiguous-skill-update",
                0,
                None,
                Some(json!({
                    "name": "Shared skill",
                    "description": "Must not pick one scope implicitly.",
                    "tools": ["read"],
                    "scope": "tenant",
                })),
            ),
        ))
        .await
        .expect("ambiguous scoped mutation");

    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let payload = json_response(response).await;
    assert_eq!(payload["code"], "invalid_managed_resource_mutation");
    assert_eq!(
        payload["detail"],
        "managed resource id is ambiguous across active scopes"
    );
}
