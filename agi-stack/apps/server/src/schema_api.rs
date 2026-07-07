//! P7 project schema strangler slice.
//!
//! Rust owns project-scoped schema collection reads plus schema create/update/
//! delete over the Python-owned schema tables.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{delete, get, put},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

use agistack_adapters_postgres::{
    CreateSchemaEdgeMap, CreateSchemaType, PgSchemaRepository, SchemaEdgeMapRecord,
    SchemaTypeRecord, UpdateSchemaType,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedProjectSchema = Arc<dyn ProjectSchemaService>;

#[async_trait]
pub(crate) trait ProjectSchemaService: Send + Sync {
    async fn list_entity_types(&self, project_id: &str)
        -> Result<Vec<SchemaTypeView>, SchemaError>;
    async fn list_edge_types(&self, project_id: &str) -> Result<Vec<SchemaTypeView>, SchemaError>;
    async fn list_edge_maps(&self, project_id: &str)
        -> Result<Vec<SchemaEdgeMapView>, SchemaError>;

    async fn create_entity_type(
        &self,
        user_id: &str,
        project_id: &str,
        request: SchemaTypeCreateRequest,
    ) -> Result<SchemaTypeView, SchemaError>;

    async fn update_entity_type(
        &self,
        user_id: &str,
        project_id: &str,
        entity_id: &str,
        request: SchemaTypeUpdateRequest,
    ) -> Result<SchemaTypeView, SchemaError>;

    async fn delete_entity_type(
        &self,
        user_id: &str,
        project_id: &str,
        entity_id: &str,
    ) -> Result<(), SchemaError>;

    async fn create_edge_type(
        &self,
        user_id: &str,
        project_id: &str,
        request: SchemaTypeCreateRequest,
    ) -> Result<SchemaTypeView, SchemaError>;

    async fn update_edge_type(
        &self,
        user_id: &str,
        project_id: &str,
        edge_id: &str,
        request: SchemaTypeUpdateRequest,
    ) -> Result<SchemaTypeView, SchemaError>;

    async fn delete_edge_type(
        &self,
        user_id: &str,
        project_id: &str,
        edge_id: &str,
    ) -> Result<(), SchemaError>;

    async fn create_edge_map(
        &self,
        user_id: &str,
        project_id: &str,
        request: SchemaEdgeMapCreateRequest,
    ) -> Result<SchemaEdgeMapView, SchemaError>;

    async fn delete_edge_map(
        &self,
        user_id: &str,
        project_id: &str,
        map_id: &str,
    ) -> Result<(), SchemaError>;
}

pub(crate) struct PgProjectSchemaService {
    repo: PgSchemaRepository,
}

impl PgProjectSchemaService {
    pub(crate) fn new(repo: PgSchemaRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl ProjectSchemaService for PgProjectSchemaService {
    async fn list_entity_types(
        &self,
        project_id: &str,
    ) -> Result<Vec<SchemaTypeView>, SchemaError> {
        let records = self
            .repo
            .list_entity_types(project_id)
            .await
            .map_err(SchemaError::internal)?;
        Ok(records.into_iter().map(SchemaTypeView::from).collect())
    }

    async fn list_edge_types(&self, project_id: &str) -> Result<Vec<SchemaTypeView>, SchemaError> {
        let records = self
            .repo
            .list_edge_types(project_id)
            .await
            .map_err(SchemaError::internal)?;
        Ok(records.into_iter().map(SchemaTypeView::from).collect())
    }

    async fn list_edge_maps(
        &self,
        project_id: &str,
    ) -> Result<Vec<SchemaEdgeMapView>, SchemaError> {
        let records = self
            .repo
            .list_edge_maps(project_id)
            .await
            .map_err(SchemaError::internal)?;
        Ok(records.into_iter().map(SchemaEdgeMapView::from).collect())
    }

    async fn create_entity_type(
        &self,
        user_id: &str,
        project_id: &str,
        request: SchemaTypeCreateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        if self
            .repo
            .entity_type_name_exists(project_id, &request.name)
            .await
            .map_err(SchemaError::internal)?
        {
            return Err(SchemaError::bad_request(
                "Entity type with this name already exists",
            ));
        }
        let id = Uuid::new_v4().to_string();
        self.repo
            .create_entity_type(CreateSchemaType {
                id: &id,
                project_id,
                name: &request.name,
                description: request.description.as_deref(),
                schema_json: &request.schema_json,
            })
            .await
            .map_err(SchemaError::internal)
            .map(SchemaTypeView::from)
    }

    async fn update_entity_type(
        &self,
        user_id: &str,
        project_id: &str,
        entity_id: &str,
        request: SchemaTypeUpdateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        self.repo
            .update_entity_type(
                project_id,
                entity_id,
                UpdateSchemaType {
                    description: request.description.as_deref(),
                    schema_json: request.schema_json.as_ref(),
                },
            )
            .await
            .map_err(SchemaError::internal)?
            .map(SchemaTypeView::from)
            .ok_or_else(|| SchemaError::not_found("Entity type not found"))
    }

    async fn delete_entity_type(
        &self,
        user_id: &str,
        project_id: &str,
        entity_id: &str,
    ) -> Result<(), SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        if self
            .repo
            .delete_entity_type(project_id, entity_id)
            .await
            .map_err(SchemaError::internal)?
        {
            Ok(())
        } else {
            Err(SchemaError::not_found("Entity type not found"))
        }
    }

    async fn create_edge_type(
        &self,
        user_id: &str,
        project_id: &str,
        request: SchemaTypeCreateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        if self
            .repo
            .edge_type_name_exists(project_id, &request.name)
            .await
            .map_err(SchemaError::internal)?
        {
            return Err(SchemaError::bad_request(
                "Edge type with this name already exists",
            ));
        }
        let id = Uuid::new_v4().to_string();
        self.repo
            .create_edge_type(CreateSchemaType {
                id: &id,
                project_id,
                name: &request.name,
                description: request.description.as_deref(),
                schema_json: &request.schema_json,
            })
            .await
            .map_err(SchemaError::internal)
            .map(SchemaTypeView::from)
    }

    async fn update_edge_type(
        &self,
        user_id: &str,
        project_id: &str,
        edge_id: &str,
        request: SchemaTypeUpdateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        self.repo
            .update_edge_type(
                project_id,
                edge_id,
                UpdateSchemaType {
                    description: request.description.as_deref(),
                    schema_json: request.schema_json.as_ref(),
                },
            )
            .await
            .map_err(SchemaError::internal)?
            .map(SchemaTypeView::from)
            .ok_or_else(|| SchemaError::not_found("Edge type not found"))
    }

    async fn delete_edge_type(
        &self,
        user_id: &str,
        project_id: &str,
        edge_id: &str,
    ) -> Result<(), SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        if self
            .repo
            .delete_edge_type(project_id, edge_id)
            .await
            .map_err(SchemaError::internal)?
        {
            Ok(())
        } else {
            Err(SchemaError::not_found("Edge type not found"))
        }
    }

    async fn create_edge_map(
        &self,
        user_id: &str,
        project_id: &str,
        request: SchemaEdgeMapCreateRequest,
    ) -> Result<SchemaEdgeMapView, SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        if self
            .repo
            .edge_map_exists(
                project_id,
                &request.source_type,
                &request.target_type,
                &request.edge_type,
            )
            .await
            .map_err(SchemaError::internal)?
        {
            return Err(SchemaError::bad_request("This mapping already exists"));
        }
        let id = Uuid::new_v4().to_string();
        self.repo
            .create_edge_map(CreateSchemaEdgeMap {
                id: &id,
                project_id,
                source_type: &request.source_type,
                target_type: &request.target_type,
                edge_type: &request.edge_type,
            })
            .await
            .map_err(SchemaError::internal)
            .map(SchemaEdgeMapView::from)
    }

    async fn delete_edge_map(
        &self,
        user_id: &str,
        project_id: &str,
        map_id: &str,
    ) -> Result<(), SchemaError> {
        ensure_schema_write_access(&self.repo, user_id, project_id).await?;
        if self
            .repo
            .delete_edge_map(project_id, map_id)
            .await
            .map_err(SchemaError::internal)?
        {
            Ok(())
        } else {
            Err(SchemaError::not_found("Mapping not found"))
        }
    }
}

