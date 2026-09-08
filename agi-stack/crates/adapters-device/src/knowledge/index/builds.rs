use super::*;

impl SqliteKnowledgeRepository {
    /// Build IDs are immutable. Reopening the same profile is idempotent; a
    /// changed model, credential binding or dimension requires a new build ID.
    pub fn begin_index_build_durable(
        &self,
        build: &IndexBuild,
        clock: Clock<'_>,
    ) -> KnowledgeResult<()> {
        validate_build(build)?;
        timed(self, clock, |tx, now| {
            tx.execute("INSERT INTO knowledge_index_builds(tenant_id,project_id,build_id,profile_json,created_at_ms)
                VALUES(?1,?2,?3,?4,?5) ON CONFLICT DO NOTHING",
                params![build.scope.tenant_id,build.scope.project_id,build.build_id,serde_json::to_string(&build.profile).map_err(storage)?,now]).map_err(storage)?;
            ensure_build(tx, build)?;
            reconcile(tx, build)?;
            Ok(((), None))
        })
    }

    /// Applied audits can complete out of sequence, including after promotion.
    /// Every worker pass reconciles the whole current set instead of a watermark.
    pub fn reconcile_index_durable(
        &self,
        config: &DesiredEmbeddingConfig,
        clock: Clock<'_>,
    ) -> KnowledgeResult<IndexCoverage> {
        let build = &config.build;
        timed(self, clock, |tx, _| {
            ensure_config(tx, config)?;
            let current = reconcile(tx, build)?;
            let (coverage, _) = vectors(tx, build, &current)?;
            Ok((coverage, None))
        })
    }

    pub fn active_index_build_durable(
        &self,
        scope: &KnowledgeScope,
        clock: Clock<'_>,
    ) -> KnowledgeResult<Option<IndexBuild>> {
        validate(scope, "active-index")?;
        timed(self, clock, |tx, _| {
            let row:Option<(String,String)> = tx.query_row("SELECT b.build_id,b.profile_json FROM knowledge_index_active a
                JOIN knowledge_index_builds b ON b.tenant_id=a.tenant_id AND b.project_id=a.project_id AND b.build_id=a.build_id
                WHERE a.tenant_id=?1 AND a.project_id=?2",params![scope.tenant_id,scope.project_id],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(storage)?;
            let build = row
                .map(|(build_id, profile)| {
                    Ok(IndexBuild {
                        scope: scope.clone(),
                        build_id,
                        profile: serde_json::from_str(&profile).map_err(storage)?,
                    })
                })
                .transpose()?;
            Ok((build, None))
        })
    }

    /// Compare-and-swap publication includes current audit/input coverage in the
    /// same write transaction. Historical builds remain available for rollback.
    pub fn promote_index_build_durable(
        &self,
        config: &DesiredEmbeddingConfig,
        expected_active: Option<&str>,
        clock: Clock<'_>,
    ) -> KnowledgeResult<()> {
        let build = &config.build;
        timed(self, clock, |tx, _| {
            ensure_config(tx, config)?;
            let active:Option<String> = tx.query_row("SELECT build_id FROM knowledge_index_active WHERE tenant_id=?1 AND project_id=?2",
                params![build.scope.tenant_id,build.scope.project_id],|r|r.get(0)).optional().map_err(storage)?;
            if active.as_deref() != expected_active {
                return Err(KnowledgeError::Conflict);
            }
            let current = reconcile(tx, build)?;
            let (coverage, _) = vectors(tx, build, &current)?;
            if !coverage.complete() {
                return Err(KnowledgeError::Conflict);
            }
            tx.execute(
                "INSERT INTO knowledge_index_active(tenant_id,project_id,build_id) VALUES(?1,?2,?3)
                ON CONFLICT(tenant_id,project_id) DO UPDATE SET build_id=excluded.build_id",
                params![
                    build.scope.tenant_id,
                    build.scope.project_id,
                    build.build_id
                ],
            )
            .map_err(storage)?;
            Ok(((), None))
        })
    }

    /// Requires the exact declared active profile. The caller additionally
    /// validates its live Provider/vault binding before and after embedding.
    pub fn read_active_index_durable(
        &self,
        config: &DesiredEmbeddingConfig,
        clock: Clock<'_>,
    ) -> KnowledgeResult<IndexRead> {
        let build = &config.build;
        timed(self, clock, |tx, _| {
            ensure_config(tx, config)?;
            let active:Option<String> = tx.query_row("SELECT build_id FROM knowledge_index_active WHERE tenant_id=?1 AND project_id=?2",
                params![build.scope.tenant_id,build.scope.project_id],|r|r.get(0)).optional().map_err(storage)?;
            if active.as_deref() != Some(build.build_id.as_str()) {
                return Err(KnowledgeError::Conflict);
            }
            let current = current_inputs(tx, build)?;
            let (coverage, vectors) = vectors(tx, build, &current)?;
            let processing = processing_coverage(tx, &build.scope, current.len())?;
            Ok((
                IndexRead {
                    config_revision: config.revision,
                    build: build.clone(),
                    coverage,
                    processing,
                    vectors,
                },
                None,
            ))
        })
    }

    pub fn index_job_status_durable(
        &self,
        config: &DesiredEmbeddingConfig,
        input: &IndexSource,
        clock: Clock<'_>,
    ) -> KnowledgeResult<Option<IndexJobStatus>> {
        let build = &config.build;
        timed(self, clock, |tx, _| {
            ensure_config(tx, config)?;
            current_input(tx, build, input)?;
            Ok((job(tx, build, input)?, None))
        })
    }
}
