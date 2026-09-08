//! Durable build discovery does not require remembering a delivered receipt.
use super::*;

impl SqliteKnowledgeRepository {
    pub fn community_builds_durable(
        &self,
        scope: &KnowledgeScope,
        offset: u32,
        limit: u32,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<CommunityBuildHistoryPage> {
        validate(scope, "history")?;
        if limit == 0 || limit > 100 {
            return Err(KnowledgeError::InvalidInput);
        }
        let mut conn = self.conn.lock().map_err(storage)?;
        let tx = conn.transaction().map_err(storage)?;
        clock()?;
        let total: u32 = tx.query_row(
            "SELECT count(*) FROM knowledge_community_builds WHERE tenant_id=?1 AND project_id=?2",
            params![scope.tenant_id, scope.project_id],
            |row| row.get(0),
        ).map_err(storage)?;
        let items = {
            let mut statement = tx
                .prepare(
                    "SELECT build_id,receipt_json FROM knowledge_community_builds
                 WHERE tenant_id=?1 AND project_id=?2
                 ORDER BY json_extract(receipt_json,'$.created_at_ms') DESC,build_id ASC
                 LIMIT ?3 OFFSET ?4",
                )
                .map_err(storage)?;
            let rows = statement
                .query_map(
                    params![scope.tenant_id, scope.project_id, limit, offset],
                    |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
                )
                .map_err(storage)?;
            rows.map(|row| {
                let (id, json) = row.map_err(storage)?;
                let receipt: CommunityBuildReceipt = decode_json(&json)?;
                if receipt.tenant_id != scope.tenant_id
                    || receipt.project_id != scope.project_id
                    || receipt.build_id != id
                {
                    return Err(KnowledgeError::Conflict);
                }
                Ok(receipt)
            })
            .collect::<KnowledgeResult<Vec<_>>>()?
        };
        clock()?;
        tx.commit().map_err(storage)?;
        Ok(CommunityBuildHistoryPage {
            items,
            total,
            offset,
            limit,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unselected_builds_survive_reopen_and_history_is_scoped_and_paginated() {
        let path =
            std::env::temp_dir().join(format!("community-history-{}.db", uuid::Uuid::new_v4()));
        let scope = KnowledgeScope {
            tenant_id: "t".into(),
            project_id: "p".into(),
        };
        let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        let mut expected = Vec::new();
        for (key, now) in [("first", 1), ("second", 2), ("third", 2)] {
            expected.push(
                repo.create_community_build_durable(
                    &scope,
                    &CommunityBuildRequest {
                        actor_id: "actor".into(),
                        idempotency_key: key.into(),
                        min_community_size: 2,
                    },
                    &|| Ok(now),
                )
                .unwrap(),
            );
        }
        assert_eq!(
            repo.active_community_build_durable(&scope)
                .unwrap()
                .selection
                .revision,
            0
        );
        drop(repo);
        let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        expected.sort_by(|a, b| {
            b.created_at_ms
                .cmp(&a.created_at_ms)
                .then(a.build_id.cmp(&b.build_id))
        });
        let first = repo
            .community_builds_durable(&scope, 0, 2, &|| Ok(3))
            .unwrap();
        assert_eq!(first.total, 3);
        assert_eq!(first.items, expected[..2]);
        let second = repo
            .community_builds_durable(&scope, 2, 2, &|| Ok(3))
            .unwrap();
        assert_eq!(second.items, expected[2..]);
        assert!(repo
            .community_builds_durable(&scope, 10, 2, &|| Ok(3))
            .unwrap()
            .items
            .is_empty());
        for foreign in [
            KnowledgeScope {
                tenant_id: "other".into(),
                ..scope.clone()
            },
            KnowledgeScope {
                project_id: "other".into(),
                ..scope.clone()
            },
        ] {
            let page = repo
                .community_builds_durable(&foreign, 0, 2, &|| Ok(3))
                .unwrap();
            assert_eq!(page.total, 0);
            assert!(page.items.is_empty());
        }
        for limit in [0, 101] {
            assert!(matches!(
                repo.community_builds_durable(&scope, 0, limit, &|| Ok(3)),
                Err(KnowledgeError::InvalidInput)
            ));
        }
        assert!(repo
            .community_builds_durable(&scope, 0, 2, &|| Err(KnowledgeError::Conflict))
            .is_err());
        drop(repo);
        std::fs::remove_file(path).unwrap();
    }
}
