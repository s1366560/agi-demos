//! Read-only adapter over Python-owned gene marketplace tables.
//!
//! Rust owns only gene list/detail reads in this checkpoint. Gene writes,
//! genomes, installation, ratings, reviews, and evolution events remain
//! Python-owned.

use std::collections::HashMap;

use serde_json::{json, Value};
use sqlx::postgres::PgRow;
use sqlx::types::chrono::{DateTime, Utc};
use sqlx::{Postgres, QueryBuilder, Row};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

const GENE_COLS: &str = "id, name, slug, tenant_id, description, short_description, category, \
    tags, source, source_ref, icon, version, manifest, dependencies, synergies, parent_gene_id, \
    created_by_instance_id, install_count, avg_rating, effectiveness_score, is_featured, \
    review_status, is_published, visibility, created_by, created_at, updated_at";

const GENOME_COLS: &str = "id, name, slug, tenant_id, description, short_description, icon, \
    gene_slugs, config_override, install_count, avg_rating, is_featured, is_published, \
    visibility, created_by, created_at, updated_at";

#[derive(Debug, Clone, Copy)]
pub struct GeneListQuery<'a> {
    pub tenant_id: &'a str,
    pub include_global: bool,
    pub category: Option<&'a str>,
    pub search: Option<&'a str>,
    pub slugs: &'a [String],
    pub visibility: Option<&'a str>,
    pub is_published: Option<bool>,
    pub exclude_installed_instance_id: Option<&'a str>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, Copy)]
pub struct GenomeListQuery<'a> {
    pub tenant_id: &'a str,
    pub include_global: bool,
    pub search: Option<&'a str>,
    pub visibility: Option<&'a str>,
    pub is_published: Option<bool>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GeneTenantAccess {
    Allowed,
    Forbidden,
    NotFound,
}

#[derive(Debug, Clone)]
pub struct GeneRecord {
    pub id: String,
    pub name: String,
    pub slug: String,
    pub tenant_id: Option<String>,
    pub description: Option<String>,
    pub short_description: Option<String>,
    pub category: Option<String>,
    pub tags: Vec<String>,
    pub source: String,
    pub source_ref: Option<String>,
    pub icon: Option<String>,
    pub version: String,
    pub manifest: Value,
    pub dependencies: Vec<String>,
    pub synergies: Vec<String>,
    pub parent_gene_id: Option<String>,
    pub created_by_instance_id: Option<String>,
    pub install_count: i32,
    pub avg_rating: f64,
    pub effectiveness_score: f64,
    pub is_featured: bool,
    pub review_status: String,
    pub is_published: bool,
    pub visibility: String,
    pub created_by: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Clone)]
pub struct GenomeRecord {
    pub id: String,
    pub name: String,
    pub slug: String,
    pub tenant_id: Option<String>,
    pub description: Option<String>,
    pub short_description: Option<String>,
    pub icon: Option<String>,
    pub gene_slugs: Vec<String>,
    pub config_override: Value,
    pub install_count: i32,
    pub avg_rating: f64,
    pub is_featured: bool,
    pub is_published: bool,
    pub visibility: String,
    pub created_by: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: Option<DateTime<Utc>>,
}

pub struct PgGeneRepository {
    pool: PgPool,
}

impl PgGeneRepository {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn default_tenant_for_user(&self, user_id: &str) -> CoreResult<Option<String>> {
        sqlx::query_as::<_, (String,)>(
            "SELECT tenant_id \
             FROM user_tenants \
             WHERE user_id = $1 \
             ORDER BY created_at ASC, id ASC \
             LIMIT 1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(tenant_id,)| tenant_id))
        .map_err(|e| CoreError::Storage(format!("read gene default tenant: {e}")))
    }

    pub async fn tenant_access_for_user(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> CoreResult<GeneTenantAccess> {
        let tenant_exists =
            sqlx::query_as::<_, (i64,)>("SELECT COUNT(*) FROM tenants WHERE id = $1")
                .bind(tenant_id)
                .fetch_one(&self.pool)
                .await
                .map(|(count,)| count > 0)
                .map_err(|e| CoreError::Storage(format!("read gene tenant: {e}")))?;
        if !tenant_exists {
            return Ok(GeneTenantAccess::NotFound);
        }

        if self.user_has_global_admin(user_id).await? {
            return Ok(GeneTenantAccess::Allowed);
        }

        let count = sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) FROM user_tenants WHERE user_id = $1 AND tenant_id = $2",
        )
        .bind(user_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count)
        .map_err(|e| CoreError::Storage(format!("read gene tenant membership: {e}")))?;

        if count > 0 {
            Ok(GeneTenantAccess::Allowed)
        } else {
            Ok(GeneTenantAccess::Forbidden)
        }
    }

