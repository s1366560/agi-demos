//! Durable desired selection, deliberately independent of the active pointer.
use super::*;

pub(in super::super) fn migrate(tx: &Transaction<'_>, previous: i64) -> KnowledgeResult<()> {
    let columns: i64 = tx.query_row(
        "SELECT count(*) FROM pragma_table_info('knowledge_index_jobs') WHERE name='config_revision'",
        [], |row| row.get(0),
    ).map_err(storage)?;
    let tables: i64 = tx.query_row(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='knowledge_index_configuration'",
        [], |row| row.get(0),
    ).map_err(storage)?;
    if previous >= 11 {
        return if columns == 1 && tables == 1 {
            Ok(())
        } else {
            Err(KnowledgeError::Storage(
                "knowledge index configuration schema is missing".into(),
            ))
        };
    }
    // Existing leases retain NULL and cannot be completed after migration.
    // Selection must be explicit; no active pointer is treated as user intent.
    if columns == 0 {
        tx.execute_batch("ALTER TABLE knowledge_index_jobs ADD COLUMN config_revision INTEGER CHECK(config_revision>0);")
            .map_err(storage)?;
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS knowledge_index_configuration (
        tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision>0), build_id TEXT NOT NULL,
        PRIMARY KEY(tenant_id,project_id)
    );",
    )
    .map_err(storage)
}

pub(super) fn ensure_config(
    tx: &Transaction<'_>,
    config: &DesiredEmbeddingConfig,
) -> KnowledgeResult<()> {
    ensure_build(tx, &config.build)?;
    let current = read(tx, &config.build.scope)?.ok_or(KnowledgeError::Conflict)?;
    if current != *config {
        return Err(KnowledgeError::Conflict);
    }
    Ok(())
}

fn read(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
) -> KnowledgeResult<Option<DesiredEmbeddingConfig>> {
    let row: Option<(u64, String, Option<String>)> = tx.query_row(
        "SELECT c.revision,c.build_id,b.profile_json FROM knowledge_index_configuration c
         LEFT JOIN knowledge_index_builds b ON b.tenant_id=c.tenant_id AND b.project_id=c.project_id AND b.build_id=c.build_id
         WHERE c.tenant_id=?1 AND c.project_id=?2",
        params![scope.tenant_id,scope.project_id], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?)),
    ).optional().map_err(storage)?;
    row.map(|(revision, build_id, profile)| {
        if revision == 0 {
            return Err(KnowledgeError::Conflict);
        }
        let build = IndexBuild {
            scope: scope.clone(),
            build_id,
            profile: serde_json::from_str(&profile.ok_or(KnowledgeError::Conflict)?)
                .map_err(storage)?,
        };
        validate_build(&build)?;
        Ok(DesiredEmbeddingConfig { revision, build })
    })
    .transpose()
}

impl SqliteKnowledgeRepository {
    /// None creates the first selection. Every subsequent selection requires
    /// the exact current version, even when selecting the same immutable build.
    pub fn select_index_config_durable(
        &self,
        build: &IndexBuild,
        expected_revision: Option<u64>,
        clock: Clock<'_>,
    ) -> KnowledgeResult<DesiredEmbeddingConfig> {
        timed(self, clock, |tx, _| {
            ensure_build(tx, build)?;
            let current = read(tx, &build.scope)?;
            if current.as_ref().map(|config| config.revision) != expected_revision {
                return Err(KnowledgeError::Conflict);
            }
            let revision = expected_revision
                .unwrap_or(0)
                .checked_add(1)
                .filter(|value| *value <= i64::MAX as u64)
                .ok_or(KnowledgeError::Conflict)?;
            tx.execute("INSERT INTO knowledge_index_configuration(tenant_id,project_id,revision,build_id) VALUES(?1,?2,?3,?4)
                ON CONFLICT(tenant_id,project_id) DO UPDATE SET revision=excluded.revision,build_id=excluded.build_id",
                params![build.scope.tenant_id,build.scope.project_id,revision,build.build_id]).map_err(storage)?;
            Ok((
                DesiredEmbeddingConfig {
                    revision,
                    build: build.clone(),
                },
                None,
            ))
        })
    }

    pub fn desired_index_config_durable(
        &self,
        scope: &KnowledgeScope,
        clock: Clock<'_>,
    ) -> KnowledgeResult<Option<DesiredEmbeddingConfig>> {
        validate(scope, "index-configuration")?;
        timed(self, clock, |tx, _| Ok((read(tx, scope)?, None)))
    }
}
