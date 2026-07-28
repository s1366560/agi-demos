use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};
use serde_json::Value;

const SEARCH_BACKFILL_BATCH_SIZE: i64 = 256;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct LocalSearchProjectionState {
    pub(super) revision: i64,
    pub(super) backfill_cursor: Option<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct LocalSearchResult {
    pub(super) id: String,
    pub(super) title: String,
    pub(super) content: String,
    pub(super) score: f64,
    pub(super) source: String,
    pub(super) result_type: String,
    pub(super) created_at: Option<String>,
    pub(super) tags: Vec<String>,
}

#[derive(Clone, Debug, PartialEq)]
pub(super) struct LocalSearchPage {
    pub(super) results: Vec<LocalSearchResult>,
    pub(super) total: usize,
    pub(super) facets: BTreeMap<String, usize>,
}

pub(super) struct LocalSearchQuery<'a> {
    pub(super) tenant_id: &'a str,
    pub(super) project_id: &'a str,
    pub(super) query: &'a str,
    pub(super) since: Option<&'a str>,
    pub(super) until: Option<&'a str>,
    pub(super) entity_types: &'a [String],
    pub(super) tags: &'a [String],
    pub(super) limit: usize,
    pub(super) offset: usize,
}

pub(super) fn initialize_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_search_documents (
               source_id TEXT PRIMARY KEY,
               tenant_id TEXT NOT NULL,
               project_id TEXT NOT NULL,
               conversation_id TEXT NOT NULL,
               title TEXT NOT NULL,
               content TEXT NOT NULL,
               result_type TEXT NOT NULL,
               source TEXT NOT NULL,
               created_at TEXT,
               tags_json TEXT NOT NULL,
               source_rowid INTEGER NOT NULL
             );
             CREATE VIRTUAL TABLE IF NOT EXISTS desktop_search_documents_fts
               USING fts5(
                 source_id UNINDEXED,
                 title,
                 content,
                 tokenize = 'unicode61 remove_diacritics 2'
               );
             CREATE TABLE IF NOT EXISTS desktop_search_backfill (
               tenant_id TEXT NOT NULL,
               project_id TEXT NOT NULL,
               last_timeline_rowid INTEGER NOT NULL,
               revision INTEGER NOT NULL,
               updated_at TEXT NOT NULL,
               PRIMARY KEY(tenant_id, project_id)
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_search_documents_scope
               ON desktop_search_documents(
                 tenant_id, project_id, created_at DESC, source_rowid DESC
               );",
        )
        .map_err(|error| error.to_string())
}

