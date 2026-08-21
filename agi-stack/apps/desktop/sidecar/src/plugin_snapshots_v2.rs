//! Durable protocol-v2 plugin distribution state.

use agistack_plugin_host::{
    parse_control_plane_distribution_v2, ApplyStatusV2, ControlPlaneDistributionV2,
    SnapshotApplyReceiptV2,
};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use thiserror::Error;

const SCHEMA_VERSION: u64 = 2;

/// One strict v2 requested/applied/last-good state record.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct PluginSnapshotStateV2 {
    pub(crate) requested: Option<ControlPlaneDistributionV2>,
    pub(crate) receipt: Option<SnapshotApplyReceiptV2>,
    pub(crate) last_good: Option<ControlPlaneDistributionV2>,
}

#[derive(Debug, Error, Clone, Eq, PartialEq)]
pub(crate) enum PluginSnapshotStoreV2Error {
    #[error("incompatible_schema_version")]
    IncompatibleSchemaVersion,
    #[error("persisted plugin v2 state is invalid: {0}")]
    InvalidState(String),
    #[error("plugin v2 receipt is stale")]
    StaleReceipt,
    #[error("plugin v2 nonce belongs to another distribution")]
    NonceConflict,
    #[error("plugin v2 receipt does not match the requested distribution")]
    ReceiptMismatch,
    #[error("plugin v2 state storage failed: {0}")]
    Storage(String),
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PersistedStateV2 {
    schema_version: u64,
    requested: Option<Value>,
    receipt: Option<SnapshotApplyReceiptV2>,
    last_good: Option<Value>,
}

pub(crate) fn initialize_schema(connection: &Connection) -> Result<(), PluginSnapshotStoreV2Error> {
    connection
        .execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS desktop_platform_plugin_state_v2 (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            "#,
        )
        .map_err(storage_error)
}

pub(crate) fn read_state(
    connection: &Connection,
) -> Result<Option<PluginSnapshotStateV2>, PluginSnapshotStoreV2Error> {
    let raw = connection
        .query_row(
            "SELECT state_json FROM desktop_platform_plugin_state_v2 WHERE id = 1",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage_error)?;
    raw.map(|item| parse_state(&item)).transpose()
}

pub(crate) fn read_last_good(
    connection: &Connection,
) -> Result<Option<ControlPlaneDistributionV2>, PluginSnapshotStoreV2Error> {
    Ok(read_state(connection)?.and_then(|state| state.last_good))
}

pub(crate) fn record_requested(
    connection: &Connection,
    distribution: &ControlPlaneDistributionV2,
) -> Result<(), PluginSnapshotStoreV2Error> {
    let existing = read_state(connection)?;
    if let Some(requested) = existing.as_ref().and_then(|state| state.requested.as_ref()) {
        if requested.envelope.nonce == distribution.envelope.nonce && requested != distribution {
            return Err(PluginSnapshotStoreV2Error::NonceConflict);
        }
    }
    let state = PluginSnapshotStateV2 {
        requested: Some(distribution.clone()),
        receipt: None,
        last_good: existing.and_then(|item| item.last_good),
    };
    write_state(connection, &state)
}

pub(crate) fn record_receipt(
    connection: &mut Connection,
    nonce: &str,
    receipt: &SnapshotApplyReceiptV2,
) -> Result<(), PluginSnapshotStoreV2Error> {
    let mut state = read_state(connection)?.ok_or(PluginSnapshotStoreV2Error::StaleReceipt)?;
    let requested = state
        .requested
        .as_ref()
        .ok_or(PluginSnapshotStoreV2Error::StaleReceipt)?;
    if requested.envelope.nonce != nonce {
        return Err(PluginSnapshotStoreV2Error::StaleReceipt);
    }
    validate_receipt(&state, receipt)?;
    if receipt.status == ApplyStatusV2::Ack {
        state.last_good = Some(requested.clone());
    }
    state.receipt = Some(receipt.clone());

    let transaction = connection.transaction().map_err(storage_error)?;
    write_state(&transaction, &state)?;
    transaction.commit().map_err(storage_error)
}

fn validate_receipt(
    state: &PluginSnapshotStateV2,
    receipt: &SnapshotApplyReceiptV2,
) -> Result<(), PluginSnapshotStoreV2Error> {
    let requested = state
        .requested
        .as_ref()
        .ok_or(PluginSnapshotStoreV2Error::ReceiptMismatch)?;
    if receipt.requested_version != requested.envelope.version
        || receipt.requested_digest != requested.snapshot.digest
    {
        return Err(PluginSnapshotStoreV2Error::ReceiptMismatch);
    }
    match receipt.status {
        ApplyStatusV2::Ack => {
            let valid = receipt.applied_version == Some(requested.envelope.version)
                && receipt.applied_digest.as_deref() == Some(requested.snapshot.digest.as_str())
                && receipt.error_code.is_none()
                && receipt.error_message.is_none();
            if !valid {
                return Err(PluginSnapshotStoreV2Error::ReceiptMismatch);
            }
        }
        ApplyStatusV2::Nack => {
            let expected_version = state.last_good.as_ref().map(|item| item.envelope.version);
            let expected_digest = state
                .last_good
                .as_ref()
                .map(|item| item.snapshot.digest.as_str());
            let valid = receipt.applied_version == expected_version
                && receipt.applied_digest.as_deref() == expected_digest
                && receipt
                    .error_code
                    .as_deref()
                    .is_some_and(|code| !code.is_empty());
            if !valid {
                return Err(PluginSnapshotStoreV2Error::ReceiptMismatch);
            }
        }
    }
    Ok(())
}

fn parse_state(raw: &str) -> Result<PluginSnapshotStateV2, PluginSnapshotStoreV2Error> {
    let value: Value = serde_json::from_str(raw)
        .map_err(|error| PluginSnapshotStoreV2Error::InvalidState(error.to_string()))?;
    if value.get("schema_version").and_then(Value::as_u64) != Some(SCHEMA_VERSION) {
        return Err(PluginSnapshotStoreV2Error::IncompatibleSchemaVersion);
    }
    let persisted: PersistedStateV2 = serde_json::from_value(value)
        .map_err(|error| PluginSnapshotStoreV2Error::InvalidState(error.to_string()))?;
    Ok(PluginSnapshotStateV2 {
        requested: persisted.requested.map(parse_distribution).transpose()?,
        receipt: persisted.receipt,
        last_good: persisted.last_good.map(parse_distribution).transpose()?,
    })
}

fn parse_distribution(
    value: Value,
) -> Result<ControlPlaneDistributionV2, PluginSnapshotStoreV2Error> {
    parse_control_plane_distribution_v2(&value.to_string())
        .map_err(|error| PluginSnapshotStoreV2Error::InvalidState(error.to_string()))
}

fn write_state(
    connection: &Connection,
    state: &PluginSnapshotStateV2,
) -> Result<(), PluginSnapshotStoreV2Error> {
    let raw = serde_json::to_string(&PersistedStateV2 {
        schema_version: SCHEMA_VERSION,
        requested: state
            .requested
            .as_ref()
            .map(serde_json::to_value)
            .transpose()
            .map_err(|error| PluginSnapshotStoreV2Error::InvalidState(error.to_string()))?,
        receipt: state.receipt.clone(),
        last_good: state
            .last_good
            .as_ref()
            .map(serde_json::to_value)
            .transpose()
            .map_err(|error| PluginSnapshotStoreV2Error::InvalidState(error.to_string()))?,
    })
    .map_err(|error| PluginSnapshotStoreV2Error::InvalidState(error.to_string()))?;
    connection
        .execute(
            r#"
            INSERT INTO desktop_platform_plugin_state_v2 (id, state_json)
            VALUES (1, ?1)
            ON CONFLICT(id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = CURRENT_TIMESTAMP
            "#,
            params![raw],
        )
        .map(|_| ())
        .map_err(storage_error)
}

fn storage_error(error: rusqlite::Error) -> PluginSnapshotStoreV2Error {
    PluginSnapshotStoreV2Error::Storage(error.to_string())
}

#[cfg(test)]
mod tests {
    use agistack_plugin_host::parse_control_plane_distribution_v2;
    use rusqlite::{params, Connection};
    use serde_json::Value;

    use super::*;

    const SNAPSHOT: &str =
        include_str!("../../../../../shared/fixtures/platform-plugin-profile.v2.json");

    fn distribution(version: u64, nonce: &str) -> agistack_plugin_host::ControlPlaneDistributionV2 {
        let snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
        let digest = snapshot["digest"].as_str().expect("digest");
        let raw = serde_json::json!({
            "schema_version": 2,
            "descriptor": {
                "profile_id": snapshot["profile_id"],
                "generation": snapshot["generation"],
                "digest": digest,
            },
            "snapshot": snapshot,
            "envelope": {
                "version": version,
                "nonce": nonce,
                "snapshot_digest": digest,
                "type_url": "types.memstack.ai/plugin.profile.v2",
            },
        });
        parse_control_plane_distribution_v2(&raw.to_string()).expect("distribution must parse")
    }

    fn receipt(
        distribution: &agistack_plugin_host::ControlPlaneDistributionV2,
        status: ApplyStatusV2,
    ) -> SnapshotApplyReceiptV2 {
        let accepted = status == ApplyStatusV2::Ack;
        SnapshotApplyReceiptV2 {
            status,
            requested_version: distribution.envelope.version,
            requested_digest: distribution.snapshot.digest.clone(),
            applied_version: accepted.then_some(distribution.envelope.version),
            applied_digest: accepted.then(|| distribution.snapshot.digest.clone()),
            error_code: (!accepted).then(|| "generation_apply_failed".into()),
            error_message: (!accepted).then(|| "test failure".into()),
        }
    }

    #[test]
    fn ack_advances_last_good_and_survives_restart() {
        let mut connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        let requested = distribution(11, "nonce-11");

        record_requested(&connection, &requested).expect("requested");
        record_receipt(
            &mut connection,
            "nonce-11",
            &receipt(&requested, ApplyStatusV2::Ack),
        )
        .expect("ack");

        let restored = read_last_good(&connection)
            .expect("read last-good")
            .expect("last-good must exist");
        assert_eq!(restored, requested);
        let state = read_state(&connection).expect("read state").expect("state");
        assert_eq!(state.receipt.expect("receipt").status, ApplyStatusV2::Ack);
    }

    #[test]
    fn nack_and_stale_receipt_preserve_last_good() {
        let mut connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        let first = distribution(11, "nonce-11");
        record_requested(&connection, &first).expect("first requested");
        record_receipt(
            &mut connection,
            "nonce-11",
            &receipt(&first, ApplyStatusV2::Ack),
        )
        .expect("first ack");

        let second = distribution(12, "nonce-12");
        record_requested(&connection, &second).expect("second requested");
        let nack = SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Nack,
            requested_version: second.envelope.version,
            requested_digest: second.snapshot.digest.clone(),
            applied_version: Some(first.envelope.version),
            applied_digest: Some(first.snapshot.digest.clone()),
            error_code: Some("generation_apply_failed".into()),
            error_message: Some("test failure".into()),
        };
        record_receipt(&mut connection, "nonce-12", &nack).expect("second nack");
        assert_eq!(read_last_good(&connection).expect("last-good"), Some(first));

        let stale = record_receipt(
            &mut connection,
            "nonce-11",
            &receipt(&second, ApplyStatusV2::Ack),
        )
        .expect_err("stale receipt must fail");
        assert_eq!(stale, PluginSnapshotStoreV2Error::StaleReceipt);
    }

    #[test]
    fn v1_persisted_state_is_rejected_without_fallback() {
        let connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        connection
            .execute(
                "INSERT INTO desktop_platform_plugin_state_v2 (id, state_json) VALUES (1, ?1)",
                params![r#"{"schema_version":1}"#],
            )
            .expect("seed incompatible state");

        assert_eq!(
            read_state(&connection),
            Err(PluginSnapshotStoreV2Error::IncompatibleSchemaVersion)
        );
    }
}