    pub async fn instance_belongs_to_tenant(
        &self,
        tenant_id: &str,
        instance_id: &str,
    ) -> CoreResult<bool> {
        sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) \
             FROM instances \
             WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL",
        )
        .bind(instance_id)
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read gene instance access: {e}")))
    }

    pub async fn list_genes(&self, query: GeneListQuery<'_>) -> CoreResult<(Vec<GeneRecord>, i64)> {
        if !query.slugs.is_empty() {
            return self.list_genes_by_slugs(query).await;
        }

        let mut count = QueryBuilder::<Postgres>::new("SELECT COUNT(*)");
        push_gene_filters(&mut count, &query);
        let total = count
            .build_query_as::<(i64,)>()
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count)
            .map_err(|e| CoreError::Storage(format!("count genes: {e}")))?;

        let mut list = QueryBuilder::<Postgres>::new(format!("SELECT {GENE_COLS}"));
        push_gene_filters(&mut list, &query);
        list.push(" ORDER BY created_at DESC, id ASC LIMIT ");
        list.push_bind(query.limit);
        list.push(" OFFSET ");
        list.push_bind(query.offset);

        let rows = list
            .build()
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list genes: {e}")))?;
        let records = rows
            .into_iter()
            .map(gene_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read gene row: {e}")))?;
        Ok((records, total))
    }

    pub async fn get_gene(&self, gene_id: &str) -> CoreResult<Option<GeneRecord>> {
        let sql = format!(
            "SELECT {GENE_COLS} \
             FROM gene_market \
             WHERE id = $1 AND deleted_at IS NULL"
        );
        sqlx::query(&sql)
            .bind(gene_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get gene: {e}")))?
            .map(gene_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read gene row: {e}")))
    }

    pub async fn list_genomes(
        &self,
        query: GenomeListQuery<'_>,
    ) -> CoreResult<(Vec<GenomeRecord>, i64)> {
        let mut count = QueryBuilder::<Postgres>::new("SELECT COUNT(*)");
        push_genome_filters(&mut count, &query);
        let total = count
            .build_query_as::<(i64,)>()
            .fetch_one(&self.pool)
            .await
            .map(|(count,)| count)
            .map_err(|e| CoreError::Storage(format!("count genomes: {e}")))?;

        let mut list = QueryBuilder::<Postgres>::new(format!("SELECT {GENOME_COLS}"));
        push_genome_filters(&mut list, &query);
        list.push(" ORDER BY created_at DESC, id ASC LIMIT ");
        list.push_bind(query.limit);
        list.push(" OFFSET ");
        list.push_bind(query.offset);

        let rows = list
            .build()
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list genomes: {e}")))?;
        let records = rows
            .into_iter()
            .map(genome_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read genome row: {e}")))?;
        Ok((records, total))
    }

    pub async fn get_genome(&self, genome_id: &str) -> CoreResult<Option<GenomeRecord>> {
        let sql = format!(
            "SELECT {GENOME_COLS} \
             FROM genomes \
             WHERE id = $1 AND deleted_at IS NULL"
        );
        sqlx::query(&sql)
            .bind(genome_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("get genome: {e}")))?
            .map(genome_from_row)
            .transpose()
            .map_err(|e| CoreError::Storage(format!("read genome row: {e}")))
    }

    async fn list_genes_by_slugs(
        &self,
        query: GeneListQuery<'_>,
    ) -> CoreResult<(Vec<GeneRecord>, i64)> {
        let normalized_slugs = normalize_slugs(query.slugs);
        if normalized_slugs.is_empty() {
            return Ok((Vec::new(), 0));
        }

        let slug_query = GeneListQuery {
            slugs: &normalized_slugs,
            limit: (normalized_slugs.len() * 2) as i64,
            offset: 0,
            ..query
        };
        let mut list = QueryBuilder::<Postgres>::new(format!("SELECT {GENE_COLS}"));
        push_gene_filters(&mut list, &slug_query);
        list.push(" ORDER BY created_at DESC, id ASC LIMIT ");
        list.push_bind(slug_query.limit);
        list.push(" OFFSET 0");

        let rows = list
            .build()
            .fetch_all(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(format!("list genes by slug: {e}")))?;
        let candidates = rows
            .into_iter()
            .map(gene_from_row)
            .collect::<Result<Vec<_>, sqlx::Error>>()
            .map_err(|e| CoreError::Storage(format!("read gene row: {e}")))?;

        let mut by_slug: HashMap<String, GeneRecord> = HashMap::new();
        for gene in candidates {
            match by_slug.get(&gene.slug) {
                Some(current)
                    if gene.tenant_id.as_deref() != Some(query.tenant_id)
                        || current.tenant_id.as_deref() == Some(query.tenant_id) => {}
                _ => {
                    by_slug.insert(gene.slug.clone(), gene);
                }
            }
        }

        let ordered = normalized_slugs
            .into_iter()
            .filter_map(|slug| by_slug.remove(&slug))
            .collect::<Vec<_>>();
        let total = ordered.len() as i64;
        let records = ordered
            .into_iter()
            .skip(query.offset as usize)
            .take(query.limit as usize)
            .collect();
        Ok((records, total))
    }

    async fn user_has_global_admin(&self, user_id: &str) -> CoreResult<bool> {
        let is_superuser = sqlx::query_as::<_, (bool,)>(
            "SELECT COALESCE(is_superuser, false) FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map(|row| row.map(|(is_superuser,)| is_superuser).unwrap_or(false))
        .map_err(|e| CoreError::Storage(format!("read gene user superuser: {e}")))?;
        if is_superuser {
            return Ok(true);
        }

        sqlx::query_as::<_, (i64,)>(
            "SELECT COUNT(*) \
             FROM user_roles \
             JOIN roles ON roles.id = user_roles.role_id \
             WHERE user_roles.user_id = $1 \
               AND user_roles.tenant_id IS NULL \
               AND roles.name = 'system_admin'",
        )
        .bind(user_id)
        .fetch_one(&self.pool)
        .await
        .map(|(count,)| count > 0)
        .map_err(|e| CoreError::Storage(format!("read gene user global role: {e}")))
    }
}

fn push_gene_filters<'a>(builder: &mut QueryBuilder<'a, Postgres>, query: &GeneListQuery<'a>) {
    builder.push(" FROM gene_market WHERE deleted_at IS NULL");
    if query.include_global {
        builder.push(" AND (tenant_id = ");
        builder.push_bind(query.tenant_id);
        builder.push(" OR (tenant_id IS NULL AND is_published = TRUE AND visibility = 'public'))");
    } else {
        builder.push(" AND tenant_id = ");
        builder.push_bind(query.tenant_id);
    }

    if let Some(category) = query.category {
        builder.push(" AND category = ");
        builder.push_bind(category);
    }
    if let Some(visibility) = query.visibility {
        builder.push(" AND visibility = ");
        builder.push_bind(visibility);
    }
    if let Some(is_published) = query.is_published {
        builder.push(" AND is_published = ");
        builder.push_bind(is_published);
    }
    if let Some(search) = query
        .search
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        let pattern = format!("%{search}%");
        builder.push(" AND (name ILIKE ");
        builder.push_bind(pattern.clone());
        builder.push(" OR slug ILIKE ");
        builder.push_bind(pattern.clone());
        builder.push(" OR description ILIKE ");
        builder.push_bind(pattern.clone());
        builder.push(" OR short_description ILIKE ");
        builder.push_bind(pattern);
        builder.push(")");
    }
    if !query.slugs.is_empty() {
        builder.push(" AND slug IN (");
        let mut separated = builder.separated(", ");
        for slug in query.slugs {
            separated.push_bind(slug);
        }
        separated.push_unseparated(")");
    }
    if let Some(instance_id) = query.exclude_installed_instance_id {
        builder.push(
            " AND NOT EXISTS (\
                SELECT 1 FROM instance_genes \
                WHERE instance_genes.instance_id = ",
        );
        builder.push_bind(instance_id);
        builder.push(
            " AND instance_genes.gene_id = gene_market.id \
              AND instance_genes.deleted_at IS NULL)",
        );
    }
}

