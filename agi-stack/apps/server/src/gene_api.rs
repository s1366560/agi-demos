//! P7 gene marketplace read-side strangler slice.
//!
//! Rust owns only current-tenant gene list/detail reads. Gene writes, genomes,
//! installation, ratings, reviews, and evolution events remain Python-owned.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    GeneListQuery as PgGeneListQuery, GeneRecord, GeneTenantAccess,
    GenomeListQuery as PgGenomeListQuery, GenomeRecord, PgGeneRepository,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedGenes = Arc<dyn GeneService>;

#[async_trait]
pub(crate) trait GeneService: Send + Sync {
    async fn list_genes(
        &self,
        user_id: &str,
        query: ValidatedGeneListQuery,
    ) -> Result<GeneListResponse, GeneApiError>;

    async fn get_gene(
        &self,
        user_id: &str,
        selected_tenant_id: Option<&str>,
        gene_id: &str,
    ) -> Result<GeneView, GeneApiError>;

    async fn list_genomes(
        &self,
        user_id: &str,
        query: ValidatedGenomeListQuery,
    ) -> Result<GenomeListResponse, GeneApiError>;

    async fn get_genome(
        &self,
        user_id: &str,
        selected_tenant_id: Option<&str>,
        genome_id: &str,
    ) -> Result<GenomeView, GeneApiError>;
}

pub(crate) struct PgGeneService {
    repo: PgGeneRepository,
}

