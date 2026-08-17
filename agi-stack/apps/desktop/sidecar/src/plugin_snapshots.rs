//! SQLite persistence for desktop platform plugin snapshots.
//!
//! This module owns durable requested/applied state and the all-or-nothing local
//! activation inventory. A rejected snapshot never changes the active generation
//! and credential values are never stored here.

use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde::{Deserialize, Serialize};
use serde_json::Value;

const TABLE_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS desktop_platform_plugin_snapshots (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    requested_version INTEGER NOT NULL,
    requested_nonce TEXT NOT NULL,
    requested_digest TEXT NOT NULL,
    requested_json TEXT NOT NULL,
    applied_version INTEGER NOT NULL,
    applied_digest TEXT,
    last_good_json TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'ack', 'nack')),
    error_message TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"#;

const ACTIVATION_TABLE_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS desktop_platform_plugin_activations (
    snapshot_digest TEXT NOT NULL,
    plugin_id TEXT NOT NULL,
    plugin_version TEXT NOT NULL,
    runtime TEXT NOT NULL,
    trust TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    config_json TEXT NOT NULL,
    activated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_digest, plugin_id)
);
"#;

const ARTIFACT_TABLE_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS desktop_platform_plugin_artifacts (
    artifact_digest TEXT NOT NULL,
    plugin_id TEXT NOT NULL,
    runtime_kind TEXT NOT NULL,
    runtime_path TEXT NOT NULL,
    runtime_bytes BLOB NOT NULL,
    verified_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (artifact_digest, plugin_id)
);
"#;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub(crate) struct PluginApplyRecord {
    pub requested_version: u64,
    pub requested_nonce: String,
    pub requested_digest: String,
    pub applied_version: u64,
    pub applied_digest: Option<String>,
    pub status: String,
    pub error_message: Option<String>,
    pub has_last_good: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct RequestedPluginSnapshot {
    pub(crate) version: u64,
    pub(crate) nonce: String,
    pub(crate) digest: String,
    pub(crate) payload: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub(crate) struct PluginActivationRecord {
    pub(crate) plugin_id: String,
    pub(crate) plugin_version: String,
    pub(crate) runtime: String,
    pub(crate) trust: String,
    pub(crate) capabilities: Vec<Value>,
    pub(crate) config: Value,
}

#[derive(Debug, Clone, PartialEq)]
pub(crate) struct RuntimeArtifact {
    pub(crate) plugin_id: String,
    pub(crate) digest: String,
    pub(crate) runtime: String,
    pub(crate) path: String,
    pub(crate) bytes: Vec<u8>,
}

struct PreparedPlugin {
    plugin_id: String,
    plugin_version: String,
    runtime: String,
    trust: String,
    capabilities: Vec<Value>,
    config: Value,
}

pub(crate) fn initialize_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(&format!(
            "{TABLE_SQL}{ACTIVATION_TABLE_SQL}{ARTIFACT_TABLE_SQL}"
        ))
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(crate) fn read_apply_record(
    connection: &Connection,
) -> Result<Option<PluginApplyRecord>, String> {
    connection
        .query_row(
            r#"
            SELECT requested_version, requested_nonce, requested_digest,
                   applied_version, applied_digest, last_good_json,
                   status, error_message
            FROM desktop_platform_plugin_snapshots WHERE id = 1
            "#,
            [],
            |row| {
                Ok(PluginApplyRecord {
                    requested_version: row.get::<_, i64>(0)? as u64,
                    requested_nonce: row.get(1)?,
                    requested_digest: row.get(2)?,
                    applied_version: row.get::<_, i64>(3)? as u64,
                    applied_digest: row.get(4)?,
                    status: row.get(6)?,
                    error_message: row.get(7)?,
                    has_last_good: row.get::<_, Option<String>>(5)?.is_some(),
                })
            },
        )
        .optional()
        .map_err(|error| error.to_string())
}

pub(crate) fn read_last_good(connection: &Connection) -> Result<Option<Value>, String> {
    connection
        .query_row(
            "SELECT last_good_json FROM desktop_platform_plugin_snapshots WHERE id = 1",
            [],
            |row| row.get::<_, Option<String>>(0),
        )
        .optional()
        .map_err(|error| error.to_string())
        .and_then(|raw| match raw.flatten() {
            Some(raw) => serde_json::from_str::<Value>(&raw)
                .map(Some)
                .map_err(|error| error.to_string()),
            None => Ok(None),
        })
}

pub(crate) fn read_requested(
    connection: &Connection,
) -> Result<Option<RequestedPluginSnapshot>, String> {
    let raw = connection
        .query_row(
            r#"
            SELECT requested_version, requested_nonce, requested_digest, requested_json
              FROM desktop_platform_plugin_snapshots WHERE id = 1
            "#,
            [],
            |row| {
                let raw_payload = row.get::<_, String>(3)?;
                let payload = serde_json::from_str::<Value>(&raw_payload)
                    .map_err(|error| rusqlite::Error::ToSqlConversionFailure(Box::new(error)))?;
                Ok(RequestedPluginSnapshot {
                    version: row.get::<_, i64>(0)? as u64,
                    nonce: row.get(1)?,
                    digest: row.get(2)?,
                    payload,
                })
            },
        )
        .optional()
        .map_err(|error| error.to_string())?;
    Ok(raw)
}

pub(crate) fn read_active_plugins(
    connection: &Connection,
    snapshot_digest: &str,
) -> Result<Vec<PluginActivationRecord>, String> {
    let mut statement = connection
        .prepare(
            r#"
            SELECT plugin_id, plugin_version, runtime, trust,
                   capabilities_json, config_json
              FROM desktop_platform_plugin_activations
             WHERE snapshot_digest = ?1
             ORDER BY plugin_id
            "#,
        )
        .map_err(|error| error.to_string())?;
    let rows = statement
        .query_map([snapshot_digest], |row| {
            let capabilities_raw = row.get::<_, String>(4)?;
            let config_raw = row.get::<_, String>(5)?;
            Ok(PluginActivationRecord {
                plugin_id: row.get(0)?,
                plugin_version: row.get(1)?,
                runtime: row.get(2)?,
                trust: row.get(3)?,
                capabilities: serde_json::from_str(&capabilities_raw)
                    .map_err(|error| rusqlite::Error::ToSqlConversionFailure(Box::new(error)))?,
                config: serde_json::from_str(&config_raw)
                    .map_err(|error| rusqlite::Error::ToSqlConversionFailure(Box::new(error)))?,
            })
        })
        .map_err(|error| error.to_string())?;
    let mut records = Vec::new();
    for row in rows {
        records.push(row.map_err(|error| error.to_string())?);
    }
    Ok(records)
}

pub(crate) fn store_runtime_artifact(
    connection: &Connection,
    artifact: &RuntimeArtifact,
) -> Result<(), String> {
    connection
        .execute(
            r#"
            INSERT INTO desktop_platform_plugin_artifacts (
                artifact_digest, plugin_id, runtime_kind, runtime_path, runtime_bytes
            ) VALUES (?1, ?2, ?3, ?4, ?5)
            ON CONFLICT(artifact_digest, plugin_id) DO UPDATE SET
                runtime_path = excluded.runtime_path,
                runtime_bytes = excluded.runtime_bytes,
                verified_at = CURRENT_TIMESTAMP
            "#,
            params![
                artifact.digest,
                artifact.plugin_id,
                artifact.runtime,
                artifact.path,
                artifact.bytes
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(crate) fn read_runtime_artifact(
    connection: &Connection,
    plugin_id: &str,
    digest: &str,
) -> Result<Option<RuntimeArtifact>, String> {
    let row = connection
        .query_row(
            r#"
            SELECT runtime_kind, runtime_path, runtime_bytes
              FROM desktop_platform_plugin_artifacts
             WHERE plugin_id = ?1 AND artifact_digest = ?2
            "#,
            params![plugin_id, digest],
            |row| {
                Ok(RuntimeArtifact {
                    plugin_id: plugin_id.to_string(),
                    digest: digest.to_string(),
                    runtime: row.get(0)?,
                    path: row.get(1)?,
                    bytes: row.get(2)?,
                })
            },
        )
        .optional()
        .map_err(|error| error.to_string())?;
    Ok(row)
}

pub(crate) fn prune_runtime_artifacts(
    connection: &mut Transaction<'_>,
    active_plugin_ids: &std::collections::BTreeSet<String>,
) -> Result<usize, String> {
    let mut statement = connection
        .prepare("SELECT DISTINCT plugin_id FROM desktop_platform_plugin_artifacts")
        .map_err(|error| error.to_string())?;
    let stored_ids = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(|error| error.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())?;
    let mut removed = 0;
    for plugin_id in stored_ids {
        if active_plugin_ids.contains(&plugin_id) {
            continue;
        }
        removed += connection
            .execute(
                "DELETE FROM desktop_platform_plugin_artifacts WHERE plugin_id = ?1",
                params![plugin_id],
            )
            .map_err(|error| error.to_string())?;
    }
    Ok(removed)
}

pub(crate) fn record_requested(
    connection: &Connection,
    version: u64,
    nonce: &str,
    digest: &str,
    raw_snapshot: &str,
) -> Result<(), String> {
    let previous = read_apply_record(connection)?;
    connection
        .execute(
            r#"
            INSERT INTO desktop_platform_plugin_snapshots (
                id, requested_version, requested_nonce, requested_digest, requested_json,
                applied_version, applied_digest, last_good_json, status
            ) VALUES (1, ?1, ?2, ?3, ?4, ?5, ?6, ?7, 'pending')
            ON CONFLICT(id) DO UPDATE SET
                requested_version = excluded.requested_version,
                requested_nonce = excluded.requested_nonce,
                requested_digest = excluded.requested_digest,
                requested_json = excluded.requested_json,
                applied_version = excluded.applied_version,
                applied_digest = excluded.applied_digest,
                last_good_json = excluded.last_good_json,
                status = 'pending',
                error_message = NULL,
                updated_at = CURRENT_TIMESTAMP
            "#,
            params![
                version as i64,
                nonce,
                digest,
                raw_snapshot,
                previous.as_ref().map_or(0, |record| record.applied_version) as i64,
                previous.and_then(|record| record.applied_digest),
                read_last_good_json(connection)?
            ],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn read_last_good_json(connection: &Connection) -> Result<Option<String>, String> {
    connection
        .query_row(
            "SELECT last_good_json FROM desktop_platform_plugin_snapshots WHERE id = 1",
            [],
            |row| row.get::<_, Option<String>>(0),
        )
        .optional()
        .map_err(|error| error.to_string())
        .map(Option::flatten)
}

pub(crate) fn record_ack(
    connection: &mut Connection,
    requested: &RequestedPluginSnapshot,
) -> Result<Vec<PluginActivationRecord>, String> {
    let prepared = prepare_plugins(connection, &requested.payload)?;
    let mut transaction = connection
        .transaction()
        .map_err(|error| error.to_string())?;
    for plugin in &prepared {
        let capabilities =
            serde_json::to_string(&plugin.capabilities).map_err(|error| error.to_string())?;
        let config = serde_json::to_string(&plugin.config).map_err(|error| error.to_string())?;
        transaction
            .execute(
                r#"
                INSERT INTO desktop_platform_plugin_activations (
                    snapshot_digest, plugin_id, plugin_version, runtime, trust,
                    capabilities_json, config_json
                ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
                ON CONFLICT(snapshot_digest, plugin_id) DO UPDATE SET
                    plugin_version = excluded.plugin_version,
                    runtime = excluded.runtime,
                    trust = excluded.trust,
                    capabilities_json = excluded.capabilities_json,
                    config_json = excluded.config_json,
                    activated_at = CURRENT_TIMESTAMP
                "#,
                params![
                    requested.digest,
                    plugin.plugin_id,
                    plugin.plugin_version,
                    plugin.runtime,
                    plugin.trust,
                    capabilities,
                    config
                ],
            )
            .map_err(|error| error.to_string())?;
    }
    update_ack(
        &transaction,
        requested.version,
        &requested.digest,
        &requested.payload.to_string(),
    )?;
    let active_plugin_ids = requested
        .payload
        .get("plugins")
        .and_then(Value::as_array)
        .map(|plugins| {
            plugins
                .iter()
                .filter_map(|plugin| plugin.get("id").and_then(Value::as_str).map(String::from))
                .collect::<std::collections::BTreeSet<_>>()
        })
        .unwrap_or_default();
    prune_runtime_artifacts(&mut transaction, &active_plugin_ids)?;
    transaction.commit().map_err(|error| error.to_string())?;

    Ok(prepared
        .into_iter()
        .map(|plugin| PluginActivationRecord {
            plugin_id: plugin.plugin_id,
            plugin_version: plugin.plugin_version,
            runtime: plugin.runtime,
            trust: plugin.trust,
            capabilities: plugin.capabilities,
            config: plugin.config,
        })
        .collect())
}

fn update_ack(
    connection: &Connection,
    version: u64,
    digest: &str,
    raw_snapshot: &str,
) -> Result<(), String> {
    connection
        .execute(
            r#"
            UPDATE desktop_platform_plugin_snapshots
               SET applied_version = ?1, applied_digest = ?2, last_good_json = ?3,
                   status = 'ack', error_message = NULL, updated_at = CURRENT_TIMESTAMP
             WHERE id = 1
            "#,
            params![version as i64, digest, raw_snapshot],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

pub(crate) fn record_nack(connection: &Connection, error: &str) -> Result<(), String> {
    connection
        .execute(
            r#"
            UPDATE desktop_platform_plugin_snapshots
               SET status = 'nack', error_message = ?1, updated_at = CURRENT_TIMESTAMP
             WHERE id = 1
            "#,
            params![error],
        )
        .map(|_| ())
        .map_err(|error| error.to_string())
}

fn required_runtime_artifact(
    connection: &Connection,
    plugin_id: &str,
    config: &Value,
) -> Result<RuntimeArtifact, String> {
    let artifact_config = config
        .get("artifact")
        .and_then(Value::as_object)
        .ok_or_else(|| format!("plugin {plugin_id} has no runtime artifact reference"))?;
    let digest = bounded_text(
        artifact_config.get("layer_sha256"),
        64,
        "runtime artifact digest",
    )?;
    if digest
        .chars()
        .any(|character| !character.is_ascii_hexdigit())
    {
        return Err(format!(
            "plugin {plugin_id} runtime artifact digest is invalid"
        ));
    }
    read_runtime_artifact(connection, plugin_id, &digest)?
        .ok_or_else(|| format!("plugin {plugin_id} runtime {digest} is not installed or verified"))
}

fn prepare_plugins(
    connection: &Connection,
    payload: &Value,
) -> Result<Vec<PreparedPlugin>, String> {
    let Some(plugins) = payload.get("plugins").and_then(Value::as_array) else {
        return Err("snapshot plugins must be an array".to_string());
    };
    if plugins.len() > 256 {
        return Err("snapshot contains more than 256 plugins".to_string());
    }

    let mut prepared = Vec::with_capacity(plugins.len());
    let mut contracts: Vec<(String, String)> = Vec::new();
    for (index, plugin) in plugins.iter().enumerate() {
        let Some(object) = plugin.as_object() else {
            return Err(format!("plugin {index} must be an object"));
        };
        let plugin_id = bounded_text(object.get("id"), 255, "plugin id")?;
        let plugin_version = semantic_version(object.get("version"))?;
        let runtime = bounded_text(object.get("runtime"), 32, "plugin runtime")?;
        let trust = bounded_text(object.get("trust"), 32, "plugin trust")?;
        let supported = matches!(
            (runtime.as_str(), trust.as_str()),
            ("python-trusted", "builtin")
                | (
                    "wasm",
                    "builtin" | "signed" | "tenant-approved" | "untrusted"
                )
                | (
                    "mcp",
                    "builtin" | "signed" | "tenant-approved" | "untrusted"
                )
                | (
                    "subprocess",
                    "builtin" | "signed" | "tenant-approved" | "untrusted"
                )
                | ("frontend", "builtin" | "signed")
        );
        if !supported {
            return Err(format!(
                "plugin {plugin_id} uses an unsupported runtime/trust pair"
            ));
        }
        let Some(capability_values) = object.get("provides").and_then(Value::as_array) else {
            return Err(format!("plugin {plugin_id} provides must be an array"));
        };
        let mut capabilities = Vec::with_capacity(capability_values.len());
        for capability in capability_values {
            let Some(capability_object) = capability.as_object() else {
                return Err(format!("plugin {plugin_id} capability must be an object"));
            };
            let kind = bounded_text(capability_object.get("kind"), 64, "capability kind")?;
            bounded_text(capability_object.get("id"), 255, "capability id")?;
            let contract = bounded_text(
                capability_object.get("contract"),
                255,
                "capability contract",
            )?;
            if matches!(kind.as_str(), "agent_loop" | "credential_source") && trust != "builtin" {
                return Err(format!(
                    "plugin {plugin_id} cannot provide protected capability {kind}"
                ));
            }
            if let Some(permissions) = capability_object
                .get("permissions")
                .and_then(Value::as_array)
            {
                for permission in permissions {
                    bounded_text(Some(permission), 191, "capability permission")?;
                }
            }
            if contracts
                .iter()
                .any(|(existing, owner)| existing == &contract && owner != &plugin_id)
            {
                return Err(format!(
                    "capability contract {contract} has multiple owners"
                ));
            }
            contracts.push((contract, plugin_id.clone()));
            capabilities.push(capability.clone());
        }

        let config = object
            .get("config")
            .cloned()
            .unwrap_or_else(|| Value::Object(Default::default()));
        if !config.is_object() {
            return Err(format!("plugin {plugin_id} config must be an object"));
        }
        validate_config(&config).map_err(|error| format!("plugin {plugin_id}: {error}"))?;
        if runtime != "python-trusted" {
            let artifact = required_runtime_artifact(connection, &plugin_id, &config)?;
            if artifact.runtime != runtime {
                return Err(format!(
                    "plugin {plugin_id} artifact does not provide runtime {}",
                    runtime
                ));
            }
        }

        if let Some(requirements) = object.get("requires").and_then(Value::as_array) {
            for requirement in requirements {
                let required = bounded_text(
                    requirement
                        .as_object()
                        .and_then(|value| value.get("capability")),
                    255,
                    "required capability",
                )?;
                if !contracts.iter().any(|(contract, _)| contract == &required) {
                    return Err(format!(
                        "plugin {plugin_id} requires unavailable capability {required}"
                    ));
                }
            }
        }

        prepared.push(PreparedPlugin {
            plugin_id,
            plugin_version,
            runtime,
            trust,
            capabilities,
            config,
        });
    }
    Ok(prepared)
}

fn bounded_text(value: Option<&Value>, limit: usize, label: &str) -> Result<String, String> {
    let Some(text) = value.and_then(Value::as_str) else {
        return Err(format!("{label} must be a string"));
    };
    if text.trim().is_empty() || text.len() > limit || text != text.trim() {
        return Err(format!("{label} is invalid"));
    }
    Ok(text.to_string())
}

fn semantic_version(value: Option<&Value>) -> Result<String, String> {
    let text = bounded_text(value, 64, "plugin version")?;
    let parts: Vec<&str> = text.split('.').collect();
    if parts.len() != 3
        || !parts
            .iter()
            .all(|part| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit()))
    {
        return Err("plugin version must be numeric major.minor.patch".to_string());
    }
    Ok(text)
}

fn validate_config(value: &Value) -> Result<(), String> {
    match value {
        Value::Object(object) => {
            for (key, child) in object {
                let normalized = key.to_ascii_lowercase();
                if [
                    "api_key",
                    "apikey",
                    "secret",
                    "password",
                    "token",
                    "credential",
                ]
                .iter()
                .any(|sensitive| normalized.contains(sensitive))
                {
                    let reference = child.as_str().unwrap_or_default();
                    if !reference.is_empty()
                        && !reference.starts_with("vault://")
                        && !reference.starts_with("env://")
                    {
                        return Err(format!(
                            "config field {key} must use a credential reference"
                        ));
                    }
                }
                validate_config(child)?;
            }
            Ok(())
        }
        Value::Array(items) => {
            for item in items {
                validate_config(item)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn snapshot(digest: &str) -> Value {
        json!({
            "schema_version": 1,
            "profile_id": "test-profile",
            "plugins": [],
            "digest": digest
        })
    }

    fn plugin_snapshot(digest: &str) -> Value {
        json!({
            "schema_version": 1,
            "profile_id": "test-profile",
            "plugins": [{
                "schema_version": 1,
                "id": "workspace-runtime",
                "version": "1.2.3",
                "runtime": "python-trusted",
                "trust": "builtin",
                "provides": [{
                    "kind": "hook",
                    "id": "before_response",
                    "contract": "hook:before_response",
                    "permissions": []
                }],
                "config": {"credential_ref": "vault://plugins/workspace/token"},
                "digest": digest
            }],
            "digest": digest
        })
    }

    #[test]
    fn requested_snapshot_roundtrips_without_exposing_last_good_payload() {
        let connection = Connection::open_in_memory().expect("plugin database");
        initialize_schema(&connection).expect("plugin schema");
        let digest = "c".repeat(64);
        let payload = snapshot(&digest);

        record_requested(&connection, 5, "nonce-5", &digest, &payload.to_string())
            .expect("record requested");
        let requested = read_requested(&connection)
            .expect("requested snapshot")
            .expect("requested row");

        assert_eq!(requested.version, 5);
        assert_eq!(requested.nonce, "nonce-5");
        assert_eq!(requested.digest, digest);
        assert_eq!(requested.payload, payload);
        assert_eq!(read_last_good(&connection).expect("last good"), None);
    }

    #[test]
    fn requested_ack_and_nack_preserve_last_good() {
        let mut connection = Connection::open_in_memory().expect("plugin database");
        initialize_schema(&connection).expect("plugin schema");
        let good_digest = "a".repeat(64);
        let good = snapshot(&good_digest).to_string();

        record_requested(&connection, 2, "nonce-2", &good_digest, &good).expect("record requested");
        let requested = read_requested(&connection)
            .expect("read requested")
            .expect("requested row");
        record_ack(&mut connection, &requested).expect("record ack");
        let record = read_apply_record(&connection)
            .expect("read apply record")
            .expect("apply record");
        assert_eq!(record.status, "ack");
        assert_eq!(record.applied_version, 2);
        assert_eq!(
            read_last_good(&connection).expect("last good"),
            Some(snapshot(&good_digest))
        );

        let bad_digest = "b".repeat(64);
        let bad = snapshot(&bad_digest).to_string();
        record_requested(&connection, 3, "nonce-3", &bad_digest, &bad)
            .expect("record bad requested");
        record_nack(&connection, "plugin failed").expect("record nack");
        let record = read_apply_record(&connection)
            .expect("reread apply record")
            .expect("apply record");
        assert_eq!(record.status, "nack");
        assert_eq!(record.applied_version, 2);
        assert_eq!(
            read_last_good(&connection).expect("retained last good"),
            Some(snapshot(&good_digest))
        );
    }

    #[test]
    fn activation_is_atomic_and_persists_the_active_capability_inventory() {
        let mut connection = Connection::open_in_memory().expect("plugin database");
        initialize_schema(&connection).expect("plugin schema");
        let digest = "d".repeat(64);
        let payload = plugin_snapshot(&digest);
        let requested = RequestedPluginSnapshot {
            version: 6,
            nonce: "nonce-6".to_string(),
            digest: digest.clone(),
            payload: payload.clone(),
        };

        record_requested(&connection, 6, "nonce-6", &digest, &payload.to_string())
            .expect("record requested");
        let activated = record_ack(&mut connection, &requested).expect("activate snapshot");

        assert_eq!(activated.len(), 1);
        assert_eq!(activated[0].plugin_id, "workspace-runtime");
        assert_eq!(
            read_active_plugins(&connection, &digest).expect("active plugins"),
            activated
        );
    }

    #[test]
    fn activation_rejects_external_runtimes_and_plaintext_credentials_before_ack() {
        let mut connection = Connection::open_in_memory().expect("plugin database");
        initialize_schema(&connection).expect("plugin schema");
        let digest = "e".repeat(64);
        let payload = json!({
            "schema_version": 1,
            "profile_id": "test-profile",
            "plugins": [{
                "schema_version": 1,
                "id": "external-tool",
                "version": "0.1.0",
                "runtime": "wasm",
                "trust": "signed",
                "provides": [{"kind": "tool", "id": "demo", "contract": "tool:demo"}],
                "config": {"credential_ref": "vault://plugins/external/token"}
            }],
            "digest": digest
        });
        record_requested(&connection, 7, "nonce-7", &digest, &payload.to_string())
            .expect("record requested");
        let requested = RequestedPluginSnapshot {
            version: 7,
            nonce: "nonce-7".to_string(),
            digest,
            payload,
        };

        let error = record_ack(&mut connection, &requested).expect_err("activation must fail");

        assert!(error.contains("runtime artifact"));
        let record = read_apply_record(&connection)
            .expect("apply record")
            .expect("row");
        assert_eq!(record.status, "pending");
        assert_eq!(record.applied_digest, None);
    }
}