#[derive(Default)]
pub(crate) struct DevProjectSchemaService {
    entity_types: Mutex<Vec<SchemaTypeRecord>>,
    edge_types: Mutex<Vec<SchemaTypeRecord>>,
    edge_maps: Mutex<Vec<SchemaEdgeMapRecord>>,
}

impl DevProjectSchemaService {
    #[cfg(test)]
    pub(crate) fn new(
        entity_types: Vec<SchemaTypeRecord>,
        edge_types: Vec<SchemaTypeRecord>,
        edge_maps: Vec<SchemaEdgeMapRecord>,
    ) -> Self {
        Self {
            entity_types: Mutex::new(entity_types),
            edge_types: Mutex::new(edge_types),
            edge_maps: Mutex::new(edge_maps),
        }
    }
}

#[async_trait]
impl ProjectSchemaService for DevProjectSchemaService {
    async fn list_entity_types(
        &self,
        project_id: &str,
    ) -> Result<Vec<SchemaTypeView>, SchemaError> {
        Ok(self
            .entity_types
            .lock()
            .map_err(|_| SchemaError::internal("schema entity type store lock poisoned"))?
            .iter()
            .filter(|record| record.project_id == project_id)
            .cloned()
            .map(SchemaTypeView::from)
            .collect())
    }

