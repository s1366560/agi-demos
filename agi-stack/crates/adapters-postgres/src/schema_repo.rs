//! Adapter over Python-owned project schema tables.
//!
//! Rust owns project-scoped schema collection reads plus schema CRUD in this
//! checkpoint. Runtime graph extraction still consumes these Python-owned rows.

use sqlx::types::chrono::{DateTime, Utc};
use sqlx::Row;

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const TYPE_COLS: &str =
    "id, project_id, name, description, schema, status, source, created_at, updated_at";
const MAP_COLS: &str =
    "id, project_id, source_type, target_type, edge_type, status, source, created_at";

#[derive(Debug, Clone, Copy)]
enum SchemaTypeTable {
    Entity,
    Edge,
}

impl SchemaTypeTable {
    fn table_name(self) -> &'static str {
        match self {
            Self::Entity => "entity_types",
            Self::Edge => "edge_types",
        }
    }

    fn duplicate_context(self) -> &'static str {
        match self {
            Self::Entity => "entity type duplicate check",
            Self::Edge => "edge type duplicate check",
        }
    }
}

#[derive(Debug, Clone)]
pub struct SchemaTypeRecord {
    pub id: String,
    pub project_id: String,
    pub name: String,
    pub description: Option<String>,
    pub schema_json: serde_json::Value,
    pub status: String,
    pub source: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct SchemaEdgeMapRecord {
    pub id: String,
    pub project_id: String,
    pub source_type: String,
    pub target_type: String,
    pub edge_type: String,
    pub status: String,
    pub source: String,
    pub created_at: DateTime<Utc>,
}

pub struct PgSchemaRepository {
    pool: PgPool,
}

pub struct CreateSchemaType<'a> {
    pub id: &'a str,
    pub project_id: &'a str,
    pub name: &'a str,
    pub description: Option<&'a str>,
    pub schema_json: &'a serde_json::Value,
}

pub struct UpdateSchemaType<'a> {
    pub description: Option<&'a str>,
    pub schema_json: Option<&'a serde_json::Value>,
}

pub struct CreateSchemaEdgeMap<'a> {
    pub id: &'a str,
    pub project_id: &'a str,
    pub source_type: &'a str,
    pub target_type: &'a str,
    pub edge_type: &'a str,
}

