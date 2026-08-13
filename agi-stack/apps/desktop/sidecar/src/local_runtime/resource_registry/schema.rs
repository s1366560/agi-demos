use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};

use super::ManagedResourceKind;

pub(in crate::local_runtime) fn initialize_resource_registry(
    connection: &Connection,
) -> Result<(), String> {
    migrate_managed_resource_table(connection)?;
    connection
        .execute_batch(
            "CREATE INDEX IF NOT EXISTS idx_desktop_managed_resources_scope
               ON desktop_managed_resources(kind, scope_kind, scope_id, status);
             CREATE TABLE IF NOT EXISTS desktop_managed_resource_versions (
               kind TEXT NOT NULL,
               scope_kind TEXT NOT NULL,
               scope_id TEXT NOT NULL,
               resource_id TEXT NOT NULL,
               revision INTEGER NOT NULL CHECK(revision >= 0),
               status TEXT NOT NULL,
               tombstone INTEGER NOT NULL CHECK(tombstone IN (0, 1)),
               created_at_ms INTEGER NOT NULL,
               value_json TEXT NOT NULL,
               vault_refs_json TEXT NOT NULL,
               PRIMARY KEY(kind, scope_kind, scope_id, resource_id, revision)
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_managed_resource_versions_scope
               ON desktop_managed_resource_versions(
                 kind, scope_kind, scope_id, resource_id, revision DESC
               );
             CREATE TABLE IF NOT EXISTS desktop_managed_resource_receipts (
               actor_id TEXT NOT NULL,
               kind TEXT NOT NULL,
               scope_kind TEXT NOT NULL,
               scope_id TEXT NOT NULL,
               idempotency_key TEXT NOT NULL,
               payload_hash TEXT NOT NULL,
               operation TEXT NOT NULL,
               resource_id TEXT NOT NULL,
               response_json TEXT NOT NULL,
               created_at_ms INTEGER NOT NULL,
               PRIMARY KEY(actor_id, kind, scope_kind, scope_id, idempotency_key)
             );
             CREATE TABLE IF NOT EXISTS desktop_llm_provider_selections (
               tenant_id TEXT PRIMARY KEY,
               provider_id TEXT NOT NULL,
               selected_at_ms INTEGER NOT NULL
             );",
        )
        .map_err(|error| error.to_string())?;
    seed_resource_registry(connection)?;
    backfill_managed_resource_versions(connection)
}

fn migrate_managed_resource_table(connection: &Connection) -> Result<(), String> {
    let table_sql = connection
        .query_row(
            "SELECT sql FROM sqlite_master
             WHERE type = 'table' AND name = 'desktop_managed_resources'",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| error.to_string())?;
    let Some(table_sql) = table_sql else {
        return connection
            .execute_batch(MANAGED_RESOURCE_TABLE_SQL)
            .map_err(|error| error.to_string());
    };
    let current = table_sql.contains("'subagent'")
        && table_sql.contains("'prompt_template'")
        && table_sql.contains("vault_refs_json");
    if current {
        return Ok(());
    }
    let transaction = connection
        .unchecked_transaction()
        .map_err(|error| error.to_string())?;
    transaction
        .execute_batch(
            "ALTER TABLE desktop_managed_resources
               RENAME TO desktop_managed_resources_v1;",
        )
        .map_err(|error| error.to_string())?;
    transaction
        .execute_batch(MANAGED_RESOURCE_TABLE_SQL)
        .map_err(|error| error.to_string())?;
    transaction
        .execute(
            "INSERT INTO desktop_managed_resources(
               kind, scope_kind, scope_id, id, status, revision,
               created_at_ms, updated_at_ms, value_json, vault_refs_json
             )
             SELECT kind, scope_kind, scope_id, id, status, revision,
                    created_at_ms, updated_at_ms, value_json, '[]'
             FROM desktop_managed_resources_v1",
            [],
        )
        .map_err(|error| error.to_string())?;
    transaction
        .execute_batch("DROP TABLE desktop_managed_resources_v1;")
        .map_err(|error| error.to_string())?;
    transaction.commit().map_err(|error| error.to_string())
}

const MANAGED_RESOURCE_TABLE_SQL: &str = "CREATE TABLE desktop_managed_resources (
       kind TEXT NOT NULL CHECK(
         kind IN ('provider', 'skill', 'plugin', 'agent', 'subagent', 'prompt_template')
       ),
       scope_kind TEXT NOT NULL CHECK(scope_kind IN ('tenant', 'project')),
       scope_id TEXT NOT NULL,
       id TEXT NOT NULL,
       status TEXT NOT NULL,
       revision INTEGER NOT NULL CHECK(revision >= 0),
       created_at_ms INTEGER NOT NULL,
       updated_at_ms INTEGER NOT NULL,
       value_json TEXT NOT NULL,
       vault_refs_json TEXT NOT NULL DEFAULT '[]',
       PRIMARY KEY(kind, scope_kind, scope_id, id)
     );";

