use super::*;

fn read_version(
    conn: &Connection,
    scope: &KnowledgeScope,
    object_id: &str,
    seen: bool,
) -> KnowledgeResult<Option<Value>> {
    let query = if seen {
        "SELECT version_json FROM knowledge_sync_graph_pull_events WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3 ORDER BY sequence DESC LIMIT 1"
    } else {
        "SELECT version_json FROM knowledge_sync_graph_remote_versions WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3"
    };
    let value: Option<String> = conn
        .query_row(
            query,
            params![scope.tenant_id, scope.project_id, object_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    value
        .map(|value| serde_json::from_str(&value).map_err(storage))
        .transpose()
}

fn typed(value: &Value) -> KnowledgeResult<RemoteGraphVersion> {
    serde_json::from_value(value.clone()).map_err(storage)
}

pub(super) fn apply_event(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    target: &KnowledgeSyncTarget,
    event: &Event,
    remote: &RemoteGraphVersion,
    result: &mut GraphPullReceipt,
) -> KnowledgeResult<()> {
    let seen = read_version(tx, scope, &remote.object_id, true)?;
    if let Some(seen) = &seen {
        let previous = typed(seen)?;
        if remote.revision <= previous.revision
            || remote.author_id != previous.author_id
            || remote.created_at_ms != previous.created_at_ms
        {
            return Err(KnowledgeError::InvalidInput);
        }
    }
    super::graph_push::accept_journal_receipt(
        tx,
        scope,
        target,
        &event.change_id,
        event.sequence,
        &event.version,
    )?;
    let baseline = read_version(tx, scope, &remote.object_id, false)?;
    if let Some(baseline) = &baseline {
        let previous = typed(baseline)?;
        if remote.author_id != previous.author_id || remote.created_at_ms != previous.created_at_ms
        {
            return Err(KnowledgeError::InvalidInput);
        }
        // A push receipt may be ahead of the pull cursor. Consume the older
        // journal event without overwriting either baseline or current record.
        if remote.revision <= previous.revision {
            if remote.revision == previous.revision && &event.version != baseline {
                return Err(KnowledgeError::InvalidInput);
            }
            return Ok(());
        }
    }
    let local = super::graph_sync::local_object(tx, scope, &remote.object_id)?;
    let pending_content: Option<String> = tx
        .query_row(
            "SELECT payload FROM knowledge_pending_graph_outbox
             WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3
             ORDER BY sequence DESC LIMIT 1",
            params![scope.tenant_id, scope.project_id, remote.object_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    let active_conflict: bool = tx
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM knowledge_active_graph_pull_conflicts WHERE tenant_id=?1 AND project_id=?2 AND object_id=?3)",
            params![scope.tenant_id, scope.project_id, remote.object_id],
            |row| row.get(0),
        )
        .map_err(storage)?;
    if pending_content.is_some()
        || active_conflict
        || (local.is_some() && baseline.is_none())
    {
        // A pending local extraction with no local record yet is materialized
        // first so explicit resolution always has a local version to compare.
        let local = match (local, &pending_content) {
            (None, Some(payload)) => {
                let content: RemoteGraphContent =
                    serde_json::from_str(payload).map_err(storage)?;
                let version = RemoteGraphVersion {
                    object_id: remote.object_id.clone(),
                    revision: 1,
                    deleted: false,
                    author_id: target.link.remote_actor_id.clone(),
                    created_at_ms: remote.created_at_ms,
                    content,
                };
                super::graph_sync::store_object(tx, scope, &version, 1)?;
                Some(version)
            }
            (existing, _) => existing.map(|object| object.version),
        };
        let conflict = json!({
            "sequence": event.sequence,
            "object_id": remote.object_id,
            "remote": event.version,
            "local": local.as_ref().map(|version| serde_json::to_value(version).map_err(storage)).transpose()?,
            "local_deleted": local.as_ref().is_some_and(|version| version.deleted),
            "baseline": baseline,
        });
        tx.execute(
            "INSERT INTO knowledge_sync_graph_pull_conflicts(tenant_id, project_id, sequence, object_id, conflict_json) VALUES(?1, ?2, ?3, ?4, ?5)",
            params![scope.tenant_id, scope.project_id, event.sequence, remote.object_id, serde_json::to_string(&conflict).map_err(storage)?],
        ).map_err(storage)?;
        result.conflicts += 1;
        return Ok(());
    }
    let revision = match &local {
        Some(object) => object
            .revision
            .checked_add(1)
            .ok_or(KnowledgeError::InvalidInput)?,
        None => 1,
    };
    super::graph_sync::store_object(tx, scope, remote, revision)?;
    tx.execute(
        "INSERT INTO knowledge_sync_graph_remote_versions(tenant_id, project_id, object_id, version_json)
         VALUES(?1, ?2, ?3, ?4) ON CONFLICT(tenant_id, project_id, object_id) DO UPDATE SET version_json=excluded.version_json",
        params![scope.tenant_id, scope.project_id, remote.object_id, serde_json::to_string(&event.version).map_err(storage)?],
    ).map_err(storage)?;
    result.applied += 1;
    Ok(())
}
