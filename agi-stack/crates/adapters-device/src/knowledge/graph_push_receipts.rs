use uuid::Uuid;

use super::*;

fn invalid() -> KnowledgeError {
    KnowledgeError::InvalidInput
}

fn canonical_uuid(value: &Value) -> KnowledgeResult<&str> {
    let id = value.as_str().ok_or_else(invalid)?;
    if Uuid::parse_str(id).map_err(|_| invalid())?.to_string() != id {
        return Err(invalid());
    }
    Ok(id)
}

fn version(value: &Value, object_id: &str) -> KnowledgeResult<RemoteGraphVersion> {
    let version: RemoteGraphVersion =
        serde_json::from_value(value.clone()).map_err(|_| invalid())?;
    version.validate().map_err(|_| invalid())?;
    if version.object_id != object_id {
        return Err(invalid());
    }
    Ok(version)
}

pub(super) fn accept(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    target: &KnowledgeSyncTarget,
    local_sequence: u64,
    response: Value,
    conflict: Option<Value>,
) -> KnowledgeResult<KnowledgeGraphPushReceipt> {
    let row: Option<(String, Option<String>)> = tx
        .query_row(
            "SELECT p.request_json, p.receipt_json FROM knowledge_sync_graph_pushes p
             JOIN knowledge_sync_graph_outbox o ON o.sequence=p.sequence
             WHERE o.tenant_id=?1 AND o.project_id=?2 AND p.sequence=?3",
            params![scope.tenant_id, scope.project_id, local_sequence],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()
        .map_err(storage)?;
    let (request_json, previous) = row.ok_or(KnowledgeError::NotFound)?;
    if !response["replayed"].is_boolean() {
        return Err(invalid());
    }
    let receipt = response
        .get("receipt")
        .filter(|value| value.is_object())
        .ok_or_else(invalid)?;
    let request: Value = serde_json::from_str(&request_json).map_err(storage)?;
    if canonical_uuid(&receipt["change_id"])? != request["change_id"].as_str().ok_or_else(invalid)?
    {
        return Err(invalid());
    }
    if let Some(previous) = previous {
        let previous: Value = serde_json::from_str(&previous).map_err(storage)?;
        if &previous != receipt {
            return Err(KnowledgeError::IdempotencyConflict);
        }
        return Ok(KnowledgeGraphPushReceipt {
            local_sequence,
            receipt: previous,
            replayed: true,
        });
    }
    let id = request["object_id"].as_str().ok_or_else(invalid)?;
    let conflict_json = match receipt["status"].as_str() {
        Some("applied") => {
            if conflict.is_some() {
                return Err(invalid());
            }
            receipt["sequence"]
                .as_i64()
                .filter(|value| *value > 0)
                .ok_or_else(invalid)?;
            let remote = version(&receipt["version"], id)?;
            let expected = request["expected_revision"].as_u64().ok_or_else(invalid)?;
            if expected >= u64::from(MAX_REMOTE_REVISION)
                || u64::from(remote.revision) != expected + 1
                || remote.deleted != (request["operation"] == "delete")
            {
                return Err(invalid());
            }
            let previous = baseline(tx, scope, id)?;
            let previous = previous
                .as_ref()
                .map(|value| version(value, id))
                .transpose()?;
            if u64::from(previous.as_ref().map_or(0, |version| version.revision)) != expected {
                return Err(KnowledgeError::Conflict);
            }
            if let Some(previous) = &previous {
                if remote.author_id != previous.author_id
                    || remote.created_at_ms != previous.created_at_ms
                {
                    return Err(invalid());
                }
            } else if remote.author_id != target.link.remote_actor_id {
                return Err(invalid());
            }
            if remote.deleted {
                if previous.as_ref().map(|previous| &previous.content) != Some(&remote.content) {
                    return Err(invalid());
                }
            } else {
                let sent: RemoteGraphContent =
                    serde_json::from_value(request["content"].clone()).map_err(|_| invalid())?;
                if sent != remote.content {
                    return Err(invalid());
                }
            }
            // Persist the complete server snapshot as the push baseline.
            tx.execute(
                "INSERT INTO knowledge_sync_graph_remote_versions(
                    tenant_id, project_id, object_id, version_json
                 ) VALUES(?1, ?2, ?3, ?4)
                 ON CONFLICT(tenant_id, project_id, object_id)
                 DO UPDATE SET version_json=excluded.version_json",
                params![
                    scope.tenant_id,
                    scope.project_id,
                    id,
                    serde_json::to_string(&receipt["version"]).map_err(storage)?,
                ],
            )
            .map_err(storage)?;
            None
        }
        Some("conflict") => {
            let conflict_id = canonical_uuid(&receipt["conflict_id"])?;
            let conflict = conflict.ok_or_else(invalid)?;
            if conflict["id"] != conflict_id || conflict["object_id"] != id {
                return Err(invalid());
            }
            let mut proposed = request.clone();
            proposed
                .as_object_mut()
                .ok_or_else(invalid)?
                .remove("change_id");
            if conflict["proposed"] != proposed {
                return Err(invalid());
            }
            let current = conflict.get("current").ok_or_else(invalid)?;
            if !current.is_null() {
                version(current, id)?;
            }
            let resolution = conflict.get("resolved_change_id").ok_or_else(invalid)?;
            if !resolution.is_null() {
                canonical_uuid(resolution)?;
            }
            Some(serde_json::to_string(&conflict).map_err(storage)?)
        }
        _ => return Err(invalid()),
    };
    let receipt_json = serde_json::to_string(receipt).map_err(storage)?;
    tx.execute(
        "UPDATE knowledge_sync_graph_pushes SET receipt_json=?2, conflict_json=?3
         WHERE sequence=?1 AND receipt_json IS NULL",
        params![local_sequence, receipt_json, conflict_json],
    )
    .map_err(storage)?;
    Ok(KnowledgeGraphPushReceipt {
        local_sequence,
        receipt: receipt.clone(),
        replayed: false,
    })
}
