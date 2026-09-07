use super::*;

impl SqliteKnowledgeRepository {
    /// Read-only discovery of both prepared decisions and cloud successes that
    /// still require explicit local reconciliation. Settled/stale rows are kept
    /// as cursor anchors, so concurrent settlement cannot shift later pages.
    pub fn pending_cloud_resolutions_durable(
        &self,
        scope: &KnowledgeScope,
        target: &KnowledgeSyncTarget,
        actor: &str,
        before_resolution_id: Option<&str>,
        limit: usize,
    ) -> KnowledgeResult<KnowledgeCloudResolutionPage> {
        valid_identifier(actor)?;
        if !(1..=200).contains(&limit) {
            return Err(KnowledgeError::InvalidInput);
        }
        if let Some(id) = before_resolution_id {
            valid_uuid(id)?;
        }
        self.cloud_transaction(scope, target, |tx| {
            let before: Option<i64> = before_resolution_id
                .map(|id| {
                    tx.query_row(
                        "SELECT rowid FROM knowledge_cloud_resolutions
                         WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3
                           AND resolution_id=?4",
                        params![scope.tenant_id, scope.project_id, actor, id],
                        |row| row.get(0),
                    )
                    .optional()
                    .map_err(storage)?
                    .ok_or(KnowledgeError::NotFound)
                })
                .transpose()?;
            let mut stmt = tx
                .prepare(
                    "SELECT resolution_id FROM knowledge_cloud_resolutions
                     WHERE tenant_id=?1 AND project_id=?2 AND actor_id=?3
                       AND rejection_json IS NULL AND reconciliation_json IS NULL
                       AND (?4 IS NULL OR rowid < ?4)
                     ORDER BY rowid DESC LIMIT ?5",
                )
                .map_err(storage)?;
            let mut ids = stmt
                .query_map(
                    params![
                        scope.tenant_id,
                        scope.project_id,
                        actor,
                        before,
                        (limit + 1) as i64
                    ],
                    |row| row.get::<_, String>(0),
                )
                .map_err(storage)?
                .collect::<Result<Vec<_>, _>>()
                .map_err(storage)?;
            let more = ids.len() > limit;
            ids.truncate(limit);
            let next_before_resolution_id = more.then(|| ids[limit - 1].clone());
            let items = ids
                .iter()
                .map(|id| load(tx, scope, actor, id))
                .collect::<KnowledgeResult<_>>()?;
            Ok(KnowledgeCloudResolutionPage {
                items,
                next_before_resolution_id,
            })
        })
    }
}