    async fn list_edge_types(&self, project_id: &str) -> Result<Vec<SchemaTypeView>, SchemaError> {
        Ok(self
            .edge_types
            .lock()
            .map_err(|_| SchemaError::internal("schema edge type store lock poisoned"))?
            .iter()
            .filter(|record| record.project_id == project_id)
            .cloned()
            .map(SchemaTypeView::from)
            .collect())
    }

    async fn list_edge_maps(
        &self,
        project_id: &str,
    ) -> Result<Vec<SchemaEdgeMapView>, SchemaError> {
        Ok(self
            .edge_maps
            .lock()
            .map_err(|_| SchemaError::internal("schema edge map store lock poisoned"))?
            .iter()
            .filter(|record| record.project_id == project_id)
            .cloned()
            .map(SchemaEdgeMapView::from)
            .collect())
    }

    async fn create_entity_type(
        &self,
        _user_id: &str,
        project_id: &str,
        request: SchemaTypeCreateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        let mut records = self
            .entity_types
            .lock()
            .map_err(|_| SchemaError::internal("schema entity type store lock poisoned"))?;
        if records
            .iter()
            .any(|record| record.project_id == project_id && record.name == request.name)
        {
            return Err(SchemaError::bad_request(
                "Entity type with this name already exists",
            ));
        }
        let record = schema_type_record(project_id, request);
        records.push(record.clone());
        Ok(SchemaTypeView::from(record))
    }

    async fn update_entity_type(
        &self,
        _user_id: &str,
        project_id: &str,
        entity_id: &str,
        request: SchemaTypeUpdateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        let mut records = self
            .entity_types
            .lock()
            .map_err(|_| SchemaError::internal("schema entity type store lock poisoned"))?;
        let record = records
            .iter_mut()
            .find(|record| record.project_id == project_id && record.id == entity_id)
            .ok_or_else(|| SchemaError::not_found("Entity type not found"))?;
        apply_schema_type_update(record, request);
        Ok(SchemaTypeView::from(record.clone()))
    }

    async fn delete_entity_type(
        &self,
        _user_id: &str,
        project_id: &str,
        entity_id: &str,
    ) -> Result<(), SchemaError> {
        delete_schema_type(
            &self.entity_types,
            project_id,
            entity_id,
            "Entity type not found",
        )
    }