fn backfill_managed_resource_versions(connection: &Connection) -> Result<(), String> {
    connection
        .execute(
            "INSERT OR IGNORE INTO desktop_managed_resource_versions(
               kind, scope_kind, scope_id, resource_id, revision, status,
               tombstone, created_at_ms, value_json, vault_refs_json
             )
             SELECT kind, scope_kind, scope_id, id, revision, status,
                    CASE WHEN status = 'deleted' THEN 1 ELSE 0 END,
                    updated_at_ms, value_json, vault_refs_json
             FROM desktop_managed_resources",
            [],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn seed_resource_registry(connection: &Connection) -> Result<(), String> {
    let now_ms = Utc::now().timestamp_millis();
    let tenants = query_ids_if_table_exists(
        connection,
        "desktop_tenants",
        "SELECT id FROM desktop_tenants WHERE status = 'active'",
    )?;
    for tenant_id in tenants {
        let provider = json!({
            "id": "local-runtime",
            "name": "Local runtime",
            "provider_type": "openai_compatible",
            "tenant_id": tenant_id,
            "is_active": false,
            "base_url": "http://127.0.0.1:11434/v1",
            "auth_method": "none",
            "credential_source": "none",
            "credential_configured": false,
            "llm_model": null,
            "allowed_models": [],
            "secondary_models": [],
            "health_status": "not_configured",
            "revision": 0,
            "updated_at": iso_from_millis(now_ms),
        });
        insert_seed(
            connection,
            ManagedResourceKind::Provider,
            "tenant",
            &tenant_id,
            "local-runtime",
            "disabled",
            &provider,
            now_ms,
        )?;
        for (id, name, description, tools) in [
            (
                "code-exploration",
                "Code exploration",
                "Inspect symbols, references, and repository structure before implementation.",
                vec![
                    "read",
                    "glob",
                    "grep",
                    "find_definition",
                    "find_references",
                    "call_graph",
                ],
            ),
            (
                "implementation",
                "Implementation",
                "Apply approved workspace changes inside the active run authority boundary.",
                vec![
                    "read",
                    "write",
                    "edit",
                    "apply_patch",
                    "run_tests",
                    "git_diff",
                ],
            ),
            (
                "verification",
                "Verification",
                "Run tests and collect structured evidence for human review.",
                vec![
                    "run_tests",
                    "analyze_coverage",
                    "git_diff",
                    "list_artifacts",
                ],
            ),
        ] {
            let skill = json!({
                "id": id,
                "name": name,
                "description": description,
                "status": "active",
                "scope": "tenant",
                "tools": tools,
                "current_version": 1,
                "is_system_skill": true,
                "revision": 0,
                "updated_at": iso_from_millis(now_ms),
            });
            insert_seed(
                connection,
                ManagedResourceKind::Skill,
                "tenant",
                &tenant_id,
                id,
                "active",
                &skill,
                now_ms,
            )?;
            reconcile_immutable_seed(
                connection,
                ManagedResourceKind::Skill,
                "tenant",
                &tenant_id,
                id,
                &skill,
                now_ms,
            )?;
        }
        for (id, name, package, tools) in [
            (
                "local-workspace",
                "Local workspace tools",
                "builtin:local-tools",
                vec!["read", "write", "edit", "glob", "grep", "terminal"],
            ),
            (
                "model-context-protocol",
                "Model Context Protocol",
                "builtin:mcp-runtime",
                vec!["mcp_tools_list", "mcp_tools_call"],
            ),
        ] {
            let tool_definitions = tools
                .into_iter()
                .map(|name| json!({ "name": name }))
                .collect::<Vec<_>>();
            let plugin = json!({
                "id": id,
                "name": name,
                "source": "builtin",
                "package": package,
                "version": env!("CARGO_PKG_VERSION"),
                "kind": "runtime",
                "enabled": true,
                "status": "active",
                "discovered": true,
                "providers": ["local"],
                "skills": [],
                "channel_types": [],
                "tool_definitions": tool_definitions,
                "revision": 0,
                "updated_at": iso_from_millis(now_ms),
            });
            insert_seed(
                connection,
                ManagedResourceKind::Plugin,
                "tenant",
                &tenant_id,
                id,
                "active",
                &plugin,
                now_ms,
            )?;
            reconcile_immutable_seed(
                connection,
                ManagedResourceKind::Plugin,
                "tenant",
                &tenant_id,
                id,
                &plugin,
                now_ms,
            )?;
        }
    }

    let projects = query_ids_if_table_exists(
        connection,
        "desktop_projects",
        "SELECT id FROM desktop_projects WHERE status = 'active'",
    )?;
    for project_id in projects {
        let agent = json!({
            "id": "builtin:all-access",
            "name": "Local Agent",
            "display_name": "General and coding Agent",
            "source": "builtin",
            "system_prompt": null,
            "enabled": true,
            "status": "active",
            "model_name": null,
            "allowed_tools": ["*"],
            "allowed_skills": ["*"],
            "allowed_mcp_servers": ["*"],
            "can_spawn": true,
            "spawn_policy": {
                "max_depth": 4,
                "max_active_runs": 8,
                "max_children_per_requester": 4,
                "allowed_subagents": ["*"]
            },
            "project_id": project_id,
            "revision": 0,
            "updated_at": iso_from_millis(now_ms),
        });
        insert_seed(
            connection,
            ManagedResourceKind::Agent,
            "project",
            &project_id,
            "builtin:all-access",
            "active",
            &agent,
            now_ms,
        )?;
        reconcile_immutable_seed(
            connection,
            ManagedResourceKind::Agent,
            "project",
            &project_id,
            "builtin:all-access",
            &agent,
            now_ms,
        )?;
    }
    Ok(())
}

pub(super) fn query_ids(connection: &Connection, query: &str) -> Result<Vec<String>, String> {
    let mut statement = connection
        .prepare(query)
        .map_err(|error| error.to_string())?;
    let ids = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|error| error.to_string())?
        .map(|row| row.map_err(|error| error.to_string()))
        .collect();
    ids
}

