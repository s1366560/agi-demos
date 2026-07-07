//! P4/P7 graph-store strangler slice.
//!
//! Rust owns authenticated graph-store engine discovery plus metadata CRUD over
//! Python-owned `graph_stores` rows. Live connection tests remain Python-owned
//! because they validate live graph backends.

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
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use tokio::sync::Mutex;
use uuid::Uuid;

use agistack_adapters_postgres::{
    BackendStoreAccessError, BackendStoreCreate, BackendStoreRecord, BackendStoreUpdate,
    PgGraphStoreRepository,
};

use crate::auth::Identity;
use crate::AppState;

const ENV_STORE_ID_PREFIX: &str = "__env_";

pub(crate) type SharedGraphStores = Arc<dyn GraphStoreCatalogService>;

#[async_trait]
pub(crate) trait GraphStoreCatalogService: Send + Sync {
    async fn resolve_selected_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, GraphStoreApiError>;

    async fn list_stores(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<GraphStoreView>, GraphStoreApiError>;

    async fn get_store(
        &self,
        tenant_id: &str,
        store_id: &str,
    ) -> Result<Option<GraphStoreView>, GraphStoreApiError>;

    async fn create_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: StoreCreateRequest,
    ) -> Result<GraphStoreView, GraphStoreApiError>;

    async fn update_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        store_id: &str,
        body: StoreUpdateRequest,
    ) -> Result<GraphStoreView, GraphStoreApiError>;

    async fn delete_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        store_id: &str,
    ) -> Result<(), GraphStoreApiError>;
}

pub(crate) struct PgGraphStoreCatalogService {
    repo: PgGraphStoreRepository,
}

