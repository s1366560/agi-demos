use super::*;

impl SqliteKnowledgeRepository {
    /// Returns the whole projection of one current, successful audit in one
    /// transaction. Missing, superseded and unaudited sources are conflicts,
    /// while a successful empty projection is a valid graph.
    pub fn graph_source_durable(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
        expected_audit_attempt: u32,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<RetrievedSourceGraph> {
        if expected_audit_attempt == 0 {
            return Err(KnowledgeError::InvalidInput);
        }
        let request = RetrievalRequest {
            source: Some(source.clone()),
            cursor: None,
            limit: 1,
        };
        self.retrieve(
            scope,
            &request,
            RetrievalKind::Text,
            None,
            clock,
            |current| {
                if current.attempt != expected_audit_attempt {
                    return Err(KnowledgeError::Conflict);
                }
                Ok(vec![(
                    0,
                    RetrievedSourceGraph {
                        source: current.source.clone(),
                        audit_attempt: current.attempt,
                        title: current.memory.title.clone(),
                        content: current.memory.content.clone(),
                        entities: current.projection.entities.clone(),
                        relationships: current.projection.relationships.clone(),
                    },
                )])
            },
        )?
        .items
        .into_iter()
        .next()
        .ok_or(KnowledgeError::Conflict)
    }
}
