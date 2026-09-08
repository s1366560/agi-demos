use agistack_core::knowledge::retrieval::EntityReference;

use super::*;

pub(in super::super) fn read_build(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    build_id: &str,
) -> KnowledgeResult<Option<CommunityBuildInput>> {
    let row: Option<(String, String, String)> = tx
        .query_row(
            "SELECT snapshot_json,receipt_json,graph_digest FROM knowledge_community_builds
         WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3",
            params![scope.tenant_id, scope.project_id, build_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()
        .map_err(storage)?;
    let Some((snapshot, receipt, graph_digest)) = row else {
        return Ok(None);
    };
    let snapshot: CommunitySnapshot = serde_json::from_str(&snapshot).map_err(storage)?;
    let receipt: CommunityBuildReceipt = serde_json::from_str(&receipt).map_err(storage)?;
    if snapshot.tenant_id != scope.tenant_id
        || snapshot.project_id != scope.project_id
        || receipt.tenant_id != scope.tenant_id
        || receipt.project_id != scope.project_id
        || receipt.build_id != build_id
        || receipt.graph_digest != graph_digest
        || snapshot.graph_digest != graph_digest
        || fingerprint(&snapshot)? != graph_digest
    {
        return Err(KnowledgeError::Conflict);
    }
    let mut statement = tx
        .prepare(
            "SELECT candidate_id,position,member_count FROM knowledge_community_candidates
         WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 ORDER BY position",
        )
        .map_err(storage)?;
    let mut rows = statement
        .query(params![scope.tenant_id, scope.project_id, build_id])
        .map_err(storage)?;
    let mut candidates = Vec::new();
    while let Some(row) = rows.next().map_err(storage)? {
        let id: String = row.get(0).map_err(storage)?;
        let position: usize = row.get(1).map_err(storage)?;
        let count: usize = row.get(2).map_err(storage)?;
        let members = read_members(tx, scope, build_id, &id)?;
        if position != candidates.len()
            || count != members.len()
            || count < snapshot.min_community_size
            || digest("knowledge-community-membership-v1", &members)? != id
        {
            return Err(KnowledgeError::Conflict);
        }
        for member in &members {
            let source = snapshot.sources.iter().find(|s| s.source == member.source);
            let projection = source.and_then(|s| s.audited_projection.as_ref());
            if projection
                .is_none_or(|p| (member.entity_index as usize) >= p.projection.entities.len())
            {
                return Err(KnowledgeError::Conflict);
            }
        }
        candidates.push(CommunityCandidate {
            membership_digest: id,
            members,
        });
    }
    if receipt.candidate_count as usize != candidates.len()
        || (receipt.state == CommunityBuildState::CompletedEmpty) != candidates.is_empty()
    {
        return Err(KnowledgeError::Conflict);
    }
    Ok(Some(CommunityBuildInput {
        receipt,
        snapshot,
        candidates,
    }))
}

fn read_members(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    build_id: &str,
    candidate_id: &str,
) -> KnowledgeResult<Vec<EntityReference>> {
    let mut statement = tx.prepare(
        "SELECT position,reference_json FROM knowledge_community_members
         WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4 ORDER BY position",
    ).map_err(storage)?;
    let mut rows = statement
        .query(params![
            scope.tenant_id,
            scope.project_id,
            build_id,
            candidate_id
        ])
        .map_err(storage)?;
    let mut members = Vec::new();
    while let Some(row) = rows.next().map_err(storage)? {
        if row.get::<_, usize>(0).map_err(storage)? != members.len() {
            return Err(KnowledgeError::Conflict);
        }
        let member: EntityReference =
            serde_json::from_str(&row.get::<_, String>(1).map_err(storage)?).map_err(storage)?;
        if member.source.tenant_id != scope.tenant_id
            || member.source.project_id != scope.project_id
        {
            return Err(KnowledgeError::Conflict);
        }
        members.push(member);
    }
    Ok(members)
}