impl PgGeneService {
    pub(crate) fn new(repo: PgGeneRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl GeneService for PgGeneService {
    async fn list_genes(
        &self,
        user_id: &str,
        query: ValidatedGeneListQuery,
    ) -> Result<GeneListResponse, GeneApiError> {
        let tenant_id =
            resolve_selected_tenant(&self.repo, user_id, query.tenant_id.as_deref()).await?;
        if let Some(instance_id) = query.exclude_installed_instance_id.as_deref() {
            let accessible = self
                .repo
                .instance_belongs_to_tenant(&tenant_id, instance_id)
                .await
                .map_err(GeneApiError::internal)?;
            if !accessible {
                return Err(GeneApiError::not_found("Instance not found"));
            }
        }

        let (records, total) = self
            .repo
            .list_genes(PgGeneListQuery {
                tenant_id: &tenant_id,
                include_global: true,
                category: query.category.as_deref(),
                search: query.search.as_deref(),
                slugs: &query.slugs,
                visibility: query.visibility.as_deref(),
                is_published: query.is_published,
                exclude_installed_instance_id: query.exclude_installed_instance_id.as_deref(),
                limit: query.page_size,
                offset: query.offset,
            })
            .await
            .map_err(GeneApiError::internal)?;
        Ok(GeneListResponse::from_records(
            records,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_gene(
        &self,
        user_id: &str,
        selected_tenant_id: Option<&str>,
        gene_id: &str,
    ) -> Result<GeneView, GeneApiError> {
        let tenant_id = resolve_selected_tenant(&self.repo, user_id, selected_tenant_id).await?;
        self.repo
            .get_gene(gene_id)
            .await
            .map_err(GeneApiError::internal)?
            .filter(|gene| gene_visible_for_tenant(gene, &tenant_id))
            .map(GeneView::from)
            .ok_or_else(|| GeneApiError::not_found("Gene not found"))
    }

    async fn list_genomes(
        &self,
        user_id: &str,
        query: ValidatedGenomeListQuery,
    ) -> Result<GenomeListResponse, GeneApiError> {
        let tenant_id =
            resolve_selected_tenant(&self.repo, user_id, query.tenant_id.as_deref()).await?;
        let (records, total) = self
            .repo
            .list_genomes(PgGenomeListQuery {
                tenant_id: &tenant_id,
                include_global: true,
                search: query.search.as_deref(),
                visibility: query.visibility.as_deref(),
                is_published: query.is_published,
                limit: query.page_size,
                offset: query.offset,
            })
            .await
            .map_err(GeneApiError::internal)?;
        Ok(GenomeListResponse::from_records(
            records,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_genome(
        &self,
        user_id: &str,
        selected_tenant_id: Option<&str>,
        genome_id: &str,
    ) -> Result<GenomeView, GeneApiError> {
        let tenant_id = resolve_selected_tenant(&self.repo, user_id, selected_tenant_id).await?;
        self.repo
            .get_genome(genome_id)
            .await
            .map_err(GeneApiError::internal)?
            .filter(|genome| genome_visible_for_tenant(genome, &tenant_id))
            .map(GenomeView::from)
            .ok_or_else(|| GeneApiError::not_found("Genome not found"))
    }
}

#[derive(Default)]
pub(crate) struct DevGeneService {
    tenant_id: String,
    genes: Vec<GeneRecord>,
    genomes: Vec<GenomeRecord>,
}

impl DevGeneService {
    #[cfg(test)]
    pub(crate) fn new(tenant_id: impl Into<String>, genes: Vec<GeneRecord>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            genes,
            genomes: Vec::new(),
        }
    }

    #[cfg(test)]
    pub(crate) fn new_with_genomes(
        tenant_id: impl Into<String>,
        genes: Vec<GeneRecord>,
        genomes: Vec<GenomeRecord>,
    ) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            genes,
            genomes,
        }
    }
}

#[async_trait]
impl GeneService for DevGeneService {
    async fn list_genes(
        &self,
        _user_id: &str,
        query: ValidatedGeneListQuery,
    ) -> Result<GeneListResponse, GeneApiError> {
        let tenant_id = query.tenant_id.as_deref().unwrap_or(&self.tenant_id);
        let mut genes = self
            .genes
            .iter()
            .filter(|gene| gene_visible_for_tenant(gene, tenant_id))
            .filter(|gene| optional_eq(gene.category.as_deref(), query.category.as_deref()))
            .filter(|gene| optional_eq(Some(gene.visibility.as_str()), query.visibility.as_deref()))
            .filter(|gene| {
                query
                    .is_published
                    .is_none_or(|value| gene.is_published == value)
            })
            .filter(|gene| search_matches(gene, query.search.as_deref()))
            .cloned()
            .collect::<Vec<_>>();

        if !query.slugs.is_empty() {
            genes = resolve_slug_order(genes, tenant_id, &query.slugs);
        } else {
            sort_genes(&mut genes);
        }

        let total = genes.len() as i64;
        let page = page(genes, query.page_size, query.offset);
        Ok(GeneListResponse::from_records(
            page,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_gene(
        &self,
        _user_id: &str,
        selected_tenant_id: Option<&str>,
        gene_id: &str,
    ) -> Result<GeneView, GeneApiError> {
        let tenant_id = selected_tenant_id.unwrap_or(&self.tenant_id);
        self.genes
            .iter()
            .find(|gene| gene.id == gene_id && gene_visible_for_tenant(gene, tenant_id))
            .cloned()
            .map(GeneView::from)
            .ok_or_else(|| GeneApiError::not_found("Gene not found"))
    }

    async fn list_genomes(
        &self,
        _user_id: &str,
        query: ValidatedGenomeListQuery,
    ) -> Result<GenomeListResponse, GeneApiError> {
        let tenant_id = query.tenant_id.as_deref().unwrap_or(&self.tenant_id);
        let mut genomes = self
            .genomes
            .iter()
            .filter(|genome| genome_visible_for_tenant(genome, tenant_id))
            .filter(|genome| {
                optional_eq(
                    Some(genome.visibility.as_str()),
                    query.visibility.as_deref(),
                )
            })
            .filter(|genome| {
                query
                    .is_published
                    .is_none_or(|value| genome.is_published == value)
            })
            .filter(|genome| genome_search_matches(genome, query.search.as_deref()))
            .cloned()
            .collect::<Vec<_>>();
        sort_genomes(&mut genomes);
        let total = genomes.len() as i64;
        let page = page(genomes, query.page_size, query.offset);
        Ok(GenomeListResponse::from_records(
            page,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_genome(
        &self,
        _user_id: &str,
        selected_tenant_id: Option<&str>,
        genome_id: &str,
    ) -> Result<GenomeView, GeneApiError> {
        let tenant_id = selected_tenant_id.unwrap_or(&self.tenant_id);
        self.genomes
            .iter()
            .find(|genome| genome.id == genome_id && genome_visible_for_tenant(genome, tenant_id))
            .cloned()
            .map(GenomeView::from)
            .ok_or_else(|| GeneApiError::not_found("Genome not found"))
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/genes/", get(list_genes))
        .route("/api/v1/genes/genomes", get(list_genomes))
        .route("/api/v1/genes/genomes/:genome_id", get(get_genome))
        .route("/api/v1/genes/:gene_id", get(get_gene))
}

async fn list_genes(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<GeneListQuery>,
) -> Result<Json<GeneListResponse>, GeneApiError> {
    let query = query.validated()?;
    let response = app.genes.list_genes(&identity.user_id, query).await?;
    Ok(Json(response))
}

async fn get_gene(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(gene_id): Path<String>,
    Query(query): Query<GeneDetailQuery>,
) -> Result<Json<GeneView>, GeneApiError> {
    let response = app
        .genes
        .get_gene(&identity.user_id, query.tenant_id.as_deref(), &gene_id)
        .await?;
    Ok(Json(response))
}

async fn list_genomes(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<GenomeListQuery>,
) -> Result<Json<GenomeListResponse>, GeneApiError> {
    let query = query.validated()?;
    let response = app.genes.list_genomes(&identity.user_id, query).await?;
    Ok(Json(response))
}

async fn get_genome(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(genome_id): Path<String>,
    Query(query): Query<GeneDetailQuery>,
) -> Result<Json<GenomeView>, GeneApiError> {
    let response = app
        .genes
        .get_genome(&identity.user_id, query.tenant_id.as_deref(), &genome_id)
        .await?;
    Ok(Json(response))
}

async fn resolve_selected_tenant(
    repo: &PgGeneRepository,
    user_id: &str,
    selected_tenant_id: Option<&str>,
) -> Result<String, GeneApiError> {
    if let Some(tenant_id) = selected_tenant_id {
        return match repo
            .tenant_access_for_user(user_id, tenant_id)
            .await
            .map_err(GeneApiError::internal)?
        {
            GeneTenantAccess::Allowed => Ok(tenant_id.to_string()),
            GeneTenantAccess::Forbidden => Err(GeneApiError::forbidden("Tenant access required")),
            GeneTenantAccess::NotFound => Err(GeneApiError::not_found("Tenant not found")),
        };
    }

    repo.default_tenant_for_user(user_id)
        .await
        .map_err(GeneApiError::internal)?
        .ok_or_else(|| {
            GeneApiError::bad_request(
                "User does not belong to any tenant. Please contact administrator.",
            )
        })
}

#[derive(Debug, Clone, Deserialize)]
struct GeneListQuery {
    page: Option<i64>,
    page_size: Option<i64>,
    category: Option<String>,
    search: Option<String>,
    slugs: Option<String>,
    visibility: Option<String>,
    is_published: Option<bool>,
    exclude_installed_instance_id: Option<String>,
    tenant_id: Option<String>,
}

impl GeneListQuery {
    fn validated(self) -> Result<ValidatedGeneListQuery, GeneApiError> {
        let page = validate_range(self.page.unwrap_or(1), "page", 1, i64::MAX)?;
        let page_size = validate_range(self.page_size.unwrap_or(20), "page_size", 1, 100)?;
        let offset = page
            .checked_sub(1)
            .and_then(|value| value.checked_mul(page_size))
            .ok_or_else(|| GeneApiError::unprocessable("pagination offset is too large"))?;
        let visibility = validate_visibility(self.visibility)?;
        Ok(ValidatedGeneListQuery {
            page,
            page_size,
            offset,
            category: non_empty(self.category),
            search: non_empty(self.search),
            slugs: split_slugs(self.slugs),
            visibility,
            is_published: self.is_published,
            exclude_installed_instance_id: non_empty(self.exclude_installed_instance_id),
            tenant_id: non_empty(self.tenant_id),
        })
    }
}

#[derive(Debug, Clone, Deserialize)]
struct GeneDetailQuery {
    tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct GenomeListQuery {
    page: Option<i64>,
    page_size: Option<i64>,
    search: Option<String>,
    visibility: Option<String>,
    is_published: Option<bool>,
    tenant_id: Option<String>,
}

impl GenomeListQuery {
    fn validated(self) -> Result<ValidatedGenomeListQuery, GeneApiError> {
        let page = validate_range(self.page.unwrap_or(1), "page", 1, i64::MAX)?;
        let page_size = validate_range(self.page_size.unwrap_or(20), "page_size", 1, 100)?;
        let offset = page
            .checked_sub(1)
            .and_then(|value| value.checked_mul(page_size))
            .ok_or_else(|| GeneApiError::unprocessable("pagination offset is too large"))?;
        let visibility = validate_visibility(self.visibility)?;
        Ok(ValidatedGenomeListQuery {
            page,
            page_size,
            offset,
            search: non_empty(self.search),
            visibility,
            is_published: self.is_published,
            tenant_id: non_empty(self.tenant_id),
        })
    }
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedGeneListQuery {
    page: i64,
    page_size: i64,
    offset: i64,
    category: Option<String>,
    search: Option<String>,
    slugs: Vec<String>,
    visibility: Option<String>,
    is_published: Option<bool>,
    exclude_installed_instance_id: Option<String>,
    tenant_id: Option<String>,
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedGenomeListQuery {
    page: i64,
    page_size: i64,
    offset: i64,
    search: Option<String>,
    visibility: Option<String>,
    is_published: Option<bool>,
    tenant_id: Option<String>,
}

fn validate_range(value: i64, field: &str, min: i64, max: i64) -> Result<i64, GeneApiError> {
    if value < min || value > max {
        Err(GeneApiError::unprocessable(format!(
            "{field} must be between {min} and {max}"
        )))
    } else {
        Ok(value)
    }
}

fn validate_visibility(value: Option<String>) -> Result<Option<String>, GeneApiError> {
    let Some(value) = non_empty(value) else {
        return Ok(None);
    };
    match value.as_str() {
        "public" | "org_private" | "unlisted" => Ok(Some(value)),
        _ => Err(GeneApiError::bad_request("Invalid gene request")),
    }
}

fn split_slugs(value: Option<String>) -> Vec<String> {
    value
        .map(|value| {
            value
                .split(',')
                .filter_map(|slug| {
                    let slug = slug.trim();
                    (!slug.is_empty()).then(|| slug.to_string())
                })
                .collect()
        })
        .unwrap_or_default()
}

fn non_empty(value: Option<String>) -> Option<String> {
    value.and_then(|value| {
        let trimmed = value.trim();
        (!trimmed.is_empty()).then(|| trimmed.to_string())
    })
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct GeneView {
    id: String,
    name: String,
    slug: String,
    tenant_id: Option<String>,
    description: Option<String>,
    short_description: Option<String>,
    category: Option<String>,
    tags: Vec<String>,
    source: String,
    source_ref: Option<String>,
    icon: Option<String>,
    version: String,
    manifest: Value,
    dependencies: Vec<String>,
    synergies: Vec<String>,
    parent_gene_id: Option<String>,
    visibility: String,
    install_count: i32,
    avg_rating: f64,
    effectiveness_score: f64,
    is_featured: bool,
    review_status: String,
    is_published: bool,
    created_by: String,
    created_by_instance_id: Option<String>,
    created_at: String,
    updated_at: Option<String>,
}

impl From<GeneRecord> for GeneView {
    fn from(record: GeneRecord) -> Self {
        Self {
            id: record.id,
            name: record.name,
            slug: record.slug,
            tenant_id: record.tenant_id,
            description: record.description,
            short_description: record.short_description,
            category: record.category,
            tags: record.tags,
            source: record.source,
            source_ref: record.source_ref,
            icon: record.icon,
            version: record.version,
            manifest: record.manifest,
            dependencies: record.dependencies,
            synergies: record.synergies,
            parent_gene_id: record.parent_gene_id,
            visibility: record.visibility,
            install_count: record.install_count,
            avg_rating: record.avg_rating,
            effectiveness_score: record.effectiveness_score,
            is_featured: record.is_featured,
            review_status: record.review_status,
            is_published: record.is_published,
            created_by: record.created_by,
            created_by_instance_id: record.created_by_instance_id,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct GeneListResponse {
    genes: Vec<GeneView>,
    total: i64,
    page: i64,
    page_size: i64,
}

impl GeneListResponse {
    fn from_records(records: Vec<GeneRecord>, total: i64, page: i64, page_size: i64) -> Self {
        Self {
            genes: records.into_iter().map(GeneView::from).collect(),
            total,
            page,
            page_size,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct GenomeView {
    id: String,
    name: String,
    slug: String,
    tenant_id: Option<String>,
    description: Option<String>,
    short_description: Option<String>,
    icon: Option<String>,
    gene_slugs: Vec<String>,
    config_override: Value,
    visibility: String,
    install_count: i32,
    avg_rating: f64,
    is_featured: bool,
    is_published: bool,
    created_by: String,
    created_at: String,
    updated_at: Option<String>,
}

impl From<GenomeRecord> for GenomeView {
    fn from(record: GenomeRecord) -> Self {
        Self {
            id: record.id,
            name: record.name,
            slug: record.slug,
            tenant_id: record.tenant_id,
            description: record.description,
            short_description: record.short_description,
            icon: record.icon,
            gene_slugs: record.gene_slugs,
            config_override: record.config_override,
            visibility: record.visibility,
            install_count: record.install_count,
            avg_rating: record.avg_rating,
            is_featured: record.is_featured,
            is_published: record.is_published,
            created_by: record.created_by,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct GenomeListResponse {
    genomes: Vec<GenomeView>,
    total: i64,
    page: i64,
    page_size: i64,
}

impl GenomeListResponse {
    fn from_records(records: Vec<GenomeRecord>, total: i64, page: i64, page_size: i64) -> Self {
        Self {
            genomes: records.into_iter().map(GenomeView::from).collect(),
            total,
            page,
            page_size,
        }
    }
}

fn gene_visible_for_tenant(gene: &GeneRecord, tenant_id: &str) -> bool {
    if gene.tenant_id.as_deref() == Some(tenant_id) {
        return true;
    }
    gene.tenant_id.is_none() && gene.is_published && gene.visibility == "public"
}

fn genome_visible_for_tenant(genome: &GenomeRecord, tenant_id: &str) -> bool {
    if genome.tenant_id.as_deref() == Some(tenant_id) {
        return true;
    }
    genome.tenant_id.is_none() && genome.is_published && genome.visibility == "public"
}

fn optional_eq(actual: Option<&str>, expected: Option<&str>) -> bool {
    expected.is_none_or(|expected| actual == Some(expected))
}

fn search_matches(gene: &GeneRecord, search: Option<&str>) -> bool {
    let Some(search) = search.map(str::trim).filter(|value| !value.is_empty()) else {
        return true;
    };
    let search = search.to_lowercase();
    [
        Some(gene.name.as_str()),
        Some(gene.slug.as_str()),
        gene.description.as_deref(),
        gene.short_description.as_deref(),
    ]
    .into_iter()
    .flatten()
    .any(|value| value.to_lowercase().contains(&search))
}

fn genome_search_matches(genome: &GenomeRecord, search: Option<&str>) -> bool {
    let Some(search) = search.map(str::trim).filter(|value| !value.is_empty()) else {
        return true;
    };
    let search = search.to_lowercase();
    [
        Some(genome.name.as_str()),
        Some(genome.slug.as_str()),
        genome.description.as_deref(),
        genome.short_description.as_deref(),
    ]
    .into_iter()
    .flatten()
    .any(|value| value.to_lowercase().contains(&search))
}

fn resolve_slug_order(
    genes: Vec<GeneRecord>,
    tenant_id: &str,
    slugs: &[String],
) -> Vec<GeneRecord> {
    let normalized = split_slugs(Some(slugs.join(",")));
    let mut by_slug: Vec<(String, GeneRecord)> = Vec::new();
    for gene in genes {
        match by_slug.iter_mut().find(|(slug, _)| slug == &gene.slug) {
            Some((_, current))
                if gene.tenant_id.as_deref() == Some(tenant_id)
                    && current.tenant_id.as_deref() != Some(tenant_id) =>
            {
                *current = gene;
            }
            Some(_) => {}
            None => by_slug.push((gene.slug.clone(), gene)),
        }
    }
    normalized
        .into_iter()
        .filter_map(|slug| {
            by_slug
                .iter()
                .find(|(candidate, _)| candidate == &slug)
                .map(|(_, gene)| gene.clone())
        })
        .collect()
}

fn sort_genes(records: &mut [GeneRecord]) {
    records.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
}

fn sort_genomes(records: &mut [GenomeRecord]) {
    records.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
}

fn page<T>(records: Vec<T>, limit: i64, offset: i64) -> Vec<T> {
    records
        .into_iter()
        .skip(offset as usize)
        .take(limit as usize)
        .collect()
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

#[derive(Debug)]
pub(crate) struct GeneApiError {
    status: StatusCode,
    detail: String,
}

impl GeneApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for GeneApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn gene(
        id: &str,
        slug: &str,
        tenant_id: Option<&str>,
        created_at: DateTime<Utc>,
        is_published: bool,
        visibility: &str,
    ) -> GeneRecord {
        GeneRecord {
            id: id.to_string(),
            name: format!("Gene {slug}"),
            slug: slug.to_string(),
            tenant_id: tenant_id.map(ToString::to_string),
            description: Some("Useful automation gene".to_string()),
            short_description: Some("Automation".to_string()),
            category: Some("automation".to_string()),
            tags: vec!["automation".to_string(), "ops".to_string()],
            source: "official".to_string(),
            source_ref: Some("https://example.test/genes".to_string()),
            icon: Some("spark".to_string()),
            version: "1.0.0".to_string(),
            manifest: json!({"tools": ["plan", "run"]}),
            dependencies: vec!["base".to_string()],
            synergies: vec!["review".to_string()],
            parent_gene_id: None,
            created_by_instance_id: Some("instance-1".to_string()),
            install_count: 42,
            avg_rating: 4.5,
            effectiveness_score: 0.8,
            is_featured: true,
            review_status: "approved".to_string(),
            is_published,
            visibility: visibility.to_string(),
            created_by: "user_123".to_string(),
            created_at,
            updated_at: Some(Utc.with_ymd_and_hms(2024, 1, 15, 12, 45, 0).unwrap()),
        }
    }

    fn genome(
        id: &str,
        slug: &str,
        tenant_id: Option<&str>,
        created_at: DateTime<Utc>,
        is_published: bool,
        visibility: &str,
    ) -> GenomeRecord {
        GenomeRecord {
            id: id.to_string(),
            name: format!("Genome {slug}"),
            slug: slug.to_string(),
            tenant_id: tenant_id.map(ToString::to_string),
            description: Some("Curated automation genome".to_string()),
            short_description: Some("Curated automation".to_string()),
            icon: Some("bundle".to_string()),
            gene_slugs: vec!["code-review".to_string(), "testing".to_string()],
            config_override: json!({"testing": {"mode": "strict"}}),
            install_count: 15,
            avg_rating: 4.7,
            is_featured: false,
            is_published,
            visibility: visibility.to_string(),
            created_by: "user_123".to_string(),
            created_at,
            updated_at: Some(Utc.with_ymd_and_hms(2024, 1, 15, 12, 45, 0).unwrap()),
        }
    }

    #[test]
    fn list_query_validates_pagination_and_visibility() {
        let query = GeneListQuery {
            page: Some(2),
            page_size: Some(25),
            category: Some("automation".to_string()),
            search: None,
            slugs: Some("a, b,,a".to_string()),
            visibility: Some("public".to_string()),
            is_published: Some(true),
            exclude_installed_instance_id: None,
            tenant_id: Some("tenant-1".to_string()),
        }
        .validated()
        .expect("valid query");
        assert_eq!(query.offset, 25);
        assert_eq!(query.slugs, vec!["a", "b", "a"]);
        assert_eq!(query.visibility.as_deref(), Some("public"));

        let err = GeneListQuery {
            page: Some(1),
            page_size: Some(20),
            category: None,
            search: None,
            slugs: None,
            visibility: Some("private".to_string()),
            is_published: None,
            exclude_installed_instance_id: None,
            tenant_id: None,
        }
        .validated()
        .expect_err("invalid visibility should reject");
        assert_eq!(err.status, StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn dev_service_lists_visible_genes_and_preserves_slug_order() {
        let global = gene(
            "gene-global-review",
            "review",
            None,
            Utc.with_ymd_and_hms(2024, 1, 15, 9, 0, 0).unwrap(),
            true,
            "public",
        );
        let local_shadow = gene(
            "gene-local-review",
            "review",
            Some("tenant-1"),
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 0, 0).unwrap(),
            false,
            "org_private",
        );
        let public_ops = gene(
            "gene-global-ops",
            "ops",
            None,
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 0, 0).unwrap(),
            true,
            "public",
        );
        let hidden_global = gene(
            "gene-hidden",
            "hidden",
            None,
            Utc.with_ymd_and_hms(2024, 1, 15, 12, 0, 0).unwrap(),
            false,
            "public",
        );
        let service = DevGeneService::new(
            "tenant-1",
            vec![global, local_shadow.clone(), public_ops, hidden_global],
        );

        let list = service
            .list_genes(
                "user-1",
                ValidatedGeneListQuery {
                    page: 1,
                    page_size: 10,
                    offset: 0,
                    category: None,
                    search: None,
                    slugs: vec!["ops".to_string(), "review".to_string()],
                    visibility: None,
                    is_published: None,
                    exclude_installed_instance_id: None,
                    tenant_id: None,
                },
            )
            .await
            .expect("list genes");
        assert_eq!(list.total, 2);
        assert_eq!(
            list.genes
                .iter()
                .map(|gene| gene.id.as_str())
                .collect::<Vec<_>>(),
            vec!["gene-global-ops", "gene-local-review"]
        );

        let detail = service
            .get_gene("user-1", None, "gene-local-review")
            .await
            .expect("gene detail");
        assert_eq!(detail.id, local_shadow.id);
        assert!(service
            .get_gene("user-1", None, "gene-hidden")
            .await
            .is_err());
    }

    #[tokio::test]
    async fn dev_service_lists_and_details_visible_genomes() {
        let local = genome(
            "genome-local",
            "local-stack",
            Some("tenant-1"),
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 0, 0).unwrap(),
            false,
            "org_private",
        );
        let global = genome(
            "genome-global",
            "full-stack",
            None,
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 0, 0).unwrap(),
            true,
            "public",
        );
        let hidden = genome(
            "genome-hidden",
            "hidden-stack",
            None,
            Utc.with_ymd_and_hms(2024, 1, 15, 12, 0, 0).unwrap(),
            false,
            "public",
        );
        let service =
            DevGeneService::new_with_genomes("tenant-1", Vec::new(), vec![global, local, hidden]);

        let list = service
            .list_genomes(
                "user-1",
                ValidatedGenomeListQuery {
                    page: 1,
                    page_size: 10,
                    offset: 0,
                    search: None,
                    visibility: None,
                    is_published: None,
                    tenant_id: None,
                },
            )
            .await
            .expect("list genomes");
        assert_eq!(list.total, 2);
        assert_eq!(
            list.genomes
                .iter()
                .map(|genome| genome.id.as_str())
                .collect::<Vec<_>>(),
            vec!["genome-local", "genome-global"]
        );

        let detail = service
            .get_genome("user-1", None, "genome-global")
            .await
            .expect("genome detail");
        assert_eq!(detail.slug, "full-stack");
        assert!(service
            .get_genome("user-1", None, "genome-hidden")
            .await
            .is_err());
    }

    #[test]
    fn gene_list_response_matches_golden() {
        let response = GeneListResponse::from_records(
            vec![gene(
                "gene_550e8400",
                "code-review",
                Some("tenant_123"),
                Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
                true,
                "public",
            )],
            1,
            1,
            20,
        );
        let value = serde_json::to_value(response).expect("gene list must serialize");
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/gene_list_response.json"))
                .expect("gene list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn genome_list_response_matches_golden() {
        let response = GenomeListResponse::from_records(
            vec![genome(
                "genome_550e8400",
                "full-stack-developer",
                Some("tenant_123"),
                Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
                true,
                "public",
            )],
            1,
            1,
            20,
        );
        let value = serde_json::to_value(response).expect("genome list must serialize");
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/genome_list_response.json"))
                .expect("genome list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }
}