impl PgGraphStoreCatalogService {
    pub(crate) fn new(repo: PgGraphStoreRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl GraphStoreCatalogService for PgGraphStoreCatalogService {
    async fn resolve_selected_tenant(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, GraphStoreApiError> {
        self.repo
            .resolve_selected_tenant(user_id, tenant_id)
            .await
            .map_err(GraphStoreApiError::internal)?
            .map_err(GraphStoreApiError::from_access)
    }

    async fn list_stores(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<GraphStoreView>, GraphStoreApiError> {
        self.repo
            .list_stores(tenant_id, limit, offset)
            .await
            .map_err(GraphStoreApiError::internal)
            .map(|records| {
                records
                    .into_iter()
                    .map(GraphStoreView::from_record)
                    .collect()
            })
    }

    async fn get_store(
        &self,
        tenant_id: &str,
        store_id: &str,
    ) -> Result<Option<GraphStoreView>, GraphStoreApiError> {
        self.repo
            .get_store(tenant_id, store_id)
            .await
            .map_err(GraphStoreApiError::internal)
            .map(|record| record.map(GraphStoreView::from_record))
    }

    async fn create_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: StoreCreateRequest,
    ) -> Result<GraphStoreView, GraphStoreApiError> {
        validate_store_name(&body.name)?;
        ensure_object(&body.connection_config, "connection_config")?;
        ensure_object(&body.index_config, "index_config")?;
        let engine_type = normalize_graph_engine_type(&body.engine_type)?;
        let tenant_id = self
            .repo
            .resolve_selected_tenant_for_admin(user_id, tenant_id)
            .await
            .map_err(GraphStoreApiError::internal)?
            .map_err(GraphStoreApiError::from_access)?;
        if self
            .repo
            .find_by_name(&tenant_id, &body.name)
            .await
            .map_err(GraphStoreApiError::internal)?
            .is_some()
        {
            return Err(GraphStoreApiError::conflict(format!(
                "A graph store named {} already exists in this tenant",
                python_repr_str(&body.name)
            )));
        }
        self.repo
            .create_store(BackendStoreCreate {
                tenant_id,
                name: body.name,
                engine_type,
                connection_config_json: body.connection_config,
                index_config_json: body.index_config,
                created_by: user_id.to_string(),
            })
            .await
            .map(GraphStoreView::from_record)
            .map_err(GraphStoreApiError::internal)
    }

    async fn update_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        store_id: &str,
        body: StoreUpdateRequest,
    ) -> Result<GraphStoreView, GraphStoreApiError> {
        if let Some(name) = body.name.as_deref() {
            validate_store_name(name)?;
        }
        if let Some(config) = body.connection_config.as_ref() {
            ensure_object(config, "connection_config")?;
        }
        if let Some(config) = body.index_config.as_ref() {
            ensure_object(config, "index_config")?;
        }
        let tenant_id = self
            .repo
            .resolve_selected_tenant_for_admin(user_id, tenant_id)
            .await
            .map_err(GraphStoreApiError::internal)?
            .map_err(GraphStoreApiError::from_access)?;
        if store_id.starts_with(ENV_STORE_ID_PREFIX) {
            return Err(GraphStoreApiError::bad_request(
                "Environment stores are read-only",
            ));
        }
        let current = self
            .repo
            .get_store(&tenant_id, store_id)
            .await
            .map_err(GraphStoreApiError::internal)?
            .ok_or_else(|| GraphStoreApiError::not_found("Graph store not found"))?;
        if let Some(name) = body.name.as_deref().filter(|name| *name != current.name) {
            if self
                .repo
                .find_by_name(&tenant_id, name)
                .await
                .map_err(GraphStoreApiError::internal)?
                .filter(|store| store.id != store_id)
                .is_some()
            {
                return Err(GraphStoreApiError::conflict(format!(
                    "A graph store named {} already exists in this tenant",
                    python_repr_str(name)
                )));
            }
        }
        if let Some(config) = body.connection_config.as_ref() {
            validate_required_fields(&current.engine_type, config, GRAPH_REQUIRED_FIELDS)?;
        }
        self.repo
            .update_store(
                &tenant_id,
                store_id,
                BackendStoreUpdate {
                    name: body.name,
                    connection_config_json: body.connection_config,
                    index_config_json: body.index_config,
                },
            )
            .await
            .map_err(GraphStoreApiError::internal)?
            .map(GraphStoreView::from_record)
            .ok_or_else(|| GraphStoreApiError::not_found("Graph store not found"))
    }

    async fn delete_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        store_id: &str,
    ) -> Result<(), GraphStoreApiError> {
        let tenant_id = self
            .repo
            .resolve_selected_tenant_for_admin(user_id, tenant_id)
            .await
            .map_err(GraphStoreApiError::internal)?
            .map_err(GraphStoreApiError::from_access)?;
        if store_id.starts_with(ENV_STORE_ID_PREFIX) {
            return Err(GraphStoreApiError::bad_request(
                "Environment stores are read-only",
            ));
        }
        self.repo
            .get_store(&tenant_id, store_id)
            .await
            .map_err(GraphStoreApiError::internal)?
            .ok_or_else(|| GraphStoreApiError::not_found("Graph store not found"))?;
        let bound = self
            .repo
            .count_projects_bound(store_id)
            .await
            .map_err(GraphStoreApiError::internal)?;
        if bound > 0 {
            return Err(GraphStoreApiError::conflict(format!(
                "Graph store {} still has {bound} project(s) bound to it; unbind or delete them before removing the store",
                python_repr_str(store_id)
            )));
        }
        if self
            .repo
            .soft_delete(&tenant_id, store_id)
            .await
            .map_err(GraphStoreApiError::internal)?
        {
            Ok(())
        } else {
            Err(GraphStoreApiError::not_found("Graph store not found"))
        }
    }
}

pub(crate) struct DevGraphStoreCatalogService {
    tenant_id: String,
    stores: Mutex<Vec<GraphStoreView>>,
}

impl DevGraphStoreCatalogService {
    pub(crate) fn new(tenant_id: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            stores: Mutex::new(Vec::new()),
        }
    }

    #[cfg(test)]
    fn with_stores(tenant_id: impl Into<String>, stores: Vec<GraphStoreView>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            stores: Mutex::new(stores),
        }
    }
}