    async fn create_edge_type(
        &self,
        _user_id: &str,
        project_id: &str,
        request: SchemaTypeCreateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        let mut records = self
            .edge_types
            .lock()
            .map_err(|_| SchemaError::internal("schema edge type store lock poisoned"))?;
        if records
            .iter()
            .any(|record| record.project_id == project_id && record.name == request.name)
        {
            return Err(SchemaError::bad_request(
                "Edge type with this name already exists",
            ));
        }
        let record = schema_type_record(project_id, request);
        records.push(record.clone());
        Ok(SchemaTypeView::from(record))
    }

    async fn update_edge_type(
        &self,
        _user_id: &str,
        project_id: &str,
        edge_id: &str,
        request: SchemaTypeUpdateRequest,
    ) -> Result<SchemaTypeView, SchemaError> {
        let mut records = self
            .edge_types
            .lock()
            .map_err(|_| SchemaError::internal("schema edge type store lock poisoned"))?;
        let record = records
            .iter_mut()
            .find(|record| record.project_id == project_id && record.id == edge_id)
            .ok_or_else(|| SchemaError::not_found("Edge type not found"))?;
        apply_schema_type_update(record, request);
        Ok(SchemaTypeView::from(record.clone()))
    }

    async fn delete_edge_type(
        &self,
        _user_id: &str,
        project_id: &str,
        edge_id: &str,
    ) -> Result<(), SchemaError> {
        delete_schema_type(&self.edge_types, project_id, edge_id, "Edge type not found")
    }

    async fn create_edge_map(
        &self,
        _user_id: &str,
        project_id: &str,
        request: SchemaEdgeMapCreateRequest,
    ) -> Result<SchemaEdgeMapView, SchemaError> {
        let mut records = self
            .edge_maps
            .lock()
            .map_err(|_| SchemaError::internal("schema edge map store lock poisoned"))?;
        if records.iter().any(|record| {
            record.project_id == project_id
                && record.source_type == request.source_type
                && record.target_type == request.target_type
                && record.edge_type == request.edge_type
        }) {
            return Err(SchemaError::bad_request("This mapping already exists"));
        }
        let record = SchemaEdgeMapRecord {
            id: Uuid::new_v4().to_string(),
            project_id: project_id.to_string(),
            source_type: request.source_type,
            target_type: request.target_type,
            edge_type: request.edge_type,
            status: "ENABLED".to_string(),
            source: "user".to_string(),
            created_at: Utc::now(),
        };
        records.push(record.clone());
        Ok(SchemaEdgeMapView::from(record))
    }

    async fn delete_edge_map(
        &self,
        _user_id: &str,
        project_id: &str,
        map_id: &str,
    ) -> Result<(), SchemaError> {
        let mut records = self
            .edge_maps
            .lock()
            .map_err(|_| SchemaError::internal("schema edge map store lock poisoned"))?;
        let before = records.len();
        records.retain(|record| !(record.project_id == project_id && record.id == map_id));
        if records.len() == before {
            Err(SchemaError::not_found("Mapping not found"))
        } else {
            Ok(())
        }
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/api/v1/projects/:project_id/schema/entities",
            get(list_entity_types).post(create_entity_type),
        )
        .route(
            "/api/v1/projects/:project_id/schema/entities/:entity_id",
            put(update_entity_type).delete(delete_entity_type),
        )
        .route(
            "/api/v1/projects/:project_id/schema/edges",
            get(list_edge_types).post(create_edge_type),
        )
        .route(
            "/api/v1/projects/:project_id/schema/edges/:edge_id",
            put(update_edge_type).delete(delete_edge_type),
        )
        .route(
            "/api/v1/projects/:project_id/schema/mappings",
            get(list_edge_maps).post(create_edge_map),
        )
        .route(
            "/api/v1/projects/:project_id/schema/mappings/:map_id",
            delete(delete_edge_map),
        )
}