impl PgSchemaRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn list_entity_types(&self, project_id: &str) -> CoreResult<Vec<SchemaTypeRecord>> {
        let sql = format!("SELECT {TYPE_COLS} FROM entity_types WHERE project_id = $1");
        self.list_type_rows(&sql, project_id, "list entity types")
            .await
    }

    pub async fn list_edge_types(&self, project_id: &str) -> CoreResult<Vec<SchemaTypeRecord>> {
        let sql = format!("SELECT {TYPE_COLS} FROM edge_types WHERE project_id = $1");
        self.list_type_rows(&sql, project_id, "list edge types")
            .await
    }

    pub async fn user_can_write_schema(&self, user_id: &str, project_id: &str) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM user_projects \
             WHERE user_id = $1 AND project_id = $2 AND role IN ('owner', 'admin', 'member')",
        )
        .bind(user_id)
        .bind(project_id)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("schema write access check: {e}")))?;
        Ok(row.0 > 0)
    }

    pub async fn entity_type_name_exists(&self, project_id: &str, name: &str) -> CoreResult<bool> {
        self.type_name_exists(SchemaTypeTable::Entity, project_id, name)
            .await
    }

    pub async fn edge_type_name_exists(&self, project_id: &str, name: &str) -> CoreResult<bool> {
        self.type_name_exists(SchemaTypeTable::Edge, project_id, name)
            .await
    }

    pub async fn edge_map_exists(
        &self,
        project_id: &str,
        source_type: &str,
        target_type: &str,
        edge_type: &str,
    ) -> CoreResult<bool> {
        let row = sqlx::query_as::<_, (i64,)>(
            "SELECT count(*) FROM edge_type_maps \
             WHERE project_id = $1 AND source_type = $2 AND target_type = $3 AND edge_type = $4",
        )
        .bind(project_id)
        .bind(source_type)
        .bind(target_type)
        .bind(edge_type)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("edge type map duplicate check: {e}")))?;
        Ok(row.0 > 0)
    }

    pub async fn create_entity_type(
        &self,
        input: CreateSchemaType<'_>,
    ) -> CoreResult<SchemaTypeRecord> {
        self.create_type(SchemaTypeTable::Entity, input).await
    }

    pub async fn create_edge_type(
        &self,
        input: CreateSchemaType<'_>,
    ) -> CoreResult<SchemaTypeRecord> {
        self.create_type(SchemaTypeTable::Edge, input).await
    }

    pub async fn update_entity_type(
        &self,
        project_id: &str,
        entity_id: &str,
        input: UpdateSchemaType<'_>,
    ) -> CoreResult<Option<SchemaTypeRecord>> {
        self.update_type(SchemaTypeTable::Entity, project_id, entity_id, input)
            .await
    }

    pub async fn update_edge_type(
        &self,
        project_id: &str,
        edge_id: &str,
        input: UpdateSchemaType<'_>,
    ) -> CoreResult<Option<SchemaTypeRecord>> {
        self.update_type(SchemaTypeTable::Edge, project_id, edge_id, input)
            .await
    }

    pub async fn delete_entity_type(&self, project_id: &str, entity_id: &str) -> CoreResult<bool> {
        self.delete_type(SchemaTypeTable::Entity, project_id, entity_id)
            .await
    }

    pub async fn delete_edge_type(&self, project_id: &str, edge_id: &str) -> CoreResult<bool> {
        self.delete_type(SchemaTypeTable::Edge, project_id, edge_id)
            .await
    }

    pub async fn create_edge_map(
        &self,
        input: CreateSchemaEdgeMap<'_>,
    ) -> CoreResult<SchemaEdgeMapRecord> {
        let row = sqlx::query(&format!(
            "INSERT INTO edge_type_maps \
             (id, project_id, source_type, target_type, edge_type, status, source, created_at) \
             VALUES ($1, $2, $3, $4, $5, 'ENABLED', 'user', now()) \
             RETURNING {MAP_COLS}"
        ))
        .bind(input.id)
        .bind(input.project_id)
        .bind(input.source_type)
        .bind(input.target_type)
        .bind(input.edge_type)
        .fetch_one(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(format!("create edge type map: {e}")))?;
        Self::edge_map_from_row(row)
            .map_err(|e| CoreError::Storage(format!("read created edge type map row: {e}")))
    }

    pub async fn delete_edge_map(&self, project_id: &str, map_id: &str) -> CoreResult<bool> {
        let result = sqlx::query("DELETE FROM edge_type_maps WHERE id = $1 AND project_id = $2")
            .bind(map_id)
            .bind(project_id)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("delete edge type map: {e}")))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn list_edge_maps(&self, project_id: &str) -> CoreResult<Vec<SchemaEdgeMapRecord>> {
        let sql = format!("SELECT {MAP_COLS} FROM edge_type_maps WHERE project_id = $1");
        let rows = sqlx::query(&sql)
            .bind(project_id)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list edge type maps: {e}")))?;

        rows.into_iter()
            .map(Self::edge_map_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read edge type map row: {e}")))
    }

    async fn type_name_exists(
        &self,
        table: SchemaTypeTable,
        project_id: &str,
        name: &str,
    ) -> CoreResult<bool> {
        let sql = format!(
            "SELECT count(*) FROM {} WHERE project_id = $1 AND name = $2",
            table.table_name()
        );
        let row = sqlx::query_as::<_, (i64,)>(&sql)
            .bind(project_id)
            .bind(name)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("{}: {e}", table.duplicate_context())))?;
        Ok(row.0 > 0)
    }

    async fn create_type(
        &self,
        table: SchemaTypeTable,
        input: CreateSchemaType<'_>,
    ) -> CoreResult<SchemaTypeRecord> {
        let sql = format!(
            "INSERT INTO {} \
             (id, project_id, name, description, schema, status, source, created_at, updated_at) \
             VALUES ($1, $2, $3, $4, $5, 'ENABLED', 'user', now(), NULL) \
             RETURNING {TYPE_COLS}",
            table.table_name()
        );
        let row = sqlx::query(&sql)
            .bind(input.id)
            .bind(input.project_id)
            .bind(input.name)
            .bind(input.description)
            .bind(input.schema_json)
            .fetch_one(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("create {}: {e}", table.table_name())))?;
        Self::schema_type_from_row(row)
            .map_err(|e| CoreError::Storage(format!("read created schema type row: {e}")))
    }

    async fn update_type(
        &self,
        table: SchemaTypeTable,
        project_id: &str,
        type_id: &str,
        input: UpdateSchemaType<'_>,
    ) -> CoreResult<Option<SchemaTypeRecord>> {
        let sql = format!(
            "UPDATE {} \
             SET description = COALESCE($3, description), \
                 schema = COALESCE($4, schema), \
                 updated_at = CASE \
                     WHEN $3::text IS NOT NULL OR $4::json IS NOT NULL THEN now() \
                     ELSE updated_at \
                 END \
             WHERE id = $1 AND project_id = $2 \
             RETURNING {TYPE_COLS}",
            table.table_name()
        );
        let row = sqlx::query(&sql)
            .bind(type_id)
            .bind(project_id)
            .bind(input.description)
            .bind(input.schema_json)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("update {}: {e}", table.table_name())))?;
        row.map(Self::schema_type_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read updated schema type row: {e}")))
    }

    async fn delete_type(
        &self,
        table: SchemaTypeTable,
        project_id: &str,
        type_id: &str,
    ) -> CoreResult<bool> {
        let sql = format!(
            "DELETE FROM {} WHERE id = $1 AND project_id = $2",
            table.table_name()
        );
        let result = sqlx::query(&sql)
            .bind(type_id)
            .bind(project_id)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("delete {}: {e}", table.table_name())))?;
        Ok(result.rows_affected() > 0)
    }

    async fn list_type_rows(
        &self,
        sql: &str,
        project_id: &str,
        context: &'static str,
    ) -> CoreResult<Vec<SchemaTypeRecord>> {
        let rows = sqlx::query(sql)
            .bind(project_id)
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("{context}: {e}")))?;

        rows.into_iter()
            .map(Self::schema_type_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read project schema row: {e}")))
    }

    fn schema_type_from_row(row: sqlx::postgres::PgRow) -> Result<SchemaTypeRecord, sqlx::Error> {
        Ok(SchemaTypeRecord {
            id: row.try_get("id")?,
            project_id: row.try_get("project_id")?,
            name: row.try_get("name")?,
            description: row.try_get("description")?,
            schema_json: row.try_get("schema")?,
            status: row.try_get("status")?,
            source: row.try_get("source")?,
            created_at: row.try_get("created_at")?,
            updated_at: row.try_get("updated_at")?,
        })
    }

    fn edge_map_from_row(row: sqlx::postgres::PgRow) -> Result<SchemaEdgeMapRecord, sqlx::Error> {
        Ok(SchemaEdgeMapRecord {
            id: row.try_get("id")?,
            project_id: row.try_get("project_id")?,
            source_type: row.try_get("source_type")?,
            target_type: row.try_get("target_type")?,
            edge_type: row.try_get("edge_type")?,
            status: row.try_get("status")?,
            source: row.try_get("source")?,
            created_at: row.try_get("created_at")?,
        })
    }
}