pub(super) fn query_ids_if_table_exists(
    connection: &Connection,
    table_name: &str,
    query: &str,
) -> Result<Vec<String>, String> {
    let exists = connection
        .query_row(
            "SELECT EXISTS(
               SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?1
             )",
            params![table_name],
            |row| row.get::<_, bool>(0),
        )
        .map_err(|error| error.to_string())?;
    if !exists {
        return Ok(Vec::new());
    }
    query_ids(connection, query)
}

#[allow(clippy::too_many_arguments)]
fn insert_seed(
    connection: &Connection,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    id: &str,
    status: &str,
    value: &Value,
    now_ms: i64,
) -> Result<(), String> {
    connection
        .execute(
            "INSERT OR IGNORE INTO desktop_managed_resources(
               kind, scope_kind, scope_id, id, status, revision,
               created_at_ms, updated_at_ms, value_json, vault_refs_json
             ) VALUES (?1, ?2, ?3, ?4, ?5, 0, ?6, ?6, ?7, '[]')",
            params![
                kind.as_str(),
                scope_kind,
                scope_id,
                id,
                status,
                now_ms,
                serde_json::to_string(value).map_err(|error| error.to_string())?,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn reconcile_immutable_seed(
    connection: &Connection,
    kind: ManagedResourceKind,
    scope_kind: &str,
    scope_id: &str,
    id: &str,
    canonical: &Value,
    now_ms: i64,
) -> Result<(), String> {
    let existing = connection
        .query_row(
            "SELECT status, revision, value_json FROM desktop_managed_resources
             WHERE kind = ?1 AND scope_kind = ?2 AND scope_id = ?3 AND id = ?4",
            params![kind.as_str(), scope_kind, scope_id, id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, u64>(1)?,
                    row.get::<_, String>(2)?,
                ))
            },
        )
        .optional()
        .map_err(|error| error.to_string())?;
    let Some((stored_status, revision, value_json)) = existing else {
        return Ok(());
    };
    let mut value: Value = serde_json::from_str(&value_json).map_err(|error| error.to_string())?;
    let object = value
        .as_object_mut()
        .ok_or_else(|| "managed resource must be an object".to_string())?;
    let mut changed = stored_status != "active";
    changed |= replace_if_different(object, "id", json!(id));
    match kind {
        ManagedResourceKind::Skill => {
            changed |= replace_if_different(object, "status", json!("active"));
            changed |= replace_if_different(object, "is_system_skill", json!(true));
            changed |= replace_seed_fields(
                object,
                canonical,
                &["name", "description", "scope", "tools"],
            );
        }
        ManagedResourceKind::Plugin => {
            changed |= replace_if_different(object, "source", json!("builtin"));
            changed |= replace_if_different(object, "enabled", json!(true));
            changed |= replace_if_different(object, "status", json!("active"));
            changed |= replace_if_different(object, "discovered", json!(true));
            changed |= replace_seed_fields(
                object,
                canonical,
                &["name", "package", "kind", "providers", "tool_definitions"],
            );
        }
        ManagedResourceKind::Agent => {
            changed |= replace_if_different(object, "source", json!("builtin"));
            changed |= replace_if_different(object, "enabled", json!(true));
            changed |= replace_if_different(object, "status", json!("active"));
            changed |= replace_seed_fields(
                object,
                canonical,
                &[
                    "name",
                    "display_name",
                    "system_prompt",
                    "model_name",
                    "allowed_tools",
                    "allowed_skills",
                    "allowed_mcp_servers",
                    "can_spawn",
                    "spawn_policy",
                    "project_id",
                ],
            );
        }
        ManagedResourceKind::SubAgent | ManagedResourceKind::PromptTemplate => return Ok(()),
        ManagedResourceKind::Provider => return Ok(()),
    }
    if !changed {
        return Ok(());
    }
    let next_revision = revision.saturating_add(1);
    object.insert("revision".to_string(), json!(next_revision));
    object.insert("updated_at".to_string(), json!(iso_from_millis(now_ms)));
    let value_json = serde_json::to_string(&value).map_err(|error| error.to_string())?;
    connection
        .execute(
            "UPDATE desktop_managed_resources
             SET status = 'active', revision = ?1, updated_at_ms = ?2, value_json = ?3
             WHERE kind = ?4 AND scope_kind = ?5 AND scope_id = ?6 AND id = ?7",
            params![
                next_revision,
                now_ms,
                value_json,
                kind.as_str(),
                scope_kind,
                scope_id,
                id,
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn replace_seed_fields(
    object: &mut serde_json::Map<String, Value>,
    canonical: &Value,
    fields: &[&str],
) -> bool {
    fields.iter().fold(false, |changed, field| {
        let expected = canonical.get(*field).cloned().unwrap_or(Value::Null);
        replace_if_different(object, field, expected) || changed
    })
}

fn replace_if_different(
    object: &mut serde_json::Map<String, Value>,
    key: &str,
    expected: Value,
) -> bool {
    if object.get(key) == Some(&expected) {
        return false;
    }
    object.insert(key.to_string(), expected);
    true
}

pub(super) fn iso_from_millis(timestamp_ms: i64) -> String {
    DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .unwrap_or_else(Utc::now)
        .to_rfc3339()
}