async fn list_entity_types(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> Result<Json<Vec<SchemaTypeView>>, SchemaError> {
    ensure_project_access(&app, &identity, &project_id).await?;
    Ok(Json(
        app.project_schema.list_entity_types(&project_id).await?,
    ))
}

async fn list_edge_types(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> Result<Json<Vec<SchemaTypeView>>, SchemaError> {
    ensure_project_access(&app, &identity, &project_id).await?;
    Ok(Json(app.project_schema.list_edge_types(&project_id).await?))
}

async fn list_edge_maps(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> Result<Json<Vec<SchemaEdgeMapView>>, SchemaError> {
    ensure_project_access(&app, &identity, &project_id).await?;
    Ok(Json(app.project_schema.list_edge_maps(&project_id).await?))
}

async fn create_entity_type(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(request): Json<SchemaTypeCreateRequest>,
) -> Result<Json<SchemaTypeView>, SchemaError> {
    Ok(Json(
        app.project_schema
            .create_entity_type(&identity.user_id, &project_id, request)
            .await?,
    ))
}

async fn update_entity_type(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, entity_id)): Path<(String, String)>,
    Json(request): Json<SchemaTypeUpdateRequest>,
) -> Result<Json<SchemaTypeView>, SchemaError> {
    Ok(Json(
        app.project_schema
            .update_entity_type(&identity.user_id, &project_id, &entity_id, request)
            .await?,
    ))
}

async fn delete_entity_type(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, entity_id)): Path<(String, String)>,
) -> Result<StatusCode, SchemaError> {
    app.project_schema
        .delete_entity_type(&identity.user_id, &project_id, &entity_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn create_edge_type(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(request): Json<SchemaTypeCreateRequest>,
) -> Result<Json<SchemaTypeView>, SchemaError> {
    Ok(Json(
        app.project_schema
            .create_edge_type(&identity.user_id, &project_id, request)
            .await?,
    ))
}

async fn update_edge_type(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, edge_id)): Path<(String, String)>,
    Json(request): Json<SchemaTypeUpdateRequest>,
) -> Result<Json<SchemaTypeView>, SchemaError> {
    Ok(Json(
        app.project_schema
            .update_edge_type(&identity.user_id, &project_id, &edge_id, request)
            .await?,
    ))
}