#[async_trait]
impl GraphStoreCatalogService for DevGraphStoreCatalogService {
    async fn resolve_selected_tenant(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<String, GraphStoreApiError> {
        Ok(tenant_id
            .filter(|value| !value.is_empty())
            .unwrap_or(&self.tenant_id)
            .to_string())
    }

    async fn list_stores(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<GraphStoreView>, GraphStoreApiError> {
        let start = usize::try_from(offset).unwrap_or(usize::MAX);
        let count = usize::try_from(limit).unwrap_or(usize::MAX);
        Ok(self
            .stores
            .lock()
            .await
            .iter()
            .filter(|store| store.tenant_id == tenant_id)
            .skip(start)
            .take(count)
            .cloned()
            .collect())
    }

    async fn get_store(
        &self,
        tenant_id: &str,
        store_id: &str,
    ) -> Result<Option<GraphStoreView>, GraphStoreApiError> {
        Ok(self
            .stores
            .lock()
            .await
            .iter()
            .find(|store| store.tenant_id == tenant_id && store.id == store_id)
            .cloned())
    }

    async fn create_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        body: StoreCreateRequest,
    ) -> Result<GraphStoreView, GraphStoreApiError> {
        validate_store_name(&body.name)?;
        ensure_object(&body.connection_config, "connection_config")?;
        ensure_object(&body.index_config, "index_config")?;
        let engine_type = normalize_graph_engine_type(&body.engine_type)?;
        let tenant_id = self.resolve_selected_tenant(user_id, tenant_id).await?;
        let mut stores = self.stores.lock().await;
        if stores
            .iter()
            .any(|store| store.tenant_id == tenant_id && store.name == body.name)
        {
            return Err(GraphStoreApiError::conflict(format!(
                "A graph store named {} already exists in this tenant",
                python_repr_str(&body.name)
            )));
        }
        let now = iso8601(Utc::now());
        let view = GraphStoreView {
            id: Uuid::new_v4().to_string(),
            tenant_id,
            name: body.name,
            engine_type,
            status: "disconnected".to_string(),
            health_status: None,
            detected_version: None,
            connection_config: mask_sensitive_connection_config(
                body.connection_config,
                GRAPH_SENSITIVE_FIELDS,
            ),
            index_config: body.index_config,
            created_at: Some(now),
            updated_at: None,
            source: "user".to_string(),
            readonly: false,
        };
        stores.push(view.clone());
        Ok(view)
    }

    async fn update_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        store_id: &str,
        body: StoreUpdateRequest,
    ) -> Result<GraphStoreView, GraphStoreApiError> {
        if let Some(name) = body.name.as_deref() {
            validate_store_name(name)?;
        }
        if let Some(config) = body.connection_config.as_ref() {
            ensure_object(config, "connection_config")?;
        }
        if let Some(config) = body.index_config.as_ref() {
            ensure_object(config, "index_config")?;
        }
        let tenant_id = self.resolve_selected_tenant(user_id, tenant_id).await?;
        if store_id.starts_with(ENV_STORE_ID_PREFIX) {
            return Err(GraphStoreApiError::bad_request(
                "Environment stores are read-only",
            ));
        }
        let mut stores = self.stores.lock().await;
        if let Some(name) = body.name.as_deref() {
            if stores.iter().any(|store| {
                store.tenant_id == tenant_id && store.id != store_id && store.name == name
            }) {
                return Err(GraphStoreApiError::conflict(format!(
                    "A graph store named {} already exists in this tenant",
                    python_repr_str(name)
                )));
            }
        }
        let store = stores
            .iter_mut()
            .find(|store| store.tenant_id == tenant_id && store.id == store_id)
            .ok_or_else(|| GraphStoreApiError::not_found("Graph store not found"))?;
        if let Some(config) = body.connection_config.as_ref() {
            validate_required_fields(&store.engine_type, config, GRAPH_REQUIRED_FIELDS)?;
        }
        if let Some(name) = body.name {
            store.name = name;
        }
        if let Some(config) = body.connection_config {
            store.connection_config =
                mask_sensitive_connection_config(config, GRAPH_SENSITIVE_FIELDS);
        }
        if let Some(config) = body.index_config {
            store.index_config = config;
        }
        store.updated_at = Some(iso8601(Utc::now()));
        Ok(store.clone())
    }

