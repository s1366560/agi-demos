//! Read-only current-source projection queries. No independently mutable graph
//! or project-only vector store participates in this authority.

use super::*;
use agistack_core::knowledge::{
    processing::{audit::*, worker::*, ProcessingProjection, ProcessingSource},
    retrieval::*,
};
use async_trait::async_trait;
use rusqlite::{params, Transaction};

mod query;

struct CurrentProjection {
    source: ProcessingSource,
    attempt: u32,
    memory: Memory,
    projection: ProcessingProjection,
}

impl SqliteKnowledgeRepository {
    pub fn entities_durable(
        &self,
        scope: &KnowledgeScope,
        request: &RetrievalRequest,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<RetrievalPage<RetrievedEntity>> {
        self.retrieve(
            scope,
            request,
            RetrievalKind::Entities,
            None,
            clock,
            |current| {
                current
                    .projection
                    .entities
                    .iter()
                    .enumerate()
                    .map(|(index, entity)| {
                        let index =
                            u32::try_from(index).map_err(|_| KnowledgeError::InvalidInput)?;
                        Ok((
                            index,
                            RetrievedEntity {
                                reference: EntityReference {
                                    source: current.source.clone(),
                                    entity_index: index,
                                },
                                audit_attempt: current.attempt,
                                entity: entity.clone(),
                            },
                        ))
                    })
                    .collect()
            },
        )
    }
    pub fn relationships_durable(
        &self,
        scope: &KnowledgeScope,
        request: &RetrievalRequest,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<RetrievalPage<RetrievedRelationship>> {
        self.retrieve(
            scope,
            request,
            RetrievalKind::Relationships,
            None,
            clock,
            |current| {
                current
                    .projection
                    .relationships
                    .iter()
                    .enumerate()
                    .map(|(index, relationship)| {
                        let index =
                            u32::try_from(index).map_err(|_| KnowledgeError::InvalidInput)?;
                        Ok((
                            index,
                            RetrievedRelationship {
                                source: current.source.clone(),
                                relationship_index: index,
                                audit_attempt: current.attempt,
                                source_entity: EntityReference {
                                    source: current.source.clone(),
                                    entity_index: relationship.source_index,
                                },
                                target_entity: EntityReference {
                                    source: current.source.clone(),
                                    entity_index: relationship.target_index,
                                },
                                relationship: relationship.clone(),
                            },
                        ))
                    })
                    .collect()
            },
        )
    }
    pub fn search_text_durable(
        &self,
        scope: &KnowledgeScope,
        literal: &str,
        request: &RetrievalRequest,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<RetrievalPage<LiteralTextHit>> {
        self.retrieve(
            scope,
            request,
            RetrievalKind::Text,
            Some(literal),
            clock,
            |current| {
                Ok(vec![(
                    0,
                    LiteralTextHit {
                        source: current.source.clone(),
                        audit_attempt: current.attempt,
                        title: current.memory.title.clone(),
                        content: current.memory.content.clone(),
                    },
                )])
            },
        )
    }
    fn retrieve<T>(
        &self,
        scope: &KnowledgeScope,
        request: &RetrievalRequest,
        kind: RetrievalKind,
        literal: Option<&str>,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
        project: impl Fn(&CurrentProjection) -> KnowledgeResult<Vec<(u32, T)>>,
    ) -> KnowledgeResult<RetrievalPage<T>> {
        query::validate_request(scope, request, kind, literal)?;
        let mut connection = self.conn.lock().map_err(storage)?;
        let tx = connection.transaction().map_err(storage)?;
        let started = clock()?;
        let page = read_page(&tx, scope, request, kind, literal, project)?;
        if clock()? < started {
            return Err(KnowledgeError::Conflict);
        }
        tx.commit().map_err(storage)?;
        Ok(page)
    }
}

fn read_page<T>(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
    request: &RetrievalRequest,
    kind: RetrievalKind,
    literal: Option<&str>,
    project: impl Fn(&CurrentProjection) -> KnowledgeResult<Vec<(u32, T)>>,
) -> KnowledgeResult<RetrievalPage<T>> {
    let upper = match &request.cursor {
        Some(cursor) => cursor.upper_change_sequence,
        None => tx
            .query_row(
                "SELECT COALESCE(MAX(sequence),0) FROM knowledge_processing_changes
                 WHERE tenant_id=?1 AND project_id=?2",
                params![scope.tenant_id, scope.project_id],
                |row| row.get::<_, u64>(0),
            )
            .map_err(storage)?,
    };
    let mut stmt = tx.prepare(query::CURRENT_PROJECTIONS).map_err(storage)?;
    let mut rows = stmt
        .query(params![
            scope.tenant_id,
            scope.project_id,
            request.source.as_ref().map(|s| s.memory_id.as_str()),
            request.source.as_ref().map(|s| s.revision),
            request.source.as_ref().map(|s| s.change_sequence),
            upper,
            request
                .cursor
                .as_ref()
                .map_or(0, |c| c.after.change_sequence),
            literal
        ])
        .map_err(storage)?;
    let mut items = Vec::new();
    let mut last = None;
    let mut more = false;
    'sources: while let Some(row) = rows.next().map_err(storage)? {
        let current = query::decode(row, scope)?;
        for (index, item) in project(&current)? {
            if request.cursor.as_ref().is_some_and(|cursor| {
                current.source.change_sequence == cursor.after.change_sequence
                    && index <= cursor.after.item_index
            }) {
                continue;
            }
            if items.len() == request.limit {
                more = true;
                break 'sources;
            }
            last = Some(RetrievalPosition {
                change_sequence: current.source.change_sequence,
                item_index: index,
            });
            items.push(item);
        }
    }
    let next_cursor = if more {
        Some(RetrievalCursor {
            tenant_id: scope.tenant_id.clone(),
            project_id: scope.project_id.clone(),
            kind,
            source: request.source.clone(),
            literal: literal.map(str::to_owned),
            upper_change_sequence: upper,
            after: last.ok_or(KnowledgeError::InvalidInput)?,
        })
    } else {
        None
    };
    Ok(RetrievalPage { items, next_cursor })
}

#[async_trait]
impl KnowledgeRetrievalRepository for SqliteKnowledgeRepository {
    async fn entities(
        &self,
        scope: &KnowledgeScope,
        request: &RetrievalRequest,
    ) -> KnowledgeResult<RetrievalPage<RetrievedEntity>> {
        self.entities_durable(scope, request, &|| Ok(0))
    }
    async fn relationships(
        &self,
        scope: &KnowledgeScope,
        request: &RetrievalRequest,
    ) -> KnowledgeResult<RetrievalPage<RetrievedRelationship>> {
        self.relationships_durable(scope, request, &|| Ok(0))
    }
    async fn search_text(
        &self,
        scope: &KnowledgeScope,
        literal: &str,
        request: &RetrievalRequest,
    ) -> KnowledgeResult<RetrievalPage<LiteralTextHit>> {
        self.search_text_durable(scope, literal, request, &|| Ok(0))
    }
}

/// Shared audited-source reader for derived index reconciliation. Keep the same
/// integrity checks as graph/text reads; callers own the transaction snapshot.
pub(super) fn audited_sources(
    tx: &Transaction<'_>,
    scope: &KnowledgeScope,
) -> KnowledgeResult<Vec<(ProcessingSource, u32, Memory)>> {
    let mut statement = tx.prepare(query::CURRENT_PROJECTIONS).map_err(storage)?;
    let mut rows = statement
        .query(params![
            scope.tenant_id,
            scope.project_id,
            Option::<String>::None,
            Option::<u32>::None,
            Option::<u64>::None,
            i64::MAX,
            0,
            Option::<String>::None
        ])
        .map_err(storage)?;
    let mut current = Vec::new();
    while let Some(row) = rows.next().map_err(storage)? {
        let value = query::decode(row, scope)?;
        current.push((value.source, value.attempt, value.memory));
    }
    Ok(current)
}