async fn delete_edge_type(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, edge_id)): Path<(String, String)>,
) -> Result<StatusCode, SchemaError> {
    app.project_schema
        .delete_edge_type(&identity.user_id, &project_id, &edge_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn create_edge_map(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(request): Json<SchemaEdgeMapCreateRequest>,
) -> Result<Json<SchemaEdgeMapView>, SchemaError> {
    Ok(Json(
        app.project_schema
            .create_edge_map(&identity.user_id, &project_id, request)
            .await?,
    ))
}

async fn delete_edge_map(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, map_id)): Path<(String, String)>,
) -> Result<StatusCode, SchemaError> {
    app.project_schema
        .delete_edge_map(&identity.user_id, &project_id, &map_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> Result<(), SchemaError> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(SchemaError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(SchemaError::forbidden("Access denied to project"))
    }
}

async fn ensure_schema_write_access(
    repo: &PgSchemaRepository,
    user_id: &str,
    project_id: &str,
) -> Result<(), SchemaError> {
    if repo
        .user_can_write_schema(user_id, project_id)
        .await
        .map_err(SchemaError::internal)?
    {
        Ok(())
    } else {
        Err(SchemaError::forbidden("Access denied to project"))
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SchemaTypeCreateRequest {
    name: String,
    description: Option<String>,
    #[serde(default = "empty_schema_json", rename = "schema")]
    schema_json: Value,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SchemaTypeUpdateRequest {
    description: Option<String>,
    #[serde(rename = "schema")]
    schema_json: Option<Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SchemaEdgeMapCreateRequest {
    source_type: String,
    target_type: String,
    edge_type: String,
}

fn empty_schema_json() -> Value {
    json!({})
}

fn schema_type_record(project_id: &str, request: SchemaTypeCreateRequest) -> SchemaTypeRecord {
    let now = Utc::now();
    SchemaTypeRecord {
        id: Uuid::new_v4().to_string(),
        project_id: project_id.to_string(),
        name: request.name,
        description: request.description,
        schema_json: request.schema_json,
        status: "ENABLED".to_string(),
        source: "user".to_string(),
        created_at: now,
        updated_at: None,
    }
}

fn apply_schema_type_update(record: &mut SchemaTypeRecord, request: SchemaTypeUpdateRequest) {
    let mut changed = false;
    if let Some(description) = request.description {
        record.description = Some(description);
        changed = true;
    }
    if let Some(schema_json) = request.schema_json {
        record.schema_json = schema_json;
        changed = true;
    }
    if changed {
        record.updated_at = Some(Utc::now());
    }
}

fn delete_schema_type(
    records: &Mutex<Vec<SchemaTypeRecord>>,
    project_id: &str,
    type_id: &str,
    not_found: &'static str,
) -> Result<(), SchemaError> {
    let mut records = records
        .lock()
        .map_err(|_| SchemaError::internal("schema type store lock poisoned"))?;
    let before = records.len();
    records.retain(|record| !(record.project_id == project_id && record.id == type_id));
    if records.len() == before {
        Err(SchemaError::not_found(not_found))
    } else {
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SchemaTypeView {
    id: String,
    project_id: String,
    name: String,
    description: Option<String>,
    #[serde(rename = "schema")]
    schema_json: Value,
    status: String,
    source: String,
    created_at: String,
    updated_at: Option<String>,
}

impl From<SchemaTypeRecord> for SchemaTypeView {
    fn from(record: SchemaTypeRecord) -> Self {
        Self {
            id: record.id,
            project_id: record.project_id,
            name: record.name,
            description: record.description,
            schema_json: record.schema_json,
            status: record.status,
            source: record.source,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct SchemaEdgeMapView {
    id: String,
    project_id: String,
    source_type: String,
    target_type: String,
    edge_type: String,
    status: String,
    source: String,
    created_at: String,
}

impl From<SchemaEdgeMapRecord> for SchemaEdgeMapView {
    fn from(record: SchemaEdgeMapRecord) -> Self {
        Self {
            id: record.id,
            project_id: record.project_id,
            source_type: record.source_type,
            target_type: record.target_type,
            edge_type: record.edge_type,
            status: record.status,
            source: record.source,
            created_at: iso8601(record.created_at),
        }
    }
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

#[derive(Debug)]
pub(crate) struct SchemaError {
    status: StatusCode,
    detail: String,
}

impl SchemaError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for SchemaError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn schema_type(id: &str, name: &str) -> SchemaTypeRecord {
        SchemaTypeRecord {
            id: id.to_string(),
            project_id: "project-1".to_string(),
            name: name.to_string(),
            description: Some(format!("{name} description")),
            schema_json: json!({"type": "object", "properties": {"name": {"type": "string"}}}),
            status: "ENABLED".to_string(),
            source: "user".to_string(),
            created_at: Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
            updated_at: Some(Utc.with_ymd_and_hms(2026, 1, 6, 0, 0, 0).unwrap()),
        }
    }

    fn edge_map() -> SchemaEdgeMapRecord {
        SchemaEdgeMapRecord {
            id: "map-1".to_string(),
            project_id: "project-1".to_string(),
            source_type: "Person".to_string(),
            target_type: "Company".to_string(),
            edge_type: "WORKS_AT".to_string(),
            status: "ENABLED".to_string(),
            source: "user".to_string(),
            created_at: Utc.with_ymd_and_hms(2026, 1, 5, 0, 0, 0).unwrap(),
        }
    }

    #[test]
    fn entity_type_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/schema_entity_types_response.json"
        ))
        .expect("schema entity type golden must be valid JSON");
        let response = vec![SchemaTypeView::from(schema_type("entity-type-1", "Person"))];

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn edge_type_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/schema_edge_types_response.json"
        ))
        .expect("schema edge type golden must be valid JSON");
        let response = vec![SchemaTypeView::from(schema_type("edge-type-1", "WORKS_AT"))];

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn edge_map_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/schema_edge_maps_response.json"
        ))
        .expect("schema edge map golden must be valid JSON");
        let response = vec![SchemaEdgeMapView::from(edge_map())];

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn entity_type_mutation_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/schema_entity_type_response.json"
        ))
        .expect("schema entity mutation golden must be valid JSON");
        let response = SchemaTypeView::from(schema_type("entity-type-1", "Person"));

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn edge_map_mutation_response_matches_python_shape() {
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/schema_edge_map_response.json"
        ))
        .expect("schema edge map mutation golden must be valid JSON");
        let response = SchemaEdgeMapView::from(edge_map());

        let value = serde_json::to_value(response).expect("response serializes");

        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn dev_schema_service_filters_by_project() {
        let service = DevProjectSchemaService::new(
            vec![
                schema_type("entity-type-1", "Person"),
                SchemaTypeRecord {
                    project_id: "project-2".to_string(),
                    ..schema_type("entity-type-other", "Other")
                },
            ],
            vec![schema_type("edge-type-1", "WORKS_AT")],
            vec![edge_map()],
        );

        let entities = service
            .list_entity_types("project-1")
            .await
            .expect("dev entity list succeeds");
        let edges = service
            .list_edge_types("project-1")
            .await
            .expect("dev edge list succeeds");
        let maps = service
            .list_edge_maps("project-1")
            .await
            .expect("dev map list succeeds");

        assert_eq!(entities.len(), 1);
        assert_eq!(edges.len(), 1);
        assert_eq!(maps.len(), 1);
    }

    #[tokio::test]
    async fn dev_schema_service_entity_crud_and_duplicates_match_python_statuses() {
        let service = DevProjectSchemaService::new(Vec::new(), Vec::new(), Vec::new());
        let created = service
            .create_entity_type(
                "user-1",
                "project-1",
                SchemaTypeCreateRequest {
                    name: "Person".to_string(),
                    description: Some("Human".to_string()),
                    schema_json: json!({"required": ["name"]}),
                },
            )
            .await
            .expect("create succeeds");
        assert_eq!(created.name, "Person");
        assert_eq!(created.status, "ENABLED");
        assert_eq!(created.source, "user");

        let duplicate = service
            .create_entity_type(
                "user-1",
                "project-1",
                SchemaTypeCreateRequest {
                    name: "Person".to_string(),
                    description: None,
                    schema_json: json!({}),
                },
            )
            .await
            .unwrap_err();
        assert_eq!(duplicate.status, StatusCode::BAD_REQUEST);

        let updated = service
            .update_entity_type(
                "user-1",
                "project-1",
                &created.id,
                SchemaTypeUpdateRequest {
                    description: Some("Updated".to_string()),
                    schema_json: Some(json!({"required": ["name", "email"]})),
                },
            )
            .await
            .expect("update succeeds");
        assert_eq!(updated.description.as_deref(), Some("Updated"));
        assert_eq!(updated.schema_json, json!({"required": ["name", "email"]}));
        assert!(updated.updated_at.is_some());

        service
            .delete_entity_type("user-1", "project-1", &created.id)
            .await
            .expect("delete succeeds");
        let missing = service
            .delete_entity_type("user-1", "project-1", &created.id)
            .await
            .unwrap_err();
        assert_eq!(missing.status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn dev_schema_service_edge_map_create_and_delete_match_python_statuses() {
        let service = DevProjectSchemaService::new(Vec::new(), Vec::new(), Vec::new());
        let created = service
            .create_edge_map(
                "user-1",
                "project-1",
                SchemaEdgeMapCreateRequest {
                    source_type: "Person".to_string(),
                    target_type: "Company".to_string(),
                    edge_type: "WORKS_AT".to_string(),
                },
            )
            .await
            .expect("create succeeds");
        assert_eq!(created.source_type, "Person");

        let duplicate = service
            .create_edge_map(
                "user-1",
                "project-1",
                SchemaEdgeMapCreateRequest {
                    source_type: "Person".to_string(),
                    target_type: "Company".to_string(),
                    edge_type: "WORKS_AT".to_string(),
                },
            )
            .await
            .unwrap_err();
        assert_eq!(duplicate.status, StatusCode::BAD_REQUEST);

        service
            .delete_edge_map("user-1", "project-1", &created.id)
            .await
            .expect("delete succeeds");
        let missing = service
            .delete_edge_map("user-1", "project-1", &created.id)
            .await
            .unwrap_err();
        assert_eq!(missing.status, StatusCode::NOT_FOUND);
    }
}