fn push_genome_filters<'a>(builder: &mut QueryBuilder<'a, Postgres>, query: &GenomeListQuery<'a>) {
    builder.push(" FROM genomes WHERE deleted_at IS NULL");
    if query.include_global {
        builder.push(" AND (tenant_id = ");
        builder.push_bind(query.tenant_id);
        builder.push(" OR (tenant_id IS NULL AND is_published = TRUE AND visibility = 'public'))");
    } else {
        builder.push(" AND tenant_id = ");
        builder.push_bind(query.tenant_id);
    }

    if let Some(visibility) = query.visibility {
        builder.push(" AND visibility = ");
        builder.push_bind(visibility);
    }
    if let Some(is_published) = query.is_published {
        builder.push(" AND is_published = ");
        builder.push_bind(is_published);
    }
    if let Some(search) = query
        .search
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        let pattern = format!("%{search}%");
        builder.push(" AND (name ILIKE ");
        builder.push_bind(pattern.clone());
        builder.push(" OR slug ILIKE ");
        builder.push_bind(pattern.clone());
        builder.push(" OR description ILIKE ");
        builder.push_bind(pattern.clone());
        builder.push(" OR short_description ILIKE ");
        builder.push_bind(pattern);
        builder.push(")");
    }
}

fn gene_from_row(row: PgRow) -> Result<GeneRecord, sqlx::Error> {
    Ok(GeneRecord {
        id: row.try_get("id")?,
        name: row.try_get("name")?,
        slug: row.try_get("slug")?,
        tenant_id: row.try_get("tenant_id")?,
        description: row.try_get("description")?,
        short_description: row.try_get("short_description")?,
        category: row.try_get("category")?,
        tags: string_vec_or_default(&row, "tags")?,
        source: string_or_default(&row, "source", "official")?,
        source_ref: row.try_get("source_ref")?,
        icon: row.try_get("icon")?,
        version: string_or_default(&row, "version", "1.0.0")?,
        manifest: object_or_default(&row, "manifest")?,
        dependencies: string_vec_or_default(&row, "dependencies")?,
        synergies: string_vec_or_default(&row, "synergies")?,
        parent_gene_id: row.try_get("parent_gene_id")?,
        created_by_instance_id: row.try_get("created_by_instance_id")?,
        install_count: int_or_default(&row, "install_count", 0)?,
        avg_rating: float_or_default(&row, "avg_rating", 0.0)?,
        effectiveness_score: float_or_default(&row, "effectiveness_score", 0.0)?,
        is_featured: bool_or_default(&row, "is_featured", false)?,
        review_status: string_or_default(&row, "review_status", "pending")?,
        is_published: bool_or_default(&row, "is_published", false)?,
        visibility: string_or_default(&row, "visibility", "public")?,
        created_by: string_or_default(&row, "created_by", "")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn genome_from_row(row: PgRow) -> Result<GenomeRecord, sqlx::Error> {
    Ok(GenomeRecord {
        id: row.try_get("id")?,
        name: row.try_get("name")?,
        slug: row.try_get("slug")?,
        tenant_id: row.try_get("tenant_id")?,
        description: row.try_get("description")?,
        short_description: row.try_get("short_description")?,
        icon: row.try_get("icon")?,
        gene_slugs: string_vec_or_default(&row, "gene_slugs")?,
        config_override: object_or_default(&row, "config_override")?,
        install_count: int_or_default(&row, "install_count", 0)?,
        avg_rating: float_or_default(&row, "avg_rating", 0.0)?,
        is_featured: bool_or_default(&row, "is_featured", false)?,
        is_published: bool_or_default(&row, "is_published", false)?,
        visibility: string_or_default(&row, "visibility", "public")?,
        created_by: string_or_default(&row, "created_by", "")?,
        created_at: row.try_get("created_at")?,
        updated_at: row.try_get("updated_at")?,
    })
}

fn normalize_slugs(slugs: &[String]) -> Vec<String> {
    let mut normalized = Vec::new();
    for slug in slugs {
        let trimmed = slug.trim();
        if !trimmed.is_empty() && !normalized.iter().any(|seen| seen == trimmed) {
            normalized.push(trimmed.to_string());
        }
    }
    normalized
}

fn string_vec_or_default(row: &PgRow, column: &str) -> Result<Vec<String>, sqlx::Error> {
    let value = row.try_get::<Option<Value>, _>(column)?;
    Ok(match value {
        Some(Value::Array(items)) => items
            .into_iter()
            .filter_map(|item| item.as_str().map(ToString::to_string))
            .collect(),
        _ => Vec::new(),
    })
}

fn object_or_default(row: &PgRow, column: &str) -> Result<Value, sqlx::Error> {
    let value = row.try_get::<Option<Value>, _>(column)?;
    Ok(match value {
        Some(value @ Value::Object(_)) => value,
        _ => json!({}),
    })
}

fn string_or_default(row: &PgRow, column: &str, default: &str) -> Result<String, sqlx::Error> {
    row.try_get::<Option<String>, _>(column)
        .map(|value| value.unwrap_or_else(|| default.to_string()))
}

fn int_or_default(row: &PgRow, column: &str, default: i32) -> Result<i32, sqlx::Error> {
    row.try_get::<Option<i32>, _>(column)
        .map(|value| value.unwrap_or(default))
}

fn float_or_default(row: &PgRow, column: &str, default: f64) -> Result<f64, sqlx::Error> {
    row.try_get::<Option<f64>, _>(column)
        .map(|value| value.unwrap_or(default))
}

fn bool_or_default(row: &PgRow, column: &str, default: bool) -> Result<bool, sqlx::Error> {
    row.try_get::<Option<bool>, _>(column)
        .map(|value| value.unwrap_or(default))
}
