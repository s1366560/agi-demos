use super::*;

fn selection(tx: &Transaction<'_>, scope: &KnowledgeScope) -> KnowledgeResult<CommunitySelection> {
    tx.query_row(
        "SELECT requested_build_id,active_build_id,revision FROM knowledge_community_selection
        WHERE tenant_id=?1 AND project_id=?2",
        params![scope.tenant_id, scope.project_id],
        |row| {
            Ok(CommunitySelection {
                requested_build_id: Some(row.get(0)?),
                active_build_id: row.get(1)?,
                revision: row.get(2)?,
            })
        },
    )
    .optional()
    .map_err(storage)
    .map(Option::unwrap_or_default)
}

impl SqliteKnowledgeRepository {
    /// Selects the desired generation without exposing incomplete candidate
    /// output. A later completion must present this exact selection revision.
    pub fn select_community_build_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        expected_revision: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<CommunitySelection> {
        validate(scope, build_id)?;
        transact(self, clock, |tx, _| {
            let build = read_build(tx, scope, build_id)?.ok_or(KnowledgeError::Conflict)?;
            if !current_graph(tx, scope, &build)? {
                return Err(KnowledgeError::Conflict);
            }
            let mut current = selection(tx, scope)?;
            if current.revision != expected_revision {
                return Err(KnowledgeError::Conflict);
            }
            let revision = i64::try_from(current.revision)
                .ok()
                .and_then(|rev| rev.checked_add(1))
                .ok_or(KnowledgeError::Conflict)?;
            tx.execute("INSERT INTO knowledge_community_selection(tenant_id,project_id,requested_build_id,active_build_id,revision)
                VALUES(?1,?2,?3,NULL,?4) ON CONFLICT(tenant_id,project_id) DO UPDATE SET requested_build_id=excluded.requested_build_id,revision=excluded.revision",
                params![scope.tenant_id,scope.project_id,build_id,revision]).map_err(storage)?;
            current.requested_build_id = Some(build_id.into());
            current.revision = revision as u64;
            Ok((current, None))
        })
    }

    /// Activates only the selected, wholly completed, current graph. Returning
    /// false means unfinished work; a stale graph/selection returns Conflict.
    pub fn activate_community_build_durable(
        &self,
        scope: &KnowledgeScope,
        build_id: &str,
        expected_revision: u64,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<bool> {
        validate(scope, build_id)?;
        transact(self, clock, |tx, _| {
            let selected = selection(tx, scope)?;
            if selected.revision != expected_revision
                || selected.requested_build_id.as_deref() != Some(build_id)
            {
                return Err(KnowledgeError::Conflict);
            }
            let build = read_build(tx, scope, build_id)?.ok_or(KnowledgeError::Conflict)?;
            if !current_graph(tx, scope, &build)? {
                return Err(KnowledgeError::Conflict);
            }
            let results = read::results(tx, scope, &build)?;
            let status = read::status(tx, scope, &build, &results)?;
            if !matches!(
                status.state,
                CommunityProgressState::Completed | CommunityProgressState::CompletedEmpty
            ) {
                return Ok((false, None));
            }
            tx.execute("UPDATE knowledge_community_selection SET active_build_id=?3 WHERE tenant_id=?1 AND project_id=?2",
                params![scope.tenant_id,scope.project_id,build_id]).map_err(storage)?;
            Ok((true, None))
        })
    }

    pub fn active_community_build_durable(
        &self,
        scope: &KnowledgeScope,
    ) -> KnowledgeResult<CommunityActiveView> {
        validate(scope, "community_selection")?;
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        let selection = selection(&tx, scope)?;
        let mut current = None;
        let mut stale_build_id = None;
        if let Some(build_id) = &selection.active_build_id {
            let build = read_build(&tx, scope, build_id)?.ok_or(KnowledgeError::Conflict)?;
            let results = read::results(&tx, scope, &build)?;
            let status = read::status(&tx, scope, &build, &results)?;
            if !matches!(
                status.state,
                CommunityProgressState::Completed | CommunityProgressState::CompletedEmpty
            ) {
                return Err(KnowledgeError::Conflict);
            }
            if current_graph(&tx, scope, &build)? {
                current = Some(CommunityPublishedBuild {
                    status,
                    candidates: build.candidates,
                    results,
                });
            } else {
                stale_build_id = Some(build_id.clone());
            }
        }
        tx.commit().map_err(storage)?;
        Ok(CommunityActiveView {
            selection,
            current,
            stale_build_id,
        })
    }
}
