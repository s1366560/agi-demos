//! Versioned Artifact text-content authority shared by Postgres and dev services.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use agistack_adapters_postgres::{
    ArtifactContentSaveCommand as PgArtifactContentSaveCommand,
    ArtifactContentSaveResult as PgArtifactContentSaveResult, ArtifactRecord,
};

use super::{ArtifactApiError, ArtifactView, DevArtifactService, PgArtifactService};

const EDITABLE_ARTIFACT_MIME_TYPES: &[&str] = &[
    "application/javascript",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "text/css",
    "text/csv",
    "text/html",
    "text/javascript",
    "text/markdown",
    "text/plain",
    "text/x-c",
    "text/x-c++",
    "text/x-go",
    "text/x-java",
    "text/x-php",
    "text/x-python",
    "text/x-ruby",
    "text/x-rust",
    "text/x-shellscript",
    "text/x-typescript",
    "text/xml",
    "text/yaml",
];

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub(crate) struct ArtifactContentSaveCommandV2 {
    pub(crate) contract_version: u8,
    pub(crate) expected_revision: i64,
    pub(crate) content_hash: String,
    pub(crate) idempotency_key: String,
    pub(crate) content: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct ArtifactContentSaveReceipt {
    pub(crate) artifact_id: String,
    pub(crate) revision: i64,
    pub(crate) content_hash: String,
    pub(crate) duplicate: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct ArtifactContentContractV2 {
    pub(crate) contract_version: u8,
    pub(crate) artifact_id: String,
    pub(crate) revision: i64,
    pub(crate) content_hash: String,
    pub(crate) mime_type: String,
    pub(crate) content: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ArtifactContentBytes {
    pub(crate) bytes: Vec<u8>,
    pub(crate) mime_type: String,
}

struct ValidatedArtifactContentSave {
    expected_revision: i64,
    content_hash: String,
    idempotency_key: String,
    request_hash: String,
    bytes: Vec<u8>,
    size_bytes: i64,
}

struct DevArtifactContentReceipt {
    request_hash: String,
    revision: i64,
    content_hash: String,
}

pub(super) async fn get_pg_artifact_bytes(
    service: &PgArtifactService,
    artifact: &ArtifactView,
) -> Result<ArtifactContentBytes, ArtifactApiError> {
    let bytes = service
        .object_store
        .get(&artifact.object_key)
        .await
        .map_err(ArtifactApiError::internal)?
        .ok_or_else(|| ArtifactApiError::not_found("Artifact content not found"))?;
    Ok(ArtifactContentBytes {
        bytes,
        mime_type: artifact.mime_type.clone(),
    })
}

pub(super) async fn get_pg_artifact_content(
    service: &PgArtifactService,
    artifact: &ArtifactView,
) -> Result<ArtifactContentContractV2, ArtifactApiError> {
    ensure_editable_mime(&artifact.mime_type)?;
    let mut current = artifact.clone();
    for _ in 0..2 {
        let raw = get_pg_artifact_bytes(service, &current).await?;
        let content_hash = artifact_content_hash(&raw.bytes);
        if let Some(persisted_hash) = &current.content_hash {
            if persisted_hash != &content_hash {
                return Err(ArtifactApiError::conflict(
                    "Artifact content integrity check failed",
                    "artifact_content_integrity_mismatch",
                    current.content_revision,
                    persisted_hash,
                ));
            }
            let content = String::from_utf8(raw.bytes).map_err(|_| {
                ArtifactApiError::unsupported_media("Artifact content is not editable text")
            })?;
            return Ok(ArtifactContentContractV2 {
                contract_version: 2,
                artifact_id: current.id,
                revision: current.content_revision,
                content_hash,
                mime_type: normalize_mime_type(&raw.mime_type),
                content,
            });
        }

        let initialized = service
            .repo
            .initialize_content_hash(&current.id, current.content_revision, &content_hash)
            .await
            .map_err(ArtifactApiError::internal)?
            .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
        current = ArtifactView::from(initialized);
    }
    Err(ArtifactApiError::conflict(
        "Artifact content authority changed during read",
        "artifact_content_authority_changed",
        current.content_revision,
        current
            .content_hash
            .unwrap_or_else(|| artifact_content_hash(b"")),
    ))
}

pub(super) async fn save_pg_artifact_content(
    service: &PgArtifactService,
    artifact: &ArtifactView,
    request: ArtifactContentSaveCommandV2,
) -> Result<ArtifactContentSaveReceipt, ArtifactApiError> {
    ensure_editable_mime(&artifact.mime_type)?;
    let validated = validate_save_command(&artifact.id, request)?;
    let current = service
        .repo
        .get(&artifact.id)
        .await
        .map_err(ArtifactApiError::internal)?
        .map(ArtifactView::from)
        .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
    get_pg_artifact_content(service, &current).await?;
    let next_revision = validated
        .expected_revision
        .checked_add(1)
        .ok_or_else(|| ArtifactApiError::unprocessable("Artifact content revision is exhausted"))?;
    let object_key =
        versioned_artifact_object_key(artifact, next_revision, &validated.content_hash);
    service
        .object_store
        .put(
            &object_key,
            validated.bytes.clone(),
            Some(&artifact.mime_type),
        )
        .await
        .map_err(ArtifactApiError::internal)?;
    let result = service
        .repo
        .save_content_v2(PgArtifactContentSaveCommand {
            artifact_id: &artifact.id,
            project_id: &artifact.project_id,
            tenant_id: &artifact.tenant_id,
            expected_revision: validated.expected_revision,
            idempotency_key: &validated.idempotency_key,
            request_hash: &validated.request_hash,
            content_hash: &validated.content_hash,
            object_key: &object_key,
            size_bytes: validated.size_bytes,
        })
        .await
        .map_err(ArtifactApiError::internal)?;
    match result {
        PgArtifactContentSaveResult::Saved(receipt) => Ok(ArtifactContentSaveReceipt {
            artifact_id: receipt.artifact_id,
            revision: receipt.revision,
            content_hash: receipt.content_hash,
            duplicate: receipt.duplicate,
        }),
        PgArtifactContentSaveResult::Conflict(conflict) => Err(ArtifactApiError::conflict(
            if conflict.reason_code == "artifact_content_revision_conflict" {
                "Artifact content revision conflict"
            } else {
                "Artifact content idempotency conflict"
            },
            conflict.reason_code,
            conflict.server_revision,
            conflict.server_content_hash,
        )),
        PgArtifactContentSaveResult::NotFound => {
            Err(ArtifactApiError::not_found("Artifact not found"))
        }
        PgArtifactContentSaveResult::NotReady => Err(ArtifactApiError::bad_request(
            "Artifact cannot be updated in its current status",
        )),
    }
}

pub(super) async fn get_dev_artifact_bytes(
    service: &DevArtifactService,
    artifact: &ArtifactView,
) -> Result<ArtifactContentBytes, ArtifactApiError> {
    let bytes = service
        .object_store
        .get(&artifact.object_key)
        .await
        .map_err(ArtifactApiError::internal)?
        .ok_or_else(|| ArtifactApiError::not_found("Artifact content not found"))?;
    Ok(ArtifactContentBytes {
        bytes,
        mime_type: artifact.mime_type.clone(),
    })
}

pub(super) async fn get_dev_artifact_content(
    service: &DevArtifactService,
    artifact: &ArtifactView,
) -> Result<ArtifactContentContractV2, ArtifactApiError> {
    ensure_editable_mime(&artifact.mime_type)?;
    let raw = get_dev_artifact_bytes(service, artifact).await?;
    let content_hash = artifact_content_hash(&raw.bytes);
    let (revision, persisted_hash) = {
        let mut artifacts = service
            .artifacts
            .lock()
            .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
        let record = artifacts
            .iter_mut()
            .find(|candidate| candidate.id == artifact.id && candidate.status == "ready")
            .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
        if let Some(persisted_hash) = &record.content_hash {
            if persisted_hash != &content_hash {
                return Err(ArtifactApiError::conflict(
                    "Artifact content integrity check failed",
                    "artifact_content_integrity_mismatch",
                    record.content_revision,
                    persisted_hash,
                ));
            }
        } else {
            record.content_hash = Some(content_hash.clone());
        }
        (record.content_revision, record.content_hash.clone())
    };
    let content = String::from_utf8(raw.bytes).map_err(|_| {
        ArtifactApiError::unsupported_media("Artifact content is not editable text")
    })?;
    Ok(ArtifactContentContractV2 {
        contract_version: 2,
        artifact_id: artifact.id.clone(),
        revision,
        content_hash: persisted_hash.unwrap_or(content_hash),
        mime_type: normalize_mime_type(&raw.mime_type),
        content,
    })
}

pub(super) async fn save_dev_artifact_content(
    service: &DevArtifactService,
    artifact: &ArtifactView,
    request: ArtifactContentSaveCommandV2,
) -> Result<ArtifactContentSaveReceipt, ArtifactApiError> {
    ensure_editable_mime(&artifact.mime_type)?;
    let validated = validate_save_command(&artifact.id, request)?;
    let current = {
        let artifacts = service
            .artifacts
            .lock()
            .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
        artifacts
            .iter()
            .find(|candidate| candidate.id == artifact.id && candidate.status == "ready")
            .cloned()
            .map(ArtifactView::from)
            .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?
    };
    get_dev_artifact_content(service, &current).await?;

    let version_key = {
        let artifacts = service
            .artifacts
            .lock()
            .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
        let record = artifacts
            .iter()
            .find(|candidate| candidate.id == artifact.id && candidate.status == "ready")
            .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
        if let Some(receipt) = dev_content_receipt(record, &validated.idempotency_key)? {
            return replay_or_conflict(receipt, &validated, record);
        }
        ensure_expected_revision(record, validated.expected_revision)?;
        let next_revision = record.content_revision.checked_add(1).ok_or_else(|| {
            ArtifactApiError::unprocessable("Artifact content revision is exhausted")
        })?;
        versioned_artifact_object_key(
            &ArtifactView::from(record.clone()),
            next_revision,
            &validated.content_hash,
        )
    };

    service
        .object_store
        .put(
            &version_key,
            validated.bytes.clone(),
            Some(&artifact.mime_type),
        )
        .await
        .map_err(ArtifactApiError::internal)?;
    let mut artifacts = service
        .artifacts
        .lock()
        .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
    let record = artifacts
        .iter_mut()
        .find(|candidate| candidate.id == artifact.id && candidate.status == "ready")
        .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
    if let Some(receipt) = dev_content_receipt(record, &validated.idempotency_key)? {
        return replay_or_conflict(receipt, &validated, record);
    }
    ensure_expected_revision(record, validated.expected_revision)?;
    let next_revision = record
        .content_revision
        .checked_add(1)
        .ok_or_else(|| ArtifactApiError::unprocessable("Artifact content revision is exhausted"))?;
    record.object_key = version_key;
    record.size_bytes = validated.size_bytes;
    record.content_revision = next_revision;
    record.content_hash = Some(validated.content_hash.clone());
    record.url = None;
    record.preview_url = None;
    record.error_message = None;
    store_dev_content_receipt(
        record,
        &validated.idempotency_key,
        &validated.request_hash,
        next_revision,
        &validated.content_hash,
    )?;
    Ok(ArtifactContentSaveReceipt {
        artifact_id: record.id.clone(),
        revision: next_revision,
        content_hash: validated.content_hash,
        duplicate: false,
    })
}

pub(super) fn normalize_mime_type(value: &str) -> String {
    value
        .split_once(';')
        .map_or(value, |(mime, _)| mime)
        .trim()
        .to_ascii_lowercase()
}

fn ensure_editable_mime(value: &str) -> Result<(), ArtifactApiError> {
    let mime_type = normalize_mime_type(value);
    if EDITABLE_ARTIFACT_MIME_TYPES.contains(&mime_type.as_str()) {
        Ok(())
    } else {
        Err(ArtifactApiError::unsupported_media(
            "Artifact content is not editable text",
        ))
    }
}

fn artifact_content_hash(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

fn validate_save_command(
    artifact_id: &str,
    request: ArtifactContentSaveCommandV2,
) -> Result<ValidatedArtifactContentSave, ArtifactApiError> {
    if request.contract_version != 2 {
        return Err(ArtifactApiError::unprocessable(
            "Artifact content contract version is unsupported",
        ));
    }
    if request.expected_revision < 0 {
        return Err(ArtifactApiError::unprocessable(
            "expected_revision must be greater than or equal to 0",
        ));
    }
    if !is_content_hash(&request.content_hash) {
        return Err(ArtifactApiError::unprocessable(
            "Artifact content hash is invalid",
        ));
    }
    if !is_idempotency_key(&request.idempotency_key) {
        return Err(ArtifactApiError::unprocessable(
            "Artifact content idempotency key is invalid",
        ));
    }
    let bytes = request.content.as_bytes().to_vec();
    let computed_hash = artifact_content_hash(&bytes);
    if computed_hash != request.content_hash {
        return Err(ArtifactApiError::unprocessable(
            "Artifact content hash does not match content",
        ));
    }
    let size_bytes = i64::try_from(bytes.len())
        .map_err(|_| ArtifactApiError::bad_request("Artifact content is too large"))?;
    let request_hash = artifact_save_request_hash(artifact_id, &request);
    Ok(ValidatedArtifactContentSave {
        expected_revision: request.expected_revision,
        content_hash: request.content_hash,
        idempotency_key: request.idempotency_key,
        request_hash,
        bytes,
        size_bytes,
    })
}

fn is_content_hash(value: &str) -> bool {
    value.len() == 71
        && value.strip_prefix("sha256:").is_some_and(|digest| {
            digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        })
}

fn is_idempotency_key(value: &str) -> bool {
    (8..=128).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
}

fn artifact_save_request_hash(artifact_id: &str, request: &ArtifactContentSaveCommandV2) -> String {
    let mut digest = Sha256::new();
    for value in [
        "artifact-content-v2",
        artifact_id,
        &request.expected_revision.to_string(),
        &request.content_hash,
        &request.content,
    ] {
        digest.update(value.as_bytes());
        digest.update(b"\0");
    }
    format!("sha256:{:x}", digest.finalize())
}

fn versioned_artifact_object_key(
    artifact: &ArtifactView,
    revision: i64,
    content_hash: &str,
) -> String {
    format!(
        "artifacts/{}/{}/{}/versions/r{}-{}",
        artifact.tenant_id,
        artifact.project_id,
        artifact.id,
        revision,
        content_hash.trim_start_matches("sha256:")
    )
}

fn dev_content_receipt(
    artifact: &ArtifactRecord,
    idempotency_key: &str,
) -> Result<Option<DevArtifactContentReceipt>, ArtifactApiError> {
    let Some(receipts) = artifact
        .metadata
        .as_object()
        .and_then(|metadata| metadata.get("_artifact_content_v2_receipts"))
        .and_then(Value::as_object)
    else {
        return Ok(None);
    };
    let Some(receipt) = receipts.get(idempotency_key).and_then(Value::as_object) else {
        return Ok(None);
    };
    let request_hash = receipt
        .get("request_hash")
        .and_then(Value::as_str)
        .ok_or_else(|| ArtifactApiError::internal("Artifact content receipt is invalid"))?;
    let revision = receipt
        .get("revision")
        .and_then(Value::as_i64)
        .ok_or_else(|| ArtifactApiError::internal("Artifact content receipt is invalid"))?;
    let content_hash = receipt
        .get("content_hash")
        .and_then(Value::as_str)
        .ok_or_else(|| ArtifactApiError::internal("Artifact content receipt is invalid"))?;
    Ok(Some(DevArtifactContentReceipt {
        request_hash: request_hash.to_string(),
        revision,
        content_hash: content_hash.to_string(),
    }))
}

fn store_dev_content_receipt(
    artifact: &mut ArtifactRecord,
    idempotency_key: &str,
    request_hash: &str,
    revision: i64,
    content_hash: &str,
) -> Result<(), ArtifactApiError> {
    let metadata = artifact
        .metadata
        .as_object_mut()
        .ok_or_else(|| ArtifactApiError::internal("Artifact metadata is invalid"))?;
    let receipts = metadata
        .entry("_artifact_content_v2_receipts")
        .or_insert_with(|| json!({}))
        .as_object_mut()
        .ok_or_else(|| ArtifactApiError::internal("Artifact content receipt store is invalid"))?;
    receipts.insert(
        idempotency_key.to_string(),
        json!({
            "request_hash": request_hash,
            "revision": revision,
            "content_hash": content_hash,
        }),
    );
    Ok(())
}

fn replay_or_conflict(
    receipt: DevArtifactContentReceipt,
    command: &ValidatedArtifactContentSave,
    artifact: &ArtifactRecord,
) -> Result<ArtifactContentSaveReceipt, ArtifactApiError> {
    if receipt.request_hash == command.request_hash {
        return Ok(ArtifactContentSaveReceipt {
            artifact_id: artifact.id.clone(),
            revision: receipt.revision,
            content_hash: receipt.content_hash,
            duplicate: true,
        });
    }
    Err(ArtifactApiError::conflict(
        "Artifact content idempotency conflict",
        "artifact_content_idempotency_conflict",
        artifact.content_revision,
        artifact.content_hash.as_deref().ok_or_else(|| {
            ArtifactApiError::internal("Artifact content hash is not initialized")
        })?,
    ))
}

fn ensure_expected_revision(
    artifact: &ArtifactRecord,
    expected_revision: i64,
) -> Result<(), ArtifactApiError> {
    if artifact.content_revision == expected_revision {
        return Ok(());
    }
    Err(ArtifactApiError::conflict(
        "Artifact content revision conflict",
        "artifact_content_revision_conflict",
        artifact.content_revision,
        artifact.content_hash.as_deref().ok_or_else(|| {
            ArtifactApiError::internal("Artifact content hash is not initialized")
        })?,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn request_fingerprint_matches_python_contract() {
        let command = ArtifactContentSaveCommandV2 {
            contract_version: 2,
            expected_revision: 1,
            content_hash: "sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777"
                .to_string(),
            idempotency_key: "artifact-v2:save:0001".to_string(),
            content: "updated".to_string(),
        };

        assert_eq!(
            artifact_save_request_hash("artifact-v2", &command),
            "sha256:99009b05d03d76249c37a09ec4c3e7f9a3096173f094e0421736197525515a21"
        );
    }
}
