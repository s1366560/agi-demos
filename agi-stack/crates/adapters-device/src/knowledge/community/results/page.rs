//! Bounded presentation reads from one SQLite snapshot.
use super::*;

impl SqliteKnowledgeRepository {
    pub fn community_build_page_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        offset: u32,
        limit: u32,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<Option<CommunityBuildPage>> {
        validate(scope, build_id)?;
        if limit == 0 || limit > 100 {
            return Err(KnowledgeError::InvalidInput);
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        clock()?;
        let output = if let Some(build) = read_build(&tx, scope, build_id)? {
            let results = read::results(&tx, scope, &build)?;
            let status = read::status(&tx, scope, &build, &results)?;
            let items = build
                .candidates
                .iter()
                .skip(offset as usize)
                .take(limit as usize)
                .map(|candidate| {
                    let candidate_id = &candidate.membership_digest;
                    let (state, attempt, failure): (String, u32, Option<String>) = tx
                        .query_row(
                            "SELECT state,attempt,failure_json FROM knowledge_community_jobs
                         WHERE tenant_id=?1 AND project_id=?2 AND build_id=?3 AND candidate_id=?4",
                            params![scope.tenant_id, scope.project_id, build_id, candidate_id],
                            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                        )
                        .map_err(storage)?;
                    let state: CommunityJobState =
                        serde_json::from_value(serde_json::Value::String(state))
                            .map_err(storage)?;
                    let failure = failure.as_deref().map(decode_json).transpose()?;
                    let audit = if attempt == 0 {
                        None
                    } else {
                        read::audit_record(&tx, scope, build_id, candidate_id, attempt)?
                            .map(|(record, _, _, _)| record.summary())
                    };
                    Ok(CommunityCandidateProgress {
                        candidate_id: candidate_id.clone(),
                        member_count: u32::try_from(candidate.members.len()).map_err(storage)?,
                        job: CommunityJobStatus {
                            build_id: build_id.into(),
                            candidate_id: candidate_id.clone(),
                            state,
                            attempt,
                            failure,
                        },
                        result: results
                            .iter()
                            .find(|r| r.candidate_id == *candidate_id)
                            .cloned(),
                        audit,
                    })
                })
                .collect::<KnowledgeResult<Vec<_>>>()?;
            Some(CommunityBuildPage {
                current_graph: current_graph(&tx, scope, &build)?,
                total: build.receipt.candidate_count,
                build: build.receipt,
                status,
                items,
                offset,
                limit,
            })
        } else {
            None
        };
        clock()?;
        tx.commit().map_err(storage)?;
        Ok(output)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_rejects_invalid_limits_and_preserves_absent_build() {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let scope = KnowledgeScope {
            tenant_id: "t".into(),
            project_id: "p".into(),
        };
        for limit in [0, 101] {
            assert!(matches!(
                repo.community_build_page_durable(&scope, "missing", 0, limit, &|| Ok(1)),
                Err(KnowledgeError::InvalidInput)
            ));
        }
        assert!(repo
            .community_build_page_durable(&scope, "missing", 0, 20, &|| Ok(1))
            .unwrap()
            .is_none());
        assert!(repo
            .community_build_page_durable(&scope, "missing", 0, 20, &|| Err(
                KnowledgeError::Conflict
            ))
            .is_err());
    }
}