pub(super) fn refresh_projection(
    connection: &mut Connection,
    tenant_id: &str,
    project_id: &str,
) -> Result<LocalSearchProjectionState, String> {
    let (last_timeline_rowid, revision) = connection
        .query_row(
            "SELECT last_timeline_rowid, revision
             FROM desktop_search_backfill
             WHERE tenant_id = ?1 AND project_id = ?2",
            params![tenant_id, project_id],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
        )
        .optional()
        .map_err(|error| error.to_string())?
        .unwrap_or((0, 0));

    let rows = {
        let mut statement = connection
            .prepare(
                "SELECT
                   timeline.rowid,
                   timeline.id,
                   timeline.conversation_id,
                   timeline.value_json,
                   conversations.value_json
                 FROM desktop_timeline AS timeline
                 JOIN desktop_conversations AS conversations
                   ON conversations.id = timeline.conversation_id
                 WHERE timeline.rowid > ?1
                   AND conversations.project_id = ?2
                   AND json_extract(conversations.value_json, '$.tenant_id') = ?3
                 ORDER BY timeline.rowid ASC
                 LIMIT ?4",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map(
                params![
                    last_timeline_rowid,
                    project_id,
                    tenant_id,
                    SEARCH_BACKFILL_BATCH_SIZE + 1
                ],
                |row| {
                    Ok((
                        row.get::<_, i64>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                        row.get::<_, String>(3)?,
                        row.get::<_, String>(4)?,
                    ))
                },
            )
            .map_err(|error| error.to_string())?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())?;
        rows
    };

    let has_more = rows.len() > SEARCH_BACKFILL_BATCH_SIZE as usize;
    let rows = rows
        .into_iter()
        .take(SEARCH_BACKFILL_BATCH_SIZE as usize)
        .collect::<Vec<_>>();
    let next_timeline_rowid = rows.last().map(|row| row.0).unwrap_or(last_timeline_rowid);
    let next_revision = revision.saturating_add(rows.len() as i64);

    let transaction = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|error| error.to_string())?;
    for (source_rowid, source_id, conversation_id, value_json, conversation_json) in rows {
        let value = serde_json::from_str::<Value>(&value_json)
            .map_err(|error| format!("invalid local timeline JSON: {error}"))?;
        let conversation = serde_json::from_str::<Value>(&conversation_json)
            .map_err(|error| format!("invalid local conversation JSON: {error}"))?;
        transaction
            .execute(
                "DELETE FROM desktop_search_documents_fts WHERE source_id = ?1",
                [&source_id],
            )
            .map_err(|error| error.to_string())?;
        let Some(document) = search_document(
            &source_id,
            tenant_id,
            project_id,
            &conversation_id,
            source_rowid,
            &value,
            &conversation,
        ) else {
            transaction
                .execute(
                    "DELETE FROM desktop_search_documents WHERE source_id = ?1",
                    [&source_id],
                )
                .map_err(|error| error.to_string())?;
            continue;
        };
        transaction
            .execute(
                "INSERT INTO desktop_search_documents(
                   source_id, tenant_id, project_id, conversation_id, title, content,
                   result_type, source, created_at, tags_json, source_rowid
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)
                 ON CONFLICT(source_id) DO UPDATE SET
                   tenant_id = excluded.tenant_id,
                   project_id = excluded.project_id,
                   conversation_id = excluded.conversation_id,
                   title = excluded.title,
                   content = excluded.content,
                   result_type = excluded.result_type,
                   source = excluded.source,
                   created_at = excluded.created_at,
                   tags_json = excluded.tags_json,
                   source_rowid = excluded.source_rowid",
                params![
                    document.source_id,
                    document.tenant_id,
                    document.project_id,
                    document.conversation_id,
                    document.title,
                    document.content,
                    document.result_type,
                    document.source,
                    document.created_at,
                    document.tags_json,
                    document.source_rowid,
                ],
            )
            .map_err(|error| error.to_string())?;
        transaction
            .execute(
                "INSERT INTO desktop_search_documents_fts(source_id, title, content)
                 VALUES (?1, ?2, ?3)",
                params![document.source_id, document.title, document.content],
            )
            .map_err(|error| error.to_string())?;
    }
    transaction
        .execute(
            "INSERT INTO desktop_search_backfill(
               tenant_id, project_id, last_timeline_rowid, revision, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5)
             ON CONFLICT(tenant_id, project_id) DO UPDATE SET
               last_timeline_rowid = excluded.last_timeline_rowid,
               revision = excluded.revision,
               updated_at = excluded.updated_at",
            params![
                tenant_id,
                project_id,
                next_timeline_rowid,
                next_revision,
                Utc::now().to_rfc3339(),
            ],
        )
        .map_err(|error| error.to_string())?;
    transaction.commit().map_err(|error| error.to_string())?;

    Ok(LocalSearchProjectionState {
        revision: next_revision,
        backfill_cursor: has_more.then(|| format!("timeline_rowid:{next_timeline_rowid}")),
    })
}

