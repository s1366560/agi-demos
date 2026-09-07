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
const AUTHORITY_FINGERPRINT_PREFIX: &str = "sha256:";

/// One strict v2 requested/applied/last-good state record.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct PluginSnapshotStateV2 {
    pub(crate) authority_fingerprint: Option<String>,
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
    #[error("plugin v2 authority fingerprint is invalid")]
    InvalidAuthorityFingerprint,
    #[error("plugin v2 state belongs to another authority")]
    AuthorityMismatch,
    #[error("plugin v2 state storage failed: {0}")]
    Storage(String),
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PersistedStateV2 {
    schema_version: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    authority_fingerprint: Option<String>,
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
            CREATE TABLE IF NOT EXISTS desktop_platform_plugin_authority_state_v2 (
                authority_fingerprint TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            "#,
        )
        .map_err(storage_error)?;
    migrate_legacy_state(connection)
}

pub(crate) fn read_state(
    connection: &Connection,
    authority_fingerprint: &str,
) -> Result<Option<PluginSnapshotStateV2>, PluginSnapshotStoreV2Error> {
    validate_authority_fingerprint(authority_fingerprint)?;
    let raw = connection
        .query_row(
            r#"
            SELECT state_json
            FROM desktop_platform_plugin_authority_state_v2
            WHERE authority_fingerprint = ?1
            "#,
            params![authority_fingerprint],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage_error)?;
    if let Some(raw) = raw {
        return parse_state(&raw).map(Some);
    }
    let legacy_raw = connection
        .query_row(
            "SELECT state_json FROM desktop_platform_plugin_state_v2 WHERE id = 1",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage_error)?;
    legacy_raw
        .map(|item| parse_state(&item))
        .transpose()
        .map(|state| {
            state
                .filter(|item| item.authority_fingerprint.as_deref() == Some(authority_fingerprint))
        })
}

pub(crate) fn read_last_good(
    connection: &Connection,
    authority_fingerprint: &str,
) -> Result<Option<ControlPlaneDistributionV2>, PluginSnapshotStoreV2Error> {
    validate_authority_fingerprint(authority_fingerprint)?;
    Ok(read_state(connection, authority_fingerprint)?.and_then(|state| state.last_good))
}

pub(crate) fn record_requested(
    connection: &Connection,
    authority_fingerprint: &str,
    distribution: &ControlPlaneDistributionV2,
) -> Result<(), PluginSnapshotStoreV2Error> {
    validate_authority_fingerprint(authority_fingerprint)?;
    let existing = read_state(connection, authority_fingerprint)?;
    if let Some(requested) = existing.as_ref().and_then(|state| state.requested.as_ref()) {
        if requested.envelope.nonce == distribution.envelope.nonce && requested != distribution {
            return Err(PluginSnapshotStoreV2Error::NonceConflict);
        }
    }
    let state = PluginSnapshotStateV2 {
        authority_fingerprint: Some(authority_fingerprint.to_owned()),
        requested: Some(distribution.clone()),
        receipt: None,
        last_good: existing.and_then(|item| item.last_good),
    };
    write_state(connection, &state)
}