    async fn delete_store(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        store_id: &str,
    ) -> Result<(), GraphStoreApiError> {
        let tenant_id = self.resolve_selected_tenant(user_id, tenant_id).await?;
        if store_id.starts_with(ENV_STORE_ID_PREFIX) {
            return Err(GraphStoreApiError::bad_request(
                "Environment stores are read-only",
            ));
        }
        let mut stores = self.stores.lock().await;
        let before = stores.len();
        stores.retain(|store| !(store.tenant_id == tenant_id && store.id == store_id));
        if stores.len() == before {
            Err(GraphStoreApiError::not_found("Graph store not found"))
        } else {
            Ok(())
        }
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/graph-stores/types", get(list_store_types))
        .route("/api/v1/graph-stores", get(list_stores).post(create_store))
        .route("/api/v1/graph-stores/", get(list_stores).post(create_store))
        .route(
            "/api/v1/graph-stores/:store_id",
            get(get_store).put(update_store).delete(delete_store),
        )
}

async fn list_store_types() -> Json<GraphStoreTypesResponse> {
    Json(graph_store_types_response())
}

async fn list_stores(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<StoreListQuery>,
) -> Result<Json<GraphStoreListResponse>, GraphStoreApiError> {
    let limit = query.validated_limit()?;
    let offset = query.validated_offset()?;
    let tenant_id = app
        .graph_stores
        .resolve_selected_tenant(&identity.user_id, query.tenant_id.as_deref())
        .await?;
    let mut data = vec![env_default_store_view(&tenant_id)];
    data.extend(
        app.graph_stores
            .list_stores(&tenant_id, limit, offset)
            .await?,
    );
    Ok(Json(GraphStoreListResponse {
        success: true,
        data,
    }))
}

async fn get_store(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(store_id): Path<String>,
    Query(query): Query<StoreTenantQuery>,
) -> Result<Json<GraphStoreResponse>, GraphStoreApiError> {
    let tenant_id = app
        .graph_stores
        .resolve_selected_tenant(&identity.user_id, query.tenant_id.as_deref())
        .await?;
    if store_id.starts_with(ENV_STORE_ID_PREFIX) {
        return Ok(Json(GraphStoreResponse {
            success: true,
            data: env_default_store_view(&tenant_id),
        }));
    }
    let data = app
        .graph_stores
        .get_store(&tenant_id, &store_id)
        .await?
        .ok_or_else(|| GraphStoreApiError::not_found("Graph store not found"))?;
    Ok(Json(GraphStoreResponse {
        success: true,
        data,
    }))
}

async fn create_store(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<StoreTenantQuery>,
    Json(body): Json<StoreCreateRequest>,
) -> Result<(StatusCode, Json<GraphStoreResponse>), GraphStoreApiError> {
    let data = app
        .graph_stores
        .create_store(&identity.user_id, query.tenant_id.as_deref(), body)
        .await?;
    Ok((
        StatusCode::CREATED,
        Json(GraphStoreResponse {
            success: true,
            data,
        }),
    ))
}

async fn update_store(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(store_id): Path<String>,
    Query(query): Query<StoreTenantQuery>,
    Json(body): Json<StoreUpdateRequest>,
) -> Result<Json<GraphStoreResponse>, GraphStoreApiError> {
    let data = app
        .graph_stores
        .update_store(
            &identity.user_id,
            query.tenant_id.as_deref(),
            &store_id,
            body,
        )
        .await?;
    Ok(Json(GraphStoreResponse {
        success: true,
        data,
    }))
}

async fn delete_store(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(store_id): Path<String>,
    Query(query): Query<StoreTenantQuery>,
) -> Result<StatusCode, GraphStoreApiError> {
    app.graph_stores
        .delete_store(&identity.user_id, query.tenant_id.as_deref(), &store_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

fn graph_store_types_response() -> GraphStoreTypesResponse {
    GraphStoreTypesResponse {
        success: true,
        data: vec![
            GraphStoreType {
                engine_type: "neo4j",
                display_name: "Neo4j",
                connection_fields: vec![
                    GraphStoreField::required("uri", "string"),
                    GraphStoreField::optional("user", "string"),
                    GraphStoreField::sensitive("password", "string"),
                ],
                index_fields: Vec::new(),
                status: None,
            },
            GraphStoreType {
                engine_type: "arcadedb",
                display_name: "ArcadeDB",
                connection_fields: vec![
                    GraphStoreField::required("uri", "string"),
                    GraphStoreField::with_default("database", "string", "memstack"),
                    GraphStoreField::optional("user", "string"),
                    GraphStoreField::sensitive("password", "string"),
                    GraphStoreField::optional("http_base_url", "string"),
                ],
                index_fields: Vec::new(),
                status: None,
            },
            GraphStoreType {
                engine_type: "age",
                display_name: "Apache AGE (PostgreSQL)",
                connection_fields: vec![GraphStoreField::sensitive_required("dsn", "string")],
                index_fields: Vec::new(),
                status: Some("planned"),
            },
        ],
    }
}

fn env_default_store_view(tenant_id: &str) -> GraphStoreView {
    GraphStoreView {
        id: "__env_neo4j__".to_string(),
        tenant_id: tenant_id.to_string(),
        name: "neo4j (env)".to_string(),
        engine_type: "neo4j".to_string(),
        status: "connected".to_string(),
        health_status: None,
        detected_version: None,
        connection_config: json!({ "uri": "env" }),
        index_config: json!({}),
        created_at: None,
        updated_at: None,
        source: "env".to_string(),
        readonly: true,
    }
}

#[derive(Debug, Deserialize)]
struct StoreTenantQuery {
    tenant_id: Option<String>,
}

fn default_graph_engine_type() -> String {
    "neo4j".to_string()
}

fn empty_json_object() -> Value {
    json!({})
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct StoreCreateRequest {
    name: String,
    #[serde(default = "default_graph_engine_type")]
    engine_type: String,
    #[serde(default = "empty_json_object")]
    connection_config: Value,
    #[serde(default = "empty_json_object")]
    index_config: Value,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct StoreUpdateRequest {
    name: Option<String>,
    connection_config: Option<Value>,
    index_config: Option<Value>,
}

#[derive(Debug, Deserialize)]
struct StoreListQuery {
    tenant_id: Option<String>,
    limit: Option<i64>,
    offset: Option<i64>,
}

impl StoreListQuery {
    fn validated_limit(&self) -> Result<i64, GraphStoreApiError> {
        let limit = self.limit.unwrap_or(50);
        if (1..=100).contains(&limit) {
            Ok(limit)
        } else {
            Err(GraphStoreApiError::unprocessable(
                "limit must be between 1 and 100",
            ))
        }
    }

    fn validated_offset(&self) -> Result<i64, GraphStoreApiError> {
        let offset = self.offset.unwrap_or(0);
        if offset >= 0 {
            Ok(offset)
        } else {
            Err(GraphStoreApiError::unprocessable(
                "offset must be greater than or equal to 0",
            ))
        }
    }
}

#[derive(Debug)]
pub(crate) struct GraphStoreApiError {
    status: StatusCode,
    detail: String,
}

impl GraphStoreApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn conflict(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::CONFLICT, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }

    fn from_access(error: BackendStoreAccessError) -> Self {
        match error {
            BackendStoreAccessError::TenantNotFound => {
                Self::new(StatusCode::NOT_FOUND, "Tenant not found")
            }
            BackendStoreAccessError::TenantAccessRequired => {
                Self::new(StatusCode::FORBIDDEN, "Tenant access required")
            }
            BackendStoreAccessError::AdminAccessRequired => {
                Self::new(StatusCode::FORBIDDEN, "Admin access required")
            }
            BackendStoreAccessError::UserHasNoTenant => Self::new(
                StatusCode::BAD_REQUEST,
                "User does not belong to any tenant. Please contact administrator.",
            ),
        }
    }
}

impl IntoResponse for GraphStoreApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct GraphStoreListResponse {
    success: bool,
    data: Vec<GraphStoreView>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct GraphStoreResponse {
    success: bool,
    data: GraphStoreView,
}

const GRAPH_VALID_ENGINE_TYPES: &[&str] = &["neo4j", "arcadedb", "age"];
const GRAPH_REQUIRED_FIELDS: &[(&str, &[&str])] = &[
    ("neo4j", &["uri"]),
    ("arcadedb", &["uri"]),
    ("age", &["dsn"]),
];
const GRAPH_SENSITIVE_FIELDS: &[&str] = &["password", "api_key", "token", "secret"];

fn validate_store_name(name: &str) -> Result<(), GraphStoreApiError> {
    if name.is_empty() {
        return Err(GraphStoreApiError::unprocessable(
            "name must have at least 1 character",
        ));
    }
    if name.chars().count() > 255 {
        return Err(GraphStoreApiError::unprocessable(
            "name must have at most 255 characters",
        ));
    }
    Ok(())
}

fn ensure_object(value: &Value, field: &str) -> Result<(), GraphStoreApiError> {
    if value.is_object() {
        Ok(())
    } else {
        Err(GraphStoreApiError::unprocessable(format!(
            "{field} must be an object"
        )))
    }
}

fn normalize_graph_engine_type(engine_type: &str) -> Result<String, GraphStoreApiError> {
    let engine_type = if engine_type.is_empty() {
        "neo4j".to_string()
    } else {
        engine_type.to_lowercase()
    };
    if GRAPH_VALID_ENGINE_TYPES.contains(&engine_type.as_str()) {
        Ok(engine_type)
    } else {
        Err(GraphStoreApiError::bad_request(format!(
            "Unsupported engine type: {} (valid: {})",
            python_repr_str(&engine_type),
            python_string_list(GRAPH_VALID_ENGINE_TYPES)
        )))
    }
}

fn validate_required_fields(
    engine_type: &str,
    config: &Value,
    required_fields: &[(&str, &[&str])],
) -> Result<(), GraphStoreApiError> {
    let required = required_fields
        .iter()
        .find_map(|(candidate, fields)| (*candidate == engine_type).then_some(*fields))
        .unwrap_or(&[]);
    let missing = required
        .iter()
        .copied()
        .filter(|field| !json_field_truthy(config.get(*field)))
        .collect::<Vec<_>>();
    if missing.is_empty() {
        Ok(())
    } else {
        Err(GraphStoreApiError::bad_request(format!(
            "Missing required connection fields for {}: {}",
            python_repr_str(engine_type),
            python_string_list(&missing)
        )))
    }
}

fn json_field_truthy(value: Option<&Value>) -> bool {
    value.map(json_truthy).unwrap_or(false)
}

fn python_string_list(items: &[&str]) -> String {
    let mut out = String::from("[");
    for (index, item) in items.iter().enumerate() {
        if index > 0 {
            out.push_str(", ");
        }
        out.push('\'');
        out.push_str(item);
        out.push('\'');
    }
    out.push(']');
    out
}

fn python_repr_str(value: &str) -> String {
    let escaped = value.replace('\\', "\\\\").replace('\'', "\\'");
    format!("'{escaped}'")
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct GraphStoreView {
    id: String,
    tenant_id: String,
    name: String,
    engine_type: String,
    status: String,
    health_status: Option<String>,
    detected_version: Option<String>,
    connection_config: Value,
    index_config: Value,
    created_at: Option<String>,
    updated_at: Option<String>,
    source: String,
    readonly: bool,
}

impl GraphStoreView {
    fn from_record(record: BackendStoreRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            name: record.name,
            engine_type: record.engine_type,
            status: record.status,
            health_status: record.health_status,
            detected_version: record.detected_version,
            connection_config: mask_sensitive_connection_config(
                record.connection_config_json,
                GRAPH_SENSITIVE_FIELDS,
            ),
            index_config: record.index_config_json,
            created_at: Some(iso8601(record.created_at)),
            updated_at: record.updated_at.map(iso8601),
            source: "user".to_string(),
            readonly: false,
        }
    }
}

fn mask_sensitive_connection_config(config: Value, sensitive: &[&str]) -> Value {
    let Value::Object(values) = config else {
        return config;
    };
    let mut out = Map::with_capacity(values.len());
    for (key, value) in values {
        if sensitive
            .iter()
            .any(|candidate| key.eq_ignore_ascii_case(candidate))
            && json_truthy(&value)
        {
            out.insert(key, Value::String("***".to_string()));
        } else {
            out.insert(key, value);
        }
    }
    Value::Object(out)
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().map(|number| number != 0.0).unwrap_or(true),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, false)
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct GraphStoreTypesResponse {
    success: bool,
    data: Vec<GraphStoreType>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct GraphStoreType {
    #[serde(rename = "type")]
    engine_type: &'static str,
    display_name: &'static str,
    connection_fields: Vec<GraphStoreField>,
    index_fields: Vec<GraphStoreField>,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<&'static str>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
struct GraphStoreField {
    name: &'static str,
    #[serde(rename = "type")]
    field_type: &'static str,
    required: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    sensitive: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    default: Option<&'static str>,
}

impl GraphStoreField {
    fn required(name: &'static str, field_type: &'static str) -> Self {
        Self {
            name,
            field_type,
            required: true,
            sensitive: None,
            default: None,
        }
    }

    fn optional(name: &'static str, field_type: &'static str) -> Self {
        Self {
            name,
            field_type,
            required: false,
            sensitive: None,
            default: None,
        }
    }

    fn sensitive(name: &'static str, field_type: &'static str) -> Self {
        Self {
            name,
            field_type,
            required: false,
            sensitive: Some(true),
            default: None,
        }
    }

    fn sensitive_required(name: &'static str, field_type: &'static str) -> Self {
        Self {
            name,
            field_type,
            required: true,
            sensitive: Some(true),
            default: None,
        }
    }

    fn with_default(name: &'static str, field_type: &'static str, default: &'static str) -> Self {
        Self {
            name,
            field_type,
            required: false,
            sensitive: None,
            default: Some(default),
        }
    }
}

#[cfg(test)]
mod tests {
    use chrono::TimeZone;
    use serde_json::Value;

    use super::*;

    #[tokio::test]
    async fn graph_store_types_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/graph_store_types_response.json"
        ))
        .expect("graph store types golden must be valid JSON");

        let value = serde_json::to_value(list_store_types().await.0)
            .expect("graph store types response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn graph_store_types_are_unique() {
        let response = graph_store_types_response();
        let mut names = response
            .data
            .iter()
            .map(|store| store.engine_type)
            .collect::<Vec<_>>();
        names.sort_unstable();
        names.dedup();
        assert_eq!(names.len(), response.data.len());
    }

    #[tokio::test]
    async fn graph_store_list_response_matches_python_shape() {
        let service = DevGraphStoreCatalogService::with_stores(
            "tenant-1",
            vec![sample_user_store_view("tenant-1")],
        );
        let tenant_id = service
            .resolve_selected_tenant("user-1", Some("tenant-1"))
            .await
            .unwrap();
        let mut data = vec![env_default_store_view(&tenant_id)];
        data.extend(service.list_stores(&tenant_id, 50, 0).await.unwrap());
        let response = GraphStoreListResponse {
            success: true,
            data,
        };

        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/graph_store_list_response.json"
        ))
        .expect("graph store list golden must be valid JSON");
        let value = serde_json::to_value(response).expect("graph store list serializes");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn graph_store_detail_response_matches_python_shape() {
        let response = GraphStoreResponse {
            success: true,
            data: sample_user_store_view("tenant-1"),
        };
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/graph_store_detail_response.json"
        ))
        .expect("graph store detail golden must be valid JSON");
        let value = serde_json::to_value(response).expect("graph store detail serializes");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn graph_store_create_response_matches_python_shape() {
        let response = GraphStoreResponse {
            success: true,
            data: sample_user_store_view("tenant-1"),
        };
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/graph_store_create_response.json"
        ))
        .expect("graph store create golden must be valid JSON");
        let value = serde_json::to_value(response).expect("graph store create serializes");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn graph_store_update_response_matches_python_shape() {
        let response = GraphStoreResponse {
            success: true,
            data: sample_user_store_view("tenant-1"),
        };
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/graph_store_update_response.json"
        ))
        .expect("graph store update golden must be valid JSON");
        let value = serde_json::to_value(response).expect("graph store update serializes");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn graph_store_view_masks_only_truthy_top_level_sensitive_fields() {
        let record = BackendStoreRecord {
            id: "graph-1".to_string(),
            tenant_id: "tenant-1".to_string(),
            name: "Primary".to_string(),
            engine_type: "neo4j".to_string(),
            connection_config_json: json!({
                "uri": "bolt://neo4j.example:7687",
                "password": "secret",
                "token": "",
                "nested": { "api_key": "left-as-python-does" }
            }),
            index_config_json: json!({}),
            status: "connected".to_string(),
            health_status: None,
            detected_version: None,
            created_at: Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap(),
            updated_at: None,
        };
        let view = GraphStoreView::from_record(record);
        assert_eq!(view.connection_config["password"], "***");
        assert_eq!(view.connection_config["token"], "");
        assert_eq!(
            view.connection_config["nested"]["api_key"],
            "left-as-python-does"
        );
    }

    #[tokio::test]
    async fn graph_store_dev_write_contracts_match_python_errors() {
        let service = DevGraphStoreCatalogService::new("tenant-1");
        let create = StoreCreateRequest {
            name: "Primary graph".to_string(),
            engine_type: "Neo4J".to_string(),
            connection_config: json!({
                "uri": "bolt://neo4j.example:7687",
                "password": "secret"
            }),
            index_config: json!({ "database": "neo4j" }),
        };
        let created = service
            .create_store("user-1", Some("tenant-1"), create.clone())
            .await
            .expect("create succeeds");
        assert_eq!(created.engine_type, "neo4j");
        assert_eq!(created.status, "disconnected");
        assert_eq!(created.connection_config["password"], "***");

        let duplicate = service
            .create_store("user-1", Some("tenant-1"), create)
            .await
            .expect_err("duplicate name rejected");
        assert_eq!(duplicate.status, StatusCode::CONFLICT);
        assert_eq!(
            duplicate.detail,
            "A graph store named 'Primary graph' already exists in this tenant"
        );

        let missing_uri = service
            .update_store(
                "user-1",
                Some("tenant-1"),
                &created.id,
                StoreUpdateRequest {
                    name: None,
                    connection_config: Some(json!({ "password": "secret" })),
                    index_config: None,
                },
            )
            .await
            .expect_err("missing required field rejected on update");
        assert_eq!(missing_uri.status, StatusCode::BAD_REQUEST);
        assert_eq!(
            missing_uri.detail,
            "Missing required connection fields for 'neo4j': ['uri']"
        );

        let updated = service
            .update_store(
                "user-1",
                Some("tenant-1"),
                &created.id,
                StoreUpdateRequest {
                    name: Some("Renamed graph".to_string()),
                    connection_config: Some(json!({
                        "uri": "bolt://neo4j-2.example:7687",
                        "token": "t"
                    })),
                    index_config: Some(json!({ "database": "neo4j2" })),
                },
            )
            .await
            .expect("update succeeds");
        assert_eq!(updated.name, "Renamed graph");
        assert_eq!(updated.connection_config["token"], "***");
        assert!(updated.updated_at.is_some());

        let env_delete = service
            .delete_store("user-1", Some("tenant-1"), "__env_neo4j__")
            .await
            .expect_err("env store is read-only");
        assert_eq!(env_delete.status, StatusCode::BAD_REQUEST);

        service
            .delete_store("user-1", Some("tenant-1"), &created.id)
            .await
            .expect("delete succeeds");
        let missing = service
            .delete_store("user-1", Some("tenant-1"), &created.id)
            .await
            .expect_err("second delete is not found");
        assert_eq!(missing.status, StatusCode::NOT_FOUND);
    }

    #[test]
    fn router_builds() {
        let _ = router();
    }

    fn sample_user_store_view(tenant_id: &str) -> GraphStoreView {
        GraphStoreView {
            id: "graph-store-1".to_string(),
            tenant_id: tenant_id.to_string(),
            name: "Primary graph".to_string(),
            engine_type: "neo4j".to_string(),
            status: "connected".to_string(),
            health_status: Some("healthy".to_string()),
            detected_version: Some("5.26".to_string()),
            connection_config: json!({
                "uri": "bolt://neo4j.example:7687",
                "user": "neo4j",
                "password": "***"
            }),
            index_config: json!({ "database": "neo4j" }),
            created_at: Some("2026-01-02T03:04:05+00:00".to_string()),
            updated_at: Some("2026-01-03T04:05:06+00:00".to_string()),
            source: "user".to_string(),
            readonly: false,
        }
    }
}