pub(super) fn search(
    connection: &Connection,
    query: &LocalSearchQuery<'_>,
) -> Result<LocalSearchPage, String> {
    let match_query = escaped_match_query(query.query)?;
    let entity_types_json =
        serde_json::to_string(query.entity_types).map_err(|error| error.to_string())?;
    let tags_json = serde_json::to_string(query.tags).map_err(|error| error.to_string())?;
    let query_parameters = params![
        match_query,
        query.tenant_id,
        query.project_id,
        query.since,
        query.until,
        entity_types_json,
        tags_json,
    ];
    let predicate = "desktop_search_documents_fts MATCH ?1
       AND documents.tenant_id = ?2
       AND documents.project_id = ?3
       AND (?4 IS NULL OR documents.created_at >= ?4)
       AND (?5 IS NULL OR documents.created_at <= ?5)
       AND (
         json_array_length(?6) = 0
         OR EXISTS (
           SELECT 1 FROM json_each(?6) AS requested_type
           WHERE requested_type.value = documents.result_type
         )
       )
       AND (
         json_array_length(?7) = 0
         OR EXISTS (
           SELECT 1
           FROM json_each(?7) AS requested_tag
           JOIN json_each(documents.tags_json) AS document_tag
             ON document_tag.value = requested_tag.value
         )
       )";

    let total = connection
        .query_row(
            &format!(
                "SELECT COUNT(*)
                 FROM desktop_search_documents_fts
                 JOIN desktop_search_documents AS documents
                   ON documents.source_id = desktop_search_documents_fts.source_id
                 WHERE {predicate}"
            ),
            query_parameters,
            |row| row.get::<_, i64>(0),
        )
        .map_err(|error| error.to_string())?;

    let mut statement = connection
        .prepare(&format!(
            "SELECT
               documents.source_id,
               documents.title,
               documents.content,
               bm25(desktop_search_documents_fts),
               documents.source,
               documents.result_type,
               documents.created_at,
               documents.tags_json
             FROM desktop_search_documents_fts
             JOIN desktop_search_documents AS documents
               ON documents.source_id = desktop_search_documents_fts.source_id
             WHERE {predicate}
             ORDER BY bm25(desktop_search_documents_fts) ASC,
                      documents.created_at DESC,
                      documents.source_rowid DESC
             LIMIT ?8 OFFSET ?9"
        ))
        .map_err(|error| error.to_string())?;
    let results = statement
        .query_map(
            params![
                match_query,
                query.tenant_id,
                query.project_id,
                query.since,
                query.until,
                entity_types_json,
                tags_json,
                query.limit as i64,
                query.offset as i64,
            ],
            |row| {
                let rank = row.get::<_, f64>(3)?;
                let tags_json = row.get::<_, String>(7)?;
                let tags = serde_json::from_str::<Vec<String>>(&tags_json).unwrap_or_default();
                Ok(LocalSearchResult {
                    id: row.get(0)?,
                    title: row.get(1)?,
                    content: row.get(2)?,
                    score: 1.0 / (1.0 + rank.abs()),
                    source: row.get(4)?,
                    result_type: row.get(5)?,
                    created_at: row.get(6)?,
                    tags,
                })
            },
        )
        .map_err(|error| error.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| error.to_string())?;

    let mut facet_statement = connection
        .prepare(&format!(
            "SELECT documents.result_type, COUNT(*)
             FROM desktop_search_documents_fts
             JOIN desktop_search_documents AS documents
               ON documents.source_id = desktop_search_documents_fts.source_id
             WHERE {predicate}
             GROUP BY documents.result_type
             ORDER BY documents.result_type ASC"
        ))
        .map_err(|error| error.to_string())?;
    let facets = facet_statement
        .query_map(
            params![
                match_query,
                query.tenant_id,
                query.project_id,
                query.since,
                query.until,
                entity_types_json,
                tags_json,
            ],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, usize>(1)?)),
        )
        .map_err(|error| error.to_string())?
        .collect::<Result<BTreeMap<_, _>, _>>()
        .map_err(|error| error.to_string())?;

    Ok(LocalSearchPage {
        results,
        total: usize::try_from(total).map_err(|error| error.to_string())?,
        facets,
    })
}