pub(crate) fn record_receipt(
    connection: &mut Connection,
    authority_fingerprint: &str,
    nonce: &str,
    receipt: &SnapshotApplyReceiptV2,
) -> Result<(), PluginSnapshotStoreV2Error> {
    validate_authority_fingerprint(authority_fingerprint)?;
    let Some(mut state) = read_state(connection, authority_fingerprint)? else {
        return if requested_nonce_belongs_to_other_authority(
            connection,
            authority_fingerprint,
            nonce,
        )? {
            Err(PluginSnapshotStoreV2Error::AuthorityMismatch)
        } else {
            Err(PluginSnapshotStoreV2Error::StaleReceipt)
        };
    };
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
    let Some(authority_fingerprint) = persisted.authority_fingerprint.as_deref() else {
        return Ok(PluginSnapshotStateV2 {
            authority_fingerprint: None,
            requested: None,
            receipt: None,
            last_good: None,
        });
    };
    validate_authority_fingerprint(authority_fingerprint).map_err(|_| {
        PluginSnapshotStoreV2Error::InvalidState("authority fingerprint is invalid".to_string())
    })?;
    Ok(PluginSnapshotStateV2 {
        authority_fingerprint: persisted.authority_fingerprint,
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
    let authority_fingerprint = state.authority_fingerprint.as_deref().ok_or_else(|| {
        PluginSnapshotStoreV2Error::InvalidState("authority fingerprint is required".to_string())
    })?;
    validate_authority_fingerprint(authority_fingerprint)?;
    let raw = serde_json::to_string(&PersistedStateV2 {
        schema_version: SCHEMA_VERSION,
        authority_fingerprint: Some(authority_fingerprint.to_owned()),
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
            INSERT INTO desktop_platform_plugin_authority_state_v2 (
                authority_fingerprint,
                state_json
            )
            VALUES (?1, ?2)
            ON CONFLICT(authority_fingerprint) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = CURRENT_TIMESTAMP
            "#,
            params![authority_fingerprint, raw],
        )
        .map(|_| ())
        .map_err(storage_error)
}

fn migrate_legacy_state(connection: &Connection) -> Result<(), PluginSnapshotStoreV2Error> {
    let legacy_raw = connection
        .query_row(
            "SELECT state_json FROM desktop_platform_plugin_state_v2 WHERE id = 1",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(storage_error)?;
    let Some(legacy_raw) = legacy_raw else {
        return Ok(());
    };
    let Ok(state) = parse_state(&legacy_raw) else {
        return Ok(());
    };
    let Some(authority_fingerprint) = state.authority_fingerprint else {
        return Ok(());
    };
    connection
        .execute(
            r#"
            INSERT OR IGNORE INTO desktop_platform_plugin_authority_state_v2 (
                authority_fingerprint,
                state_json
            )
            VALUES (?1, ?2)
            "#,
            params![authority_fingerprint, legacy_raw],
        )
        .map(|_| ())
        .map_err(storage_error)
}

fn requested_nonce_belongs_to_other_authority(
    connection: &Connection,
    authority_fingerprint: &str,
    nonce: &str,
) -> Result<bool, PluginSnapshotStoreV2Error> {
    let mut statement = connection
        .prepare(
            r#"
            SELECT authority_fingerprint, state_json
            FROM desktop_platform_plugin_authority_state_v2
            WHERE authority_fingerprint != ?1
            "#,
        )
        .map_err(storage_error)?;
    let rows = statement
        .query_map(params![authority_fingerprint], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })
        .map_err(storage_error)?;
    for row in rows {
        let (_, raw) = row.map_err(storage_error)?;
        let state = parse_state(&raw)?;
        if state
            .requested
            .as_ref()
            .is_some_and(|requested| requested.envelope.nonce == nonce)
        {
            return Ok(true);
        }
    }
    Ok(false)
}

fn validate_authority_fingerprint(
    authority_fingerprint: &str,
) -> Result<(), PluginSnapshotStoreV2Error> {
    let Some(digest) = authority_fingerprint.strip_prefix(AUTHORITY_FINGERPRINT_PREFIX) else {
        return Err(PluginSnapshotStoreV2Error::InvalidAuthorityFingerprint);
    };
    let valid = digest.len() == 64
        && digest
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte));
    if !valid {
        return Err(PluginSnapshotStoreV2Error::InvalidAuthorityFingerprint);
    }
    Ok(())
}

fn storage_error(error: rusqlite::Error) -> PluginSnapshotStoreV2Error {
    PluginSnapshotStoreV2Error::Storage(error.to_string())
}

#[cfg(test)]
mod tests {
    use agistack_plugin_host::parse_control_plane_distribution_v2;
    use rusqlite::{params, Connection};
    use serde_json::Value;
    use sha2::{Digest, Sha256};

    use super::*;

    const SNAPSHOT: &str =
        include_str!("../../../../../shared/fixtures/platform-plugin-profile.v2.json");
    const AUTHORITY_A: &str =
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const AUTHORITY_B: &str =
        "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";

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

    fn distribution_with_explicit_null(
        version: u64,
        nonce: &str,
    ) -> agistack_plugin_host::ControlPlaneDistributionV2 {
        let mut snapshot: Value = serde_json::from_str(SNAPSHOT).expect("fixture must parse");
        snapshot["manifests"][0]["modules"][0]["artifact"]["signature"] = Value::Null;
        let mut digest_payload = snapshot.clone();
        digest_payload
            .as_object_mut()
            .expect("snapshot object")
            .remove("digest");
        let canonical = serde_jcs::to_vec(&digest_payload).expect("snapshot must canonicalize");
        snapshot["digest"] = Value::String(format!("{:x}", Sha256::digest(canonical)));
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

        record_requested(&connection, AUTHORITY_A, &requested).expect("requested");
        record_receipt(
            &mut connection,
            AUTHORITY_A,
            "nonce-11",
            &receipt(&requested, ApplyStatusV2::Ack),
        )
        .expect("ack");

        let restored = read_last_good(&connection, AUTHORITY_A)
            .expect("read last-good")
            .expect("last-good must exist");
        assert_eq!(restored, requested);
        let state = read_state(&connection, AUTHORITY_A)
            .expect("read state")
            .expect("state");
        assert_eq!(state.receipt.expect("receipt").status, ApplyStatusV2::Ack);
    }

    #[test]
    fn nack_and_stale_receipt_preserve_last_good() {
        let mut connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        let first = distribution(11, "nonce-11");
        record_requested(&connection, AUTHORITY_A, &first).expect("first requested");
        record_receipt(
            &mut connection,
            AUTHORITY_A,
            "nonce-11",
            &receipt(&first, ApplyStatusV2::Ack),
        )
        .expect("first ack");

        let second = distribution(12, "nonce-12");
        record_requested(&connection, AUTHORITY_A, &second).expect("second requested");
        let nack = SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Nack,
            requested_version: second.envelope.version,
            requested_digest: second.snapshot.digest.clone(),
            applied_version: Some(first.envelope.version),
            applied_digest: Some(first.snapshot.digest.clone()),
            error_code: Some("generation_apply_failed".into()),
            error_message: Some("test failure".into()),
        };
        record_receipt(&mut connection, AUTHORITY_A, "nonce-12", &nack).expect("second nack");
        assert_eq!(
            read_last_good(&connection, AUTHORITY_A).expect("last-good"),
            Some(first)
        );

        let stale = record_receipt(
            &mut connection,
            AUTHORITY_A,
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
            read_state(&connection, AUTHORITY_A),
            Err(PluginSnapshotStoreV2Error::IncompatibleSchemaVersion)
        );
    }

    #[test]
    fn authority_switch_never_restores_or_accepts_receipts_for_foreign_state() {
        let mut connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        let first = distribution(11, "nonce-11");
        record_requested(&connection, AUTHORITY_A, &first).expect("first requested");
        record_receipt(
            &mut connection,
            AUTHORITY_A,
            "nonce-11",
            &receipt(&first, ApplyStatusV2::Ack),
        )
        .expect("first ack");

        assert_eq!(
            read_last_good(&connection, AUTHORITY_B).expect("foreign read"),
            None
        );
        assert_eq!(
            record_receipt(
                &mut connection,
                AUTHORITY_B,
                "nonce-11",
                &receipt(&first, ApplyStatusV2::Ack),
            ),
            Err(PluginSnapshotStoreV2Error::AuthorityMismatch)
        );

        let second = distribution(12, "nonce-12");
        record_requested(&connection, AUTHORITY_B, &second).expect("second requested");
        assert_eq!(
            read_last_good(&connection, AUTHORITY_A).expect("first authority last-good"),
            Some(first)
        );
        let state = read_state(&connection, AUTHORITY_B)
            .expect("state read")
            .expect("state");
        assert_eq!(state.authority_fingerprint.as_deref(), Some(AUTHORITY_B));
        assert_eq!(state.last_good, None);
    }

    #[test]
    fn scoped_legacy_v2_state_migrates_to_its_authority_row() {
        let connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        let requested = distribution(11, "legacy-nonce-11");
        let persisted = PersistedStateV2 {
            schema_version: SCHEMA_VERSION,
            authority_fingerprint: Some(AUTHORITY_A.to_owned()),
            requested: Some(serde_json::to_value(&requested).expect("requested value")),
            receipt: Some(receipt(&requested, ApplyStatusV2::Ack)),
            last_good: Some(serde_json::to_value(&requested).expect("last-good value")),
        };
        connection
            .execute(
                "INSERT INTO desktop_platform_plugin_state_v2 (id, state_json) VALUES (1, ?1)",
                params![serde_json::to_string(&persisted).expect("legacy state")],
            )
            .expect("seed scoped legacy state");

        initialize_schema(&connection).expect("legacy migration");

        assert_eq!(
            read_last_good(&connection, AUTHORITY_A).expect("migrated last-good"),
            Some(requested)
        );
        let migrated_rows: u64 = connection
            .query_row(
                r#"
                SELECT COUNT(*)
                FROM desktop_platform_plugin_authority_state_v2
                WHERE authority_fingerprint = ?1
                "#,
                params![AUTHORITY_A],
                |row| row.get(0),
            )
            .expect("migrated row count");
        assert_eq!(migrated_rows, 1);
    }

    #[test]
    fn unscoped_legacy_v2_state_is_not_restored() {
        let connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        let persisted = serde_json::json!({
            "schema_version": 2,
            "requested": {"legacy": "unscoped"},
            "receipt": null,
            "last_good": {"legacy": "unscoped"},
        });
        connection
            .execute(
                "INSERT INTO desktop_platform_plugin_state_v2 (id, state_json) VALUES (1, ?1)",
                params![persisted.to_string()],
            )
            .expect("seed unscoped state");

        assert_eq!(
            read_last_good(&connection, AUTHORITY_A).expect("read last-good"),
            None
        );
    }

    #[test]
    fn explicit_null_snapshot_survives_sqlite_round_trip() {
        let mut connection = Connection::open_in_memory().expect("database");
        initialize_schema(&connection).expect("schema");
        let requested = distribution_with_explicit_null(13, "nonce-explicit-null");
        record_requested(&connection, AUTHORITY_A, &requested).expect("requested");
        record_receipt(
            &mut connection,
            AUTHORITY_A,
            "nonce-explicit-null",
            &receipt(&requested, ApplyStatusV2::Ack),
        )
        .expect("ack");

        let restored = read_last_good(&connection, AUTHORITY_A)
            .expect("read last-good")
            .expect("last-good");
        assert_eq!(restored, requested);
        let persisted: String = connection
            .query_row(
                r#"
                SELECT state_json
                FROM desktop_platform_plugin_authority_state_v2
                WHERE authority_fingerprint = ?1
                "#,
                params![AUTHORITY_A],
                |row| row.get(0),
            )
            .expect("persisted state");
        let value: Value = serde_json::from_str(&persisted).expect("state JSON");
        let artifact = value["last_good"]["snapshot"]["manifests"][0]["modules"][0]["artifact"]
            .as_object()
            .expect("artifact object");
        assert_eq!(artifact.get("signature"), Some(&Value::Null));
    }
}