struct SearchDocument {
    source_id: String,
    tenant_id: String,
    project_id: String,
    conversation_id: String,
    title: String,
    content: String,
    result_type: String,
    source: &'static str,
    created_at: Option<String>,
    tags_json: String,
    source_rowid: i64,
}

fn search_document(
    source_id: &str,
    tenant_id: &str,
    project_id: &str,
    conversation_id: &str,
    source_rowid: i64,
    value: &Value,
    conversation: &Value,
) -> Option<SearchDocument> {
    let display = value.get("display").and_then(Value::as_object);
    let payload_display = value
        .get("payload")
        .and_then(|payload| payload.get("display"))
        .and_then(Value::as_object);
    let data = value.get("data").and_then(Value::as_object);
    let title = first_non_empty([
        value.get("title").and_then(Value::as_str),
        display
            .and_then(|value| value.get("title"))
            .and_then(Value::as_str),
        payload_display
            .and_then(|value| value.get("title"))
            .and_then(Value::as_str),
        conversation.get("title").and_then(Value::as_str),
    ])
    .unwrap_or("Local timeline");
    let content = first_non_empty([
        value.get("content").and_then(Value::as_str),
        data.and_then(|value| value.get("content"))
            .and_then(Value::as_str),
        value.get("summary").and_then(Value::as_str),
        display
            .and_then(|value| value.get("summary"))
            .and_then(Value::as_str),
        payload_display
            .and_then(|value| value.get("summary"))
            .and_then(Value::as_str),
    ])?;
    let result_type = first_non_empty([
        value.get("type").and_then(Value::as_str),
        value.get("event_type").and_then(Value::as_str),
    ])
    .unwrap_or("timeline");
    let tags = value
        .get("tags")
        .or_else(|| data.and_then(|data| data.get("tags")))
        .and_then(Value::as_array)
        .map(|tags| {
            tags.iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|tag| !tag.is_empty())
                .map(ToString::to_string)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    let created_at = timestamp(value).or_else(|| {
        first_non_empty([
            value.get("created_at").and_then(Value::as_str),
            value.get("updated_at").and_then(Value::as_str),
            conversation.get("updated_at").and_then(Value::as_str),
        ])
        .map(ToString::to_string)
    });
    Some(SearchDocument {
        source_id: source_id.to_string(),
        tenant_id: tenant_id.to_string(),
        project_id: project_id.to_string(),
        conversation_id: conversation_id.to_string(),
        title: title.to_string(),
        content: content.to_string(),
        result_type: result_type.to_string(),
        source: "desktop_timeline",
        created_at,
        tags_json: serde_json::to_string(&tags).ok()?,
        source_rowid,
    })
}

fn timestamp(value: &Value) -> Option<String> {
    for key in ["eventTimeUs", "event_time_us", "time_us"] {
        if let Some(timestamp) = value.get(key).and_then(Value::as_i64) {
            if let Some(date_time) = DateTime::<Utc>::from_timestamp_micros(timestamp) {
                return Some(date_time.to_rfc3339());
            }
        }
    }
    value
        .get("timestamp")
        .and_then(Value::as_i64)
        .and_then(DateTime::<Utc>::from_timestamp_millis)
        .map(|date_time| date_time.to_rfc3339())
}

fn first_non_empty<'a>(values: impl IntoIterator<Item = Option<&'a str>>) -> Option<&'a str> {
    values
        .into_iter()
        .flatten()
        .find(|value| !value.trim().is_empty())
}

fn escaped_match_query(query: &str) -> Result<String, String> {
    if query.len() > 2_048 {
        return Err("local search query is too large".to_string());
    }
    let terms = query
        .split_whitespace()
        .filter(|term| !term.is_empty())
        .map(|term| format!("\"{}\"", term.replace('"', "\"\"")))
        .collect::<Vec<_>>();
    if terms.is_empty() {
        return Err("local search query is empty".to_string());
    }
    Ok(terms.join(" AND "))
}
