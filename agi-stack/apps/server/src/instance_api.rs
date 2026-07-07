//! P7 instance read-side strangler slice.
//!
//! Rust owns current-tenant instance list/detail reads, instance config
//! reads/writes, pending-config staging, instance LLM config reads/writes,
//! instance member list/search/mutations, plus instance channel config list
//! reads. Instance writes, scaling, config apply, files, channel mutations/tests,
//! and runtime side effects remain Python-owned.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, put},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::Deserialize;
use serde::Serialize;
use serde_json::{json, Map, Value};
use uuid::Uuid;

use agistack_adapters_postgres::{
    InstanceChannelRecord, InstanceListQuery as PgInstanceListQuery,
    InstanceMemberListQuery as PgInstanceMemberListQuery, InstanceMemberRecord, InstanceRecord,
    InstanceUserSearchRecord, PgInstanceRepository,
};

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedInstances = Arc<dyn InstanceService>;

#[async_trait]
pub(crate) trait InstanceService: Send + Sync {
    async fn list_instances(
        &self,
        user_id: &str,
        query: ValidatedInstanceListQuery,
    ) -> Result<InstanceListResponse, InstanceApiError>;

    async fn get_instance(
        &self,
        user_id: &str,
        instance_id: &str,
    ) -> Result<InstanceView, InstanceApiError>;

    async fn update_instance_config(
        &self,
        user_id: &str,
        instance_id: &str,
        request: InstanceConfigUpdateRequest,
    ) -> Result<InstanceConfigResponse, InstanceApiError>;

    async fn save_pending_config(
        &self,
        user_id: &str,
        instance_id: &str,
        request: PendingConfigRequest,
    ) -> Result<InstanceView, InstanceApiError>;

    async fn update_instance_llm_config(
        &self,
        user_id: &str,
        instance_id: &str,
        request: InstanceLlmConfigUpdateRequest,
    ) -> Result<InstanceLlmConfigResponse, InstanceApiError>;

    async fn list_instance_channels(
        &self,
        user_id: &str,
        instance_id: &str,
    ) -> Result<InstanceChannelListResponse, InstanceApiError>;

    async fn list_instance_members(
        &self,
        user_id: &str,
        instance_id: &str,
        query: ValidatedInstanceMemberListQuery,
    ) -> Result<InstanceMemberListResponse, InstanceApiError>;

    async fn add_instance_member(
        &self,
        user_id: &str,
        instance_id: &str,
        request: InstanceMemberCreateRequest,
    ) -> Result<InstanceMemberView, InstanceApiError>;

    async fn update_instance_member_role(
        &self,
        user_id: &str,
        instance_id: &str,
        member_id: &str,
        request: InstanceMemberUpdateRequest,
    ) -> Result<InstanceMemberView, InstanceApiError>;

    async fn remove_instance_member(
        &self,
        user_id: &str,
        instance_id: &str,
        member_user_id: &str,
    ) -> Result<(), InstanceApiError>;

    async fn search_instance_member_users(
        &self,
        user_id: &str,
        instance_id: &str,
        query: ValidatedInstanceMemberUserSearchQuery,
    ) -> Result<Vec<InstanceUserSearchView>, InstanceApiError>;
}

pub(crate) struct PgInstanceService {
    repo: PgInstanceRepository,
}

impl PgInstanceService {
    pub(crate) fn new(repo: PgInstanceRepository) -> Self {
        Self { repo }
    }
}

#[async_trait]
impl InstanceService for PgInstanceService {
    async fn list_instances(
        &self,
        user_id: &str,
        query: ValidatedInstanceListQuery,
    ) -> Result<InstanceListResponse, InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        let (records, total) = self
            .repo
            .list_instances(PgInstanceListQuery {
                tenant_id: &tenant_id,
                limit: query.page_size,
                offset: query.offset,
            })
            .await
            .map_err(InstanceApiError::internal)?;
        Ok(InstanceListResponse::from_records(
            records,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_instance(
        &self,
        user_id: &str,
        instance_id: &str,
    ) -> Result<InstanceView, InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .map(InstanceView::from)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))
    }

    async fn update_instance_config(
        &self,
        user_id: &str,
        instance_id: &str,
        request: InstanceConfigUpdateRequest,
    ) -> Result<InstanceConfigResponse, InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        self.repo
            .update_instance_config(
                &tenant_id,
                instance_id,
                Value::Object(request.env_vars),
                Value::Object(request.advanced_config),
                Value::Object(request.llm_providers),
            )
            .await
            .map_err(InstanceApiError::internal)?
            .map(InstanceConfigResponse::from)
            .ok_or_else(|| InstanceApiError::not_found("Instance operation failed"))
    }

    async fn save_pending_config(
        &self,
        user_id: &str,
        instance_id: &str,
        request: PendingConfigRequest,
    ) -> Result<InstanceView, InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        self.repo
            .save_pending_config(&tenant_id, instance_id, request.into_value())
            .await
            .map_err(InstanceApiError::internal)?
            .map(InstanceView::from)
            .ok_or_else(|| InstanceApiError::not_found("Instance operation failed"))
    }

    async fn update_instance_llm_config(
        &self,
        user_id: &str,
        instance_id: &str,
        request: InstanceLlmConfigUpdateRequest,
    ) -> Result<InstanceLlmConfigResponse, InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        let instance = self
            .repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        let llm_providers = update_llm_config_value(instance.llm_providers, request);

        self.repo
            .update_instance_config(
                &tenant_id,
                instance_id,
                instance.env_vars,
                instance.advanced_config,
                llm_providers.clone(),
            )
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance operation failed"))?;
        Ok(InstanceLlmConfigResponse::from_value(&llm_providers))
    }

    async fn list_instance_channels(
        &self,
        user_id: &str,
        instance_id: &str,
    ) -> Result<InstanceChannelListResponse, InstanceApiError> {
        let tenant_id = self
            .repo
            .instance_tenant_id(instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        let allowed = self
            .repo
            .user_can_access_tenant(user_id, &tenant_id)
            .await
            .map_err(InstanceApiError::internal)?;
        if !allowed {
            return Err(InstanceApiError::forbidden("Tenant access required"));
        }

        let channels = self
            .repo
            .list_instance_channels(instance_id)
            .await
            .map_err(InstanceApiError::internal)?;
        Ok(InstanceChannelListResponse::from_records(channels))
    }

    async fn list_instance_members(
        &self,
        user_id: &str,
        instance_id: &str,
        query: ValidatedInstanceMemberListQuery,
    ) -> Result<InstanceMemberListResponse, InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        let (records, total) = self
            .repo
            .list_instance_members(PgInstanceMemberListQuery {
                instance_id,
                limit: query.limit,
                offset: query.offset,
            })
            .await
            .map_err(InstanceApiError::internal)?;
        Ok(InstanceMemberListResponse::from_records(
            records,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn add_instance_member(
        &self,
        user_id: &str,
        instance_id: &str,
        request: InstanceMemberCreateRequest,
    ) -> Result<InstanceMemberView, InstanceApiError> {
        let role = validate_instance_role(
            &request.role.unwrap_or_else(|| "viewer".to_string()),
            StatusCode::BAD_REQUEST,
            "Invalid instance member request",
        )?;
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        if self
            .repo
            .instance_member_exists_any(instance_id, &request.user_id)
            .await
            .map_err(InstanceApiError::internal)?
        {
            return Err(InstanceApiError::bad_request(
                "Invalid instance member request",
            ));
        }

        self.repo
            .insert_instance_member(
                &Uuid::new_v4().to_string(),
                instance_id,
                &request.user_id,
                &role,
            )
            .await
            .map_err(InstanceApiError::internal)
            .map(InstanceMemberView::from)
    }

    async fn update_instance_member_role(
        &self,
        user_id: &str,
        instance_id: &str,
        member_id: &str,
        request: InstanceMemberUpdateRequest,
    ) -> Result<InstanceMemberView, InstanceApiError> {
        let role = validate_instance_role(
            &request.role,
            StatusCode::NOT_FOUND,
            "Instance member not found",
        )?;
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        self.repo
            .update_instance_member_role(instance_id, member_id, &role)
            .await
            .map_err(InstanceApiError::internal)?
            .map(InstanceMemberView::from)
            .ok_or_else(|| InstanceApiError::not_found("Instance member not found"))
    }

    async fn remove_instance_member(
        &self,
        user_id: &str,
        instance_id: &str,
        member_user_id: &str,
    ) -> Result<(), InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        if self
            .repo
            .soft_delete_instance_member(instance_id, member_user_id)
            .await
            .map_err(InstanceApiError::internal)?
        {
            Ok(())
        } else {
            Err(InstanceApiError::not_found("Instance member not found"))
        }
    }

    async fn search_instance_member_users(
        &self,
        user_id: &str,
        instance_id: &str,
        query: ValidatedInstanceMemberUserSearchQuery,
    ) -> Result<Vec<InstanceUserSearchView>, InstanceApiError> {
        let tenant_id = default_tenant_or_error(&self.repo, user_id).await?;
        self.repo
            .get_instance(&tenant_id, instance_id)
            .await
            .map_err(InstanceApiError::internal)?
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;

        self.repo
            .search_tenant_users(&tenant_id, &query.q, query.limit)
            .await
            .map_err(InstanceApiError::internal)
            .map(|records| {
                records
                    .into_iter()
                    .map(InstanceUserSearchView::from)
                    .collect()
            })
    }
}

#[derive(Default)]
pub(crate) struct DevInstanceService {
    tenant_id: String,
    instances: Vec<InstanceRecord>,
    channels: Vec<InstanceChannelRecord>,
    members: Vec<InstanceMemberRecord>,
    member_users: Vec<InstanceUserSearchRecord>,
}

impl DevInstanceService {
    #[cfg(test)]
    pub(crate) fn new(tenant_id: impl Into<String>, instances: Vec<InstanceRecord>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            instances,
            channels: Vec::new(),
            members: Vec::new(),
            member_users: Vec::new(),
        }
    }

    #[cfg(test)]
    pub(crate) fn with_channels(
        tenant_id: impl Into<String>,
        instances: Vec<InstanceRecord>,
        channels: Vec<InstanceChannelRecord>,
    ) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            instances,
            channels,
            members: Vec::new(),
            member_users: Vec::new(),
        }
    }

    #[cfg(test)]
    pub(crate) fn with_members(
        tenant_id: impl Into<String>,
        instances: Vec<InstanceRecord>,
        members: Vec<InstanceMemberRecord>,
    ) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            instances,
            channels: Vec::new(),
            members,
            member_users: Vec::new(),
        }
    }

    #[cfg(test)]
    pub(crate) fn with_member_users(
        tenant_id: impl Into<String>,
        instances: Vec<InstanceRecord>,
        member_users: Vec<InstanceUserSearchRecord>,
    ) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            instances,
            channels: Vec::new(),
            members: Vec::new(),
            member_users,
        }
    }
}

#[async_trait]
impl InstanceService for DevInstanceService {
    async fn list_instances(
        &self,
        _user_id: &str,
        query: ValidatedInstanceListQuery,
    ) -> Result<InstanceListResponse, InstanceApiError> {
        let mut instances = self
            .instances
            .iter()
            .filter(|instance| instance.tenant_id == self.tenant_id)
            .cloned()
            .collect::<Vec<_>>();
        sort_instances(&mut instances);
        let total = instances.len() as i64;
        let page = page(instances, query.page_size, query.offset);
        Ok(InstanceListResponse::from_records(
            page,
            total,
            query.page,
            query.page_size,
        ))
    }

    async fn get_instance(
        &self,
        _user_id: &str,
        instance_id: &str,
    ) -> Result<InstanceView, InstanceApiError> {
        self.instances
            .iter()
            .find(|instance| instance.tenant_id == self.tenant_id && instance.id == instance_id)
            .cloned()
            .map(InstanceView::from)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))
    }

    async fn update_instance_config(
        &self,
        _user_id: &str,
        instance_id: &str,
        request: InstanceConfigUpdateRequest,
    ) -> Result<InstanceConfigResponse, InstanceApiError> {
        self.instances
            .iter()
            .find(|instance| instance.tenant_id == self.tenant_id && instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        Ok(InstanceConfigResponse {
            env_vars: Value::Object(request.env_vars),
            advanced_config: Value::Object(request.advanced_config),
            llm_providers: Value::Object(request.llm_providers),
        })
    }

    async fn save_pending_config(
        &self,
        _user_id: &str,
        instance_id: &str,
        request: PendingConfigRequest,
    ) -> Result<InstanceView, InstanceApiError> {
        let mut instance = self
            .instances
            .iter()
            .find(|instance| instance.tenant_id == self.tenant_id && instance.id == instance_id)
            .cloned()
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        instance.pending_config = request.into_value();
        instance.updated_at = Some(Utc::now());
        Ok(InstanceView::from(instance))
    }

    async fn update_instance_llm_config(
        &self,
        _user_id: &str,
        instance_id: &str,
        request: InstanceLlmConfigUpdateRequest,
    ) -> Result<InstanceLlmConfigResponse, InstanceApiError> {
        let instance = self
            .instances
            .iter()
            .find(|instance| instance.tenant_id == self.tenant_id && instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        let llm_providers = update_llm_config_value(instance.llm_providers.clone(), request);
        Ok(InstanceLlmConfigResponse::from_value(&llm_providers))
    }

    async fn list_instance_channels(
        &self,
        _user_id: &str,
        instance_id: &str,
    ) -> Result<InstanceChannelListResponse, InstanceApiError> {
        let instance = self
            .instances
            .iter()
            .find(|instance| instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        if instance.tenant_id != self.tenant_id {
            return Err(InstanceApiError::forbidden("Tenant access required"));
        }

        let mut channels = self
            .channels
            .iter()
            .filter(|channel| channel.instance_id == instance_id && channel.deleted_at.is_none())
            .cloned()
            .collect::<Vec<_>>();
        sort_instance_channels(&mut channels);
        Ok(InstanceChannelListResponse::from_records(channels))
    }

    async fn list_instance_members(
        &self,
        _user_id: &str,
        instance_id: &str,
        query: ValidatedInstanceMemberListQuery,
    ) -> Result<InstanceMemberListResponse, InstanceApiError> {
        let instance = self
            .instances
            .iter()
            .find(|instance| instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        if instance.tenant_id != self.tenant_id {
            return Err(InstanceApiError::not_found("Instance not found"));
        }

        let mut members = self
            .members
            .iter()
            .filter(|member| member.instance_id == instance_id)
            .cloned()
            .collect::<Vec<_>>();
        sort_instance_members(&mut members);
        let total = members.len() as i64;
        let page = page(members, query.limit, query.offset);
        Ok(InstanceMemberListResponse::from_records(
            page,
            total,
            query.limit,
            query.offset,
        ))
    }

    async fn add_instance_member(
        &self,
        _user_id: &str,
        instance_id: &str,
        request: InstanceMemberCreateRequest,
    ) -> Result<InstanceMemberView, InstanceApiError> {
        let role = validate_instance_role(
            &request.role.unwrap_or_else(|| "viewer".to_string()),
            StatusCode::BAD_REQUEST,
            "Invalid instance member request",
        )?;
        self.instances
            .iter()
            .find(|instance| instance.tenant_id == self.tenant_id && instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        if self
            .members
            .iter()
            .any(|member| member.instance_id == instance_id && member.user_id == request.user_id)
        {
            return Err(InstanceApiError::bad_request(
                "Invalid instance member request",
            ));
        }
        let user = self
            .member_users
            .iter()
            .find(|user| user.id == request.user_id);
        Ok(InstanceMemberView {
            id: Uuid::new_v4().to_string(),
            instance_id: instance_id.to_string(),
            user_id: request.user_id,
            role,
            user_name: user.and_then(|user| user.full_name.clone()),
            user_email: user.map(|user| user.email.clone()),
            user_avatar_url: None,
            created_at: iso8601(Utc::now()),
        })
    }

    async fn update_instance_member_role(
        &self,
        _user_id: &str,
        instance_id: &str,
        member_id: &str,
        request: InstanceMemberUpdateRequest,
    ) -> Result<InstanceMemberView, InstanceApiError> {
        let role = validate_instance_role(
            &request.role,
            StatusCode::NOT_FOUND,
            "Instance member not found",
        )?;
        self.instances
            .iter()
            .find(|instance| instance.tenant_id == self.tenant_id && instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        let member = self
            .members
            .iter()
            .find(|member| member.instance_id == instance_id && member.id == member_id)
            .cloned()
            .ok_or_else(|| InstanceApiError::not_found("Instance member not found"))?;
        let user = self
            .member_users
            .iter()
            .find(|user| user.id == member.user_id);
        Ok(InstanceMemberView {
            id: member.id,
            instance_id: member.instance_id,
            user_id: member.user_id,
            role,
            user_name: user.and_then(|user| user.full_name.clone()),
            user_email: user.map(|user| user.email.clone()),
            user_avatar_url: None,
            created_at: iso8601(member.created_at),
        })
    }

    async fn remove_instance_member(
        &self,
        _user_id: &str,
        instance_id: &str,
        member_user_id: &str,
    ) -> Result<(), InstanceApiError> {
        self.instances
            .iter()
            .find(|instance| instance.tenant_id == self.tenant_id && instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        self.members
            .iter()
            .find(|member| member.instance_id == instance_id && member.user_id == member_user_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance member not found"))?;
        Ok(())
    }

    async fn search_instance_member_users(
        &self,
        _user_id: &str,
        instance_id: &str,
        query: ValidatedInstanceMemberUserSearchQuery,
    ) -> Result<Vec<InstanceUserSearchView>, InstanceApiError> {
        let instance = self
            .instances
            .iter()
            .find(|instance| instance.id == instance_id)
            .ok_or_else(|| InstanceApiError::not_found("Instance not found"))?;
        if instance.tenant_id != self.tenant_id {
            return Err(InstanceApiError::not_found("Instance not found"));
        }

        let q = query.q.to_lowercase();
        let mut users = self
            .member_users
            .iter()
            .filter(|user| {
                q.is_empty()
                    || user.email.to_lowercase().contains(&q)
                    || user
                        .full_name
                        .as_deref()
                        .unwrap_or_default()
                        .to_lowercase()
                        .contains(&q)
            })
            .cloned()
            .collect::<Vec<_>>();
        users.sort_by(|left, right| {
            cmp_optional_string_nulls_last(&left.full_name, &right.full_name)
                .then_with(|| left.email.cmp(&right.email))
        });
        Ok(users
            .into_iter()
            .take(query.limit as usize)
            .map(InstanceUserSearchView::from)
            .collect())
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/instances/", get(list_instances))
        .route("/api/v1/instances/:instance_id", get(get_instance))
        .route(
            "/api/v1/instances/:instance_id/config",
            get(get_instance_config).put(update_instance_config),
        )
        .route(
            "/api/v1/instances/:instance_id/config/pending",
            put(save_pending_config),
        )
        .route(
            "/api/v1/instances/:instance_id/llm-config",
            get(get_instance_llm_config).put(update_instance_llm_config),
        )
        .route(
            "/api/v1/instances/:instance_id/members",
            get(list_instance_members).post(add_instance_member),
        )
        .route(
            "/api/v1/instances/:instance_id/members/:member_id",
            put(update_instance_member_role).delete(remove_instance_member),
        )
        .route(
            "/api/v1/instances/:instance_id/members/search-users",
            get(search_instance_member_users),
        )
        .route(
            "/api/v1/instances/:instance_id/channels",
            get(list_instance_channels),
        )
}

async fn list_instances(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<InstanceListQuery>,
) -> Result<Json<InstanceListResponse>, InstanceApiError> {
    let query = query.validated()?;
    let response = app
        .instances
        .list_instances(&identity.user_id, query)
        .await?;
    Ok(Json(response))
}

async fn get_instance(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
) -> Result<Json<InstanceView>, InstanceApiError> {
    let response = app
        .instances
        .get_instance(&identity.user_id, &instance_id)
        .await?;
    Ok(Json(response))
}

async fn get_instance_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
) -> Result<Json<InstanceConfigResponse>, InstanceApiError> {
    let instance = app
        .instances
        .get_instance(&identity.user_id, &instance_id)
        .await?;
    Ok(Json(InstanceConfigResponse {
        env_vars: instance.env_vars,
        advanced_config: instance.advanced_config,
        llm_providers: instance.llm_providers,
    }))
}

async fn update_instance_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
    Json(request): Json<InstanceConfigUpdateRequest>,
) -> Result<Json<InstanceConfigResponse>, InstanceApiError> {
    let response = app
        .instances
        .update_instance_config(&identity.user_id, &instance_id, request)
        .await?;
    Ok(Json(response))
}

async fn save_pending_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
    Json(request): Json<PendingConfigRequest>,
) -> Result<Json<InstanceView>, InstanceApiError> {
    let response = app
        .instances
        .save_pending_config(&identity.user_id, &instance_id, request)
        .await?;
    Ok(Json(response))
}

async fn get_instance_llm_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
) -> Result<Json<InstanceLlmConfigResponse>, InstanceApiError> {
    let instance = app
        .instances
        .get_instance(&identity.user_id, &instance_id)
        .await?;
    let llm_cfg = instance.llm_providers.as_object();
    Ok(Json(InstanceLlmConfigResponse {
        provider_id: llm_cfg.and_then(|config| string_field(config.get("provider_id"))),
        model_name: llm_cfg.and_then(|config| string_field(config.get("model_name"))),
        has_api_key_override: llm_cfg
            .and_then(|config| config.get("api_key_override"))
            .map(json_truthy)
            .unwrap_or(false),
    }))
}

async fn update_instance_llm_config(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
    Json(request): Json<InstanceLlmConfigUpdateRequest>,
) -> Result<Json<InstanceLlmConfigResponse>, InstanceApiError> {
    let response = app
        .instances
        .update_instance_llm_config(&identity.user_id, &instance_id, request)
        .await?;
    Ok(Json(response))
}

async fn list_instance_channels(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
) -> Result<Json<InstanceChannelListResponse>, InstanceApiError> {
    let response = app
        .instances
        .list_instance_channels(&identity.user_id, &instance_id)
        .await?;
    Ok(Json(response))
}

async fn list_instance_members(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
    Query(query): Query<InstanceMemberListQuery>,
) -> Result<Json<InstanceMemberListResponse>, InstanceApiError> {
    let query = query.validated()?;
    let response = app
        .instances
        .list_instance_members(&identity.user_id, &instance_id, query)
        .await?;
    Ok(Json(response))
}

async fn add_instance_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
    Json(request): Json<InstanceMemberCreateRequest>,
) -> Result<(StatusCode, Json<InstanceMemberView>), InstanceApiError> {
    let response = app
        .instances
        .add_instance_member(&identity.user_id, &instance_id, request)
        .await?;
    Ok((StatusCode::CREATED, Json(response)))
}

async fn update_instance_member_role(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((instance_id, member_id)): Path<(String, String)>,
    Json(request): Json<InstanceMemberUpdateRequest>,
) -> Result<Json<InstanceMemberView>, InstanceApiError> {
    let response = app
        .instances
        .update_instance_member_role(&identity.user_id, &instance_id, &member_id, request)
        .await?;
    Ok(Json(response))
}

async fn remove_instance_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((instance_id, member_user_id)): Path<(String, String)>,
) -> Result<StatusCode, InstanceApiError> {
    app.instances
        .remove_instance_member(&identity.user_id, &instance_id, &member_user_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn search_instance_member_users(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(instance_id): Path<String>,
    Query(query): Query<InstanceMemberUserSearchQuery>,
) -> Result<Json<Vec<InstanceUserSearchView>>, InstanceApiError> {
    let query = query.validated()?;
    let response = app
        .instances
        .search_instance_member_users(&identity.user_id, &instance_id, query)
        .await?;
    Ok(Json(response))
}

async fn default_tenant_or_error(
    repo: &PgInstanceRepository,
    user_id: &str,
) -> Result<String, InstanceApiError> {
    repo.default_tenant_for_user(user_id)
        .await
        .map_err(InstanceApiError::internal)?
        .ok_or_else(|| {
            InstanceApiError::bad_request(
                "User does not belong to any tenant. Please contact administrator.",
            )
        })
}

#[derive(Debug, Clone, Deserialize)]
struct InstanceListQuery {
    page: Option<i64>,
    page_size: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
struct InstanceMemberListQuery {
    limit: Option<i64>,
    offset: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
struct InstanceMemberUserSearchQuery {
    q: Option<String>,
    limit: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct PendingConfigRequest {
    pending_config: Map<String, Value>,
}

impl PendingConfigRequest {
    fn into_value(self) -> Value {
        Value::Object(self.pending_config)
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct InstanceConfigUpdateRequest {
    #[serde(default)]
    env_vars: Map<String, Value>,
    #[serde(default)]
    advanced_config: Map<String, Value>,
    #[serde(default)]
    llm_providers: Map<String, Value>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct InstanceLlmConfigUpdateRequest {
    provider_id: Option<String>,
    model_name: Option<String>,
    api_key_override: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct InstanceMemberCreateRequest {
    #[allow(dead_code)]
    instance_id: String,
    user_id: String,
    role: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct InstanceMemberUpdateRequest {
    role: String,
}

impl InstanceMemberUserSearchQuery {
    fn validated(self) -> Result<ValidatedInstanceMemberUserSearchQuery, InstanceApiError> {
        Ok(ValidatedInstanceMemberUserSearchQuery {
            q: self.q.unwrap_or_default(),
            limit: validate_range(self.limit.unwrap_or(20), "limit", 1, 100)?,
        })
    }
}

impl InstanceMemberListQuery {
    fn validated(self) -> Result<ValidatedInstanceMemberListQuery, InstanceApiError> {
        Ok(ValidatedInstanceMemberListQuery {
            limit: validate_range(self.limit.unwrap_or(25), "limit", 1, 100)?,
            offset: validate_range(self.offset.unwrap_or(0), "offset", 0, i64::MAX)?,
        })
    }
}

impl InstanceListQuery {
    fn validated(self) -> Result<ValidatedInstanceListQuery, InstanceApiError> {
        let page = validate_range(self.page.unwrap_or(1), "page", 1, i64::MAX)?;
        let page_size = validate_range(self.page_size.unwrap_or(20), "page_size", 1, 100)?;
        let offset = page
            .checked_sub(1)
            .and_then(|value| value.checked_mul(page_size))
            .ok_or_else(|| InstanceApiError::unprocessable("pagination offset is too large"))?;
        Ok(ValidatedInstanceListQuery {
            page,
            page_size,
            offset,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedInstanceListQuery {
    page: i64,
    page_size: i64,
    offset: i64,
}

#[derive(Debug, Clone, Copy)]
pub(crate) struct ValidatedInstanceMemberListQuery {
    limit: i64,
    offset: i64,
}

#[derive(Debug, Clone)]
pub(crate) struct ValidatedInstanceMemberUserSearchQuery {
    q: String,
    limit: i64,
}

fn validate_range(value: i64, field: &str, min: i64, max: i64) -> Result<i64, InstanceApiError> {
    if value < min || value > max {
        Err(InstanceApiError::unprocessable(format!(
            "{field} must be between {min} and {max}"
        )))
    } else {
        Ok(value)
    }
}

fn validate_instance_role(
    role: &str,
    status: StatusCode,
    detail: &'static str,
) -> Result<String, InstanceApiError> {
    match role {
        "admin" | "editor" | "user" | "viewer" => Ok(role.to_string()),
        _ => Err(InstanceApiError::new(status, detail)),
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceView {
    id: String,
    name: String,
    slug: String,
    description: Option<String>,
    tenant_id: String,
    cluster_id: Option<String>,
    namespace: Option<String>,
    image_version: String,
    replicas: i32,
    cpu_request: String,
    cpu_limit: String,
    mem_request: String,
    mem_limit: String,
    service_type: String,
    ingress_domain: Option<String>,
    env_vars: Value,
    quota_cpu: Option<String>,
    quota_memory: Option<String>,
    quota_max_pods: Option<i32>,
    storage_class: Option<String>,
    storage_size: Option<String>,
    advanced_config: Value,
    llm_providers: Value,
    compute_provider: Option<String>,
    runtime: String,
    workspace_id: Option<String>,
    hex_position_q: Option<i32>,
    hex_position_r: Option<i32>,
    agent_display_name: Option<String>,
    agent_label: Option<String>,
    theme_color: Option<String>,
    status: String,
    health_status: Option<String>,
    current_revision: i32,
    available_replicas: i32,
    proxy_token: Option<String>,
    pending_config: Value,
    created_by: String,
    created_at: String,
    updated_at: Option<String>,
}

impl From<InstanceRecord> for InstanceView {
    fn from(record: InstanceRecord) -> Self {
        Self {
            id: record.id,
            name: record.name,
            slug: record.slug,
            description: record.description,
            tenant_id: record.tenant_id,
            cluster_id: record.cluster_id,
            namespace: record.namespace,
            image_version: record.image_version,
            replicas: record.replicas,
            cpu_request: record.cpu_request,
            cpu_limit: record.cpu_limit,
            mem_request: record.mem_request,
            mem_limit: record.mem_limit,
            service_type: record.service_type,
            ingress_domain: record.ingress_domain,
            env_vars: record.env_vars,
            quota_cpu: record.quota_cpu,
            quota_memory: record.quota_memory,
            quota_max_pods: record.quota_max_pods,
            storage_class: record.storage_class,
            storage_size: record.storage_size,
            advanced_config: record.advanced_config,
            llm_providers: record.llm_providers,
            compute_provider: record.compute_provider,
            runtime: record.runtime,
            workspace_id: record.workspace_id,
            hex_position_q: record.hex_position_q,
            hex_position_r: record.hex_position_r,
            agent_display_name: record.agent_display_name,
            agent_label: record.agent_label,
            theme_color: record.theme_color,
            status: record.status,
            health_status: record.health_status,
            current_revision: record.current_revision,
            available_replicas: record.available_replicas,
            proxy_token: record.proxy_token,
            pending_config: record.pending_config,
            created_by: record.created_by,
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceListResponse {
    instances: Vec<InstanceView>,
    total: i64,
    page: i64,
    page_size: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceConfigResponse {
    env_vars: Value,
    advanced_config: Value,
    llm_providers: Value,
}

impl From<InstanceRecord> for InstanceConfigResponse {
    fn from(record: InstanceRecord) -> Self {
        Self {
            env_vars: record.env_vars,
            advanced_config: record.advanced_config,
            llm_providers: record.llm_providers,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceLlmConfigResponse {
    provider_id: Option<String>,
    model_name: Option<String>,
    has_api_key_override: bool,
}

impl InstanceLlmConfigResponse {
    fn from_value(value: &Value) -> Self {
        let llm_cfg = value.as_object();
        Self {
            provider_id: llm_cfg.and_then(|config| string_field(config.get("provider_id"))),
            model_name: llm_cfg.and_then(|config| string_field(config.get("model_name"))),
            has_api_key_override: llm_cfg
                .and_then(|config| config.get("api_key_override"))
                .map(json_truthy)
                .unwrap_or(false),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceMemberView {
    id: String,
    instance_id: String,
    user_id: String,
    role: String,
    user_name: Option<String>,
    user_email: Option<String>,
    user_avatar_url: Option<String>,
    created_at: String,
}

impl From<InstanceMemberRecord> for InstanceMemberView {
    fn from(record: InstanceMemberRecord) -> Self {
        Self {
            id: record.id,
            instance_id: record.instance_id,
            user_id: record.user_id,
            role: record.role,
            user_name: record.user_name,
            user_email: record.user_email,
            user_avatar_url: None,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceMemberListResponse {
    members: Vec<InstanceMemberView>,
    total: i64,
    limit: i64,
    offset: i64,
    has_more: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceUserSearchView {
    id: String,
    email: String,
    full_name: Option<String>,
}

impl From<InstanceUserSearchRecord> for InstanceUserSearchView {
    fn from(record: InstanceUserSearchRecord) -> Self {
        Self {
            id: record.id,
            email: record.email,
            full_name: record.full_name,
        }
    }
}

impl InstanceMemberListResponse {
    fn from_records(
        records: Vec<InstanceMemberRecord>,
        total: i64,
        limit: i64,
        offset: i64,
    ) -> Self {
        let has_more = offset.saturating_add(records.len() as i64) < total;
        Self {
            members: records.into_iter().map(InstanceMemberView::from).collect(),
            total,
            limit,
            offset,
            has_more,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceChannelView {
    id: String,
    instance_id: String,
    channel_type: String,
    name: String,
    config: Value,
    status: String,
    last_connected_at: Option<String>,
    created_at: String,
    updated_at: Option<String>,
    deleted_at: Option<String>,
}

impl From<InstanceChannelRecord> for InstanceChannelView {
    fn from(record: InstanceChannelRecord) -> Self {
        Self {
            id: record.id,
            instance_id: record.instance_id,
            channel_type: record.channel_type,
            name: record.name,
            config: record.config,
            status: record.status,
            last_connected_at: record.last_connected_at.map(iso8601),
            created_at: iso8601(record.created_at),
            updated_at: record.updated_at.map(iso8601),
            deleted_at: record.deleted_at.map(iso8601),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct InstanceChannelListResponse {
    items: Vec<InstanceChannelView>,
}

impl InstanceChannelListResponse {
    fn from_records(records: Vec<InstanceChannelRecord>) -> Self {
        Self {
            items: records.into_iter().map(InstanceChannelView::from).collect(),
        }
    }
}

impl InstanceListResponse {
    fn from_records(records: Vec<InstanceRecord>, total: i64, page: i64, page_size: i64) -> Self {
        Self {
            instances: records.into_iter().map(InstanceView::from).collect(),
            total,
            page,
            page_size,
        }
    }
}

fn sort_instances(records: &mut [InstanceRecord]) {
    records.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
}

fn sort_instance_channels(records: &mut [InstanceChannelRecord]) {
    records.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| left.id.cmp(&right.id))
    });
}

fn sort_instance_members(records: &mut [InstanceMemberRecord]) {
    records.sort_by(|left, right| {
        left.created_at
            .cmp(&right.created_at)
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

fn string_field(value: Option<&Value>) -> Option<String> {
    value.and_then(Value::as_str).map(str::to_string)
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64() != Some(0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn update_llm_config_value(current: Value, request: InstanceLlmConfigUpdateRequest) -> Value {
    let mut llm_cfg = current.as_object().cloned().unwrap_or_default();
    llm_cfg.insert(
        "provider_id".to_string(),
        request
            .provider_id
            .map(Value::String)
            .unwrap_or(Value::Null),
    );
    llm_cfg.insert(
        "model_name".to_string(),
        request.model_name.map(Value::String).unwrap_or(Value::Null),
    );
    if let Some(api_key_override) = request.api_key_override {
        llm_cfg.insert(
            "api_key_override".to_string(),
            Value::String(api_key_override),
        );
    } else if !llm_cfg.contains_key("api_key_override") {
        llm_cfg.insert("api_key_override".to_string(), Value::Null);
    }
    Value::Object(llm_cfg)
}

fn cmp_optional_string_nulls_last(
    left: &Option<String>,
    right: &Option<String>,
) -> std::cmp::Ordering {
    match (left, right) {
        (Some(left), Some(right)) => left.cmp(right),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => std::cmp::Ordering::Equal,
    }
}

#[derive(Debug)]
pub(crate) struct InstanceApiError {
    status: StatusCode,
    detail: String,
}

impl InstanceApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for InstanceApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn instance(id: &str, tenant_id: &str, created_at: DateTime<Utc>) -> InstanceRecord {
        InstanceRecord {
            id: id.to_string(),
            name: "Production Instance".to_string(),
            slug: "production-instance".to_string(),
            description: Some("Primary production runtime".to_string()),
            tenant_id: tenant_id.to_string(),
            cluster_id: Some("cluster_456".to_string()),
            namespace: Some("production".to_string()),
            image_version: "1.2.0".to_string(),
            replicas: 2,
            cpu_request: "200m".to_string(),
            cpu_limit: "1000m".to_string(),
            mem_request: "512Mi".to_string(),
            mem_limit: "1Gi".to_string(),
            service_type: "ClusterIP".to_string(),
            ingress_domain: Some("agents.example.test".to_string()),
            proxy_token: Some("proxy-token-redacted-shape".to_string()),
            env_vars: json!({"RUST_LOG": "info"}),
            quota_cpu: Some("2".to_string()),
            quota_memory: Some("4Gi".to_string()),
            quota_max_pods: Some(4),
            storage_class: Some("standard".to_string()),
            storage_size: Some("20Gi".to_string()),
            advanced_config: json!({"autoscale": true}),
            llm_providers: json!({"provider_id": "provider-1", "model_name": "gpt-4o-mini"}),
            pending_config: json!({"image_version": "1.3.0"}),
            available_replicas: 2,
            status: "running".to_string(),
            health_status: Some("healthy".to_string()),
            current_revision: 3,
            compute_provider: Some("kubernetes".to_string()),
            runtime: "default".to_string(),
            created_by: "user_123".to_string(),
            workspace_id: Some("workspace-1".to_string()),
            hex_position_q: Some(1),
            hex_position_r: Some(-1),
            agent_display_name: Some("Prod Agent".to_string()),
            agent_label: Some("prod".to_string()),
            theme_color: Some("#3366ff".to_string()),
            created_at,
            updated_at: Some(Utc.with_ymd_and_hms(2024, 1, 15, 12, 45, 0).unwrap()),
        }
    }

    fn channel(
        id: &str,
        instance_id: &str,
        created_at: DateTime<Utc>,
        deleted_at: Option<DateTime<Utc>>,
    ) -> InstanceChannelRecord {
        InstanceChannelRecord {
            id: id.to_string(),
            instance_id: instance_id.to_string(),
            channel_type: "feishu".to_string(),
            name: format!("Channel {id}"),
            config: json!({"webhook_url": "https://open.feishu.cn/hook/redacted"}),
            status: "connected".to_string(),
            last_connected_at: Some(Utc.with_ymd_and_hms(2024, 1, 15, 11, 0, 0).unwrap()),
            created_at,
            updated_at: Some(Utc.with_ymd_and_hms(2024, 1, 15, 11, 30, 0).unwrap()),
            deleted_at,
        }
    }

    fn member(
        id: &str,
        instance_id: &str,
        user_id: &str,
        created_at: DateTime<Utc>,
    ) -> InstanceMemberRecord {
        InstanceMemberRecord {
            id: id.to_string(),
            instance_id: instance_id.to_string(),
            user_id: user_id.to_string(),
            role: "viewer".to_string(),
            user_name: Some(format!("User {user_id}")),
            user_email: Some(format!("{user_id}@example.test")),
            created_at,
        }
    }

    fn search_user(id: &str, email: &str, full_name: Option<&str>) -> InstanceUserSearchRecord {
        InstanceUserSearchRecord {
            id: id.to_string(),
            email: email.to_string(),
            full_name: full_name.map(str::to_string),
        }
    }

    fn pending_config_request(config: Value) -> PendingConfigRequest {
        serde_json::from_value(json!({ "pending_config": config }))
            .expect("pending config request must deserialize")
    }

    fn config_update_request(
        env_vars: Value,
        advanced_config: Value,
        llm_providers: Value,
    ) -> InstanceConfigUpdateRequest {
        serde_json::from_value(json!({
            "env_vars": env_vars,
            "advanced_config": advanced_config,
            "llm_providers": llm_providers,
        }))
        .expect("config update request must deserialize")
    }

    fn llm_config_update_request(
        provider_id: Option<&str>,
        model_name: Option<&str>,
        api_key_override: Option<&str>,
    ) -> InstanceLlmConfigUpdateRequest {
        serde_json::from_value(json!({
            "provider_id": provider_id,
            "model_name": model_name,
            "api_key_override": api_key_override,
        }))
        .expect("llm config update request must deserialize")
    }

    fn member_create_request(
        instance_id: &str,
        user_id: &str,
        role: Option<&str>,
    ) -> InstanceMemberCreateRequest {
        let mut value = json!({
            "instance_id": instance_id,
            "user_id": user_id,
        });
        if let Some(role) = role {
            value["role"] = json!(role);
        }
        serde_json::from_value(value).expect("member create request must deserialize")
    }

    fn member_update_request(role: &str) -> InstanceMemberUpdateRequest {
        serde_json::from_value(json!({ "role": role }))
            .expect("member update request must deserialize")
    }

    #[test]
    fn list_query_validates_pagination() {
        let query = InstanceListQuery {
            page: Some(2),
            page_size: Some(25),
        }
        .validated()
        .expect("valid query");
        assert_eq!(query.page, 2);
        assert_eq!(query.page_size, 25);
        assert_eq!(query.offset, 25);

        let err = InstanceListQuery {
            page: Some(0),
            page_size: Some(20),
        }
        .validated()
        .expect_err("page zero should reject");
        assert_eq!(err.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[tokio::test]
    async fn dev_service_lists_and_details_current_tenant() {
        let old = instance(
            "instance-old",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 9, 30, 0).unwrap(),
        );
        let latest = instance(
            "instance-latest",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let other = instance(
            "instance-other",
            "tenant-2",
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 30, 0).unwrap(),
        );
        let service = DevInstanceService::new("tenant-1", vec![old, latest.clone(), other]);

        let list = service
            .list_instances(
                "user-1",
                ValidatedInstanceListQuery {
                    page: 1,
                    page_size: 10,
                    offset: 0,
                },
            )
            .await
            .expect("list instances");
        assert_eq!(list.total, 2);
        assert_eq!(list.instances[0].id, "instance-latest");

        let detail = service
            .get_instance("user-1", "instance-latest")
            .await
            .expect("instance detail");
        assert_eq!(detail.id, latest.id);
        assert_eq!(detail.tenant_id, "tenant-1");
    }

    #[tokio::test]
    async fn dev_service_lists_instance_channels() {
        let visible_instance = instance(
            "instance-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let hidden_instance = instance(
            "instance-2",
            "tenant-2",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 35, 0).unwrap(),
        );
        let old = channel(
            "channel-old",
            "instance-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 0, 0).unwrap(),
            None,
        );
        let latest = channel(
            "channel-latest",
            "instance-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
            None,
        );
        let deleted = channel(
            "channel-deleted",
            "instance-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 0, 0).unwrap(),
            Some(Utc.with_ymd_and_hms(2024, 1, 15, 11, 1, 0).unwrap()),
        );
        let other = channel(
            "channel-other",
            "instance-2",
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 30, 0).unwrap(),
            None,
        );
        let service = DevInstanceService::with_channels(
            "tenant-1",
            vec![visible_instance, hidden_instance],
            vec![old, latest, deleted, other],
        );

        let list = service
            .list_instance_channels("user-1", "instance-1")
            .await
            .expect("list channels");
        assert_eq!(
            list.items
                .iter()
                .map(|channel| channel.id.as_str())
                .collect::<Vec<_>>(),
            vec!["channel-latest", "channel-old"]
        );

        let err = service
            .list_instance_channels("user-1", "instance-2")
            .await
            .expect_err("wrong tenant should reject");
        assert_eq!(err.status, StatusCode::FORBIDDEN);
    }

    #[tokio::test]
    async fn dev_service_lists_instance_members() {
        let visible_instance = instance(
            "instance-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let other_instance = instance(
            "instance-2",
            "tenant-2",
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 30, 0).unwrap(),
        );
        let service = DevInstanceService::with_members(
            "tenant-1",
            vec![visible_instance, other_instance],
            vec![
                member(
                    "member-old",
                    "instance-1",
                    "user-old",
                    Utc.with_ymd_and_hms(2024, 1, 15, 10, 0, 0).unwrap(),
                ),
                member(
                    "member-latest",
                    "instance-1",
                    "user-latest",
                    Utc.with_ymd_and_hms(2024, 1, 15, 11, 0, 0).unwrap(),
                ),
                member(
                    "member-other",
                    "instance-2",
                    "user-other",
                    Utc.with_ymd_and_hms(2024, 1, 15, 12, 0, 0).unwrap(),
                ),
            ],
        );

        let response = service
            .list_instance_members(
                "user-1",
                "instance-1",
                ValidatedInstanceMemberListQuery {
                    limit: 1,
                    offset: 1,
                },
            )
            .await
            .expect("list members");
        assert_eq!(response.total, 2);
        assert_eq!(response.members[0].id, "member-latest");
        assert!(!response.has_more);

        let err = service
            .list_instance_members(
                "user-1",
                "instance-2",
                ValidatedInstanceMemberListQuery {
                    limit: 25,
                    offset: 0,
                },
            )
            .await
            .expect_err("wrong tenant should be hidden");
        assert_eq!(err.status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn dev_service_mutates_instance_members() {
        let visible_instance = instance(
            "instance-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let mut service = DevInstanceService::with_members(
            "tenant-1",
            vec![visible_instance],
            vec![member(
                "member-existing",
                "instance-1",
                "user-existing",
                Utc.with_ymd_and_hms(2024, 1, 15, 10, 0, 0).unwrap(),
            )],
        );
        service.member_users = vec![search_user(
            "user-new",
            "new@example.test",
            Some("New User"),
        )];

        let created = service
            .add_instance_member(
                "user-1",
                "instance-1",
                member_create_request("ignored-instance-body", "user-new", None),
            )
            .await
            .expect("add member");
        assert_eq!(created.role, "viewer");
        assert_eq!(created.user_email.as_deref(), Some("new@example.test"));

        let duplicate = service
            .add_instance_member(
                "user-1",
                "instance-1",
                member_create_request("instance-1", "user-existing", Some("admin")),
            )
            .await
            .expect_err("duplicate member should reject");
        assert_eq!(duplicate.status, StatusCode::BAD_REQUEST);

        let updated = service
            .update_instance_member_role(
                "user-1",
                "instance-1",
                "member-existing",
                member_update_request("editor"),
            )
            .await
            .expect("update role");
        assert_eq!(updated.role, "editor");

        service
            .remove_instance_member("user-1", "instance-1", "user-existing")
            .await
            .expect("remove member");

        let invalid_role = service
            .update_instance_member_role(
                "user-1",
                "instance-1",
                "member-existing",
                member_update_request("owner"),
            )
            .await
            .expect_err("invalid update role maps to member not found");
        assert_eq!(invalid_role.status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn dev_service_searches_instance_member_users() {
        let instance = instance(
            "instance-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let service = DevInstanceService::with_member_users(
            "tenant-1",
            vec![instance],
            vec![
                search_user("user-b", "beta@example.test", Some("Beta User")),
                search_user("user-a", "alpha@example.test", Some("Alpha User")),
                search_user("user-c", "charlie@example.test", None),
            ],
        );

        let users = service
            .search_instance_member_users(
                "user-1",
                "instance-1",
                ValidatedInstanceMemberUserSearchQuery {
                    q: "example".to_string(),
                    limit: 2,
                },
            )
            .await
            .expect("search users");
        assert_eq!(
            users
                .iter()
                .map(|user| user.id.as_str())
                .collect::<Vec<_>>(),
            vec!["user-a", "user-b"]
        );
    }

    #[tokio::test]
    async fn dev_service_saves_pending_config_for_current_tenant() {
        let visible_instance = instance(
            "instance-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let other_instance = instance(
            "instance-2",
            "tenant-2",
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 30, 0).unwrap(),
        );
        let service = DevInstanceService::new("tenant-1", vec![visible_instance, other_instance]);

        let response = service
            .save_pending_config(
                "user-1",
                "instance-1",
                pending_config_request(json!({"image_version": "2.0.0", "replicas": 3})),
            )
            .await
            .expect("save pending config");
        assert_eq!(
            response.pending_config,
            json!({"image_version": "2.0.0", "replicas": 3})
        );

        let err = service
            .save_pending_config(
                "user-1",
                "instance-2",
                pending_config_request(json!({"image_version": "2.0.0"})),
            )
            .await
            .expect_err("wrong tenant should be hidden");
        assert_eq!(err.status, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn dev_service_updates_instance_config_and_llm_config() {
        let visible_instance = instance(
            "instance-1",
            "tenant-1",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        let other_instance = instance(
            "instance-2",
            "tenant-2",
            Utc.with_ymd_and_hms(2024, 1, 15, 11, 30, 0).unwrap(),
        );
        let service = DevInstanceService::new("tenant-1", vec![visible_instance, other_instance]);

        let config = service
            .update_instance_config(
                "user-1",
                "instance-1",
                config_update_request(
                    json!({"RUST_LOG": "debug"}),
                    json!({"autoscale": false}),
                    json!({"provider_id": "provider-2"}),
                ),
            )
            .await
            .expect("update config");
        assert_eq!(config.env_vars, json!({"RUST_LOG": "debug"}));
        assert_eq!(config.advanced_config, json!({"autoscale": false}));
        assert_eq!(config.llm_providers, json!({"provider_id": "provider-2"}));

        let llm = service
            .update_instance_llm_config(
                "user-1",
                "instance-1",
                llm_config_update_request(Some("provider-2"), Some("gpt-4o"), Some("secret")),
            )
            .await
            .expect("update llm config");
        assert_eq!(llm.provider_id.as_deref(), Some("provider-2"));
        assert_eq!(llm.model_name.as_deref(), Some("gpt-4o"));
        assert!(llm.has_api_key_override);

        let err = service
            .update_instance_config(
                "user-1",
                "instance-2",
                config_update_request(json!({}), json!({}), json!({})),
            )
            .await
            .expect_err("wrong tenant should be hidden");
        assert_eq!(err.status, StatusCode::NOT_FOUND);
    }

    #[test]
    fn instance_list_response_matches_golden() {
        let response = InstanceListResponse::from_records(
            vec![instance(
                "inst_550e8400",
                "tenant_123",
                Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
            )],
            1,
            1,
            20,
        );
        let value = serde_json::to_value(response).expect("instance list must serialize");
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/instance_list_response.json"))
                .expect("instance list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn instance_config_response_matches_golden() {
        let response = InstanceConfigResponse {
            env_vars: json!({"RUST_LOG": "info"}),
            advanced_config: json!({"autoscale": true}),
            llm_providers: json!({"provider_id": "provider-1", "model_name": "gpt-4o-mini"}),
        };
        let value = serde_json::to_value(response).expect("config response must serialize");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_config_response.json"
        ))
        .expect("instance config golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn instance_llm_config_response_matches_golden() {
        let response = InstanceLlmConfigResponse {
            provider_id: Some("provider-1".to_string()),
            model_name: Some("gpt-4o-mini".to_string()),
            has_api_key_override: false,
        };
        let value = serde_json::to_value(response).expect("llm config response must serialize");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_llm_config_response.json"
        ))
        .expect("instance llm config golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn instance_llm_config_override_response_matches_golden() {
        let response = InstanceLlmConfigResponse::from_value(&json!({
            "provider_id": "provider-2",
            "model_name": "gpt-4o",
            "api_key_override": "secret"
        }));
        let value = serde_json::to_value(response).expect("llm override response serializes");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_llm_config_override_response.json"
        ))
        .expect("instance llm override golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn instance_member_list_response_matches_golden() {
        let response = InstanceMemberListResponse::from_records(
            vec![member(
                "member_550e8400",
                "inst_550e8400",
                "user_123",
                Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
            )],
            1,
            25,
            0,
        );
        let value = serde_json::to_value(response).expect("member list response must serialize");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_member_list_response.json"
        ))
        .expect("instance member list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn instance_member_response_matches_golden() {
        let value = serde_json::to_value(InstanceMemberView::from(member(
            "member_550e8400",
            "inst_550e8400",
            "user_123",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        )))
        .expect("member response must serialize");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_member_response.json"
        ))
        .expect("instance member golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn instance_pending_config_response_matches_golden() {
        let mut record = instance(
            "inst_550e8400",
            "tenant_123",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
        );
        record.pending_config = json!({"image_version": "2.0.0", "replicas": 3});
        let value =
            serde_json::to_value(InstanceView::from(record)).expect("instance view serializes");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_pending_config_response.json"
        ))
        .expect("instance pending config golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn instance_user_search_response_matches_golden() {
        let response = vec![InstanceUserSearchView::from(search_user(
            "user_123",
            "user@example.test",
            Some("User Example"),
        ))];
        let value = serde_json::to_value(response).expect("user search response must serialize");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_user_search_response.json"
        ))
        .expect("instance user search golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn llm_config_uses_python_bool_semantics_for_api_key_override() {
        assert!(!json_truthy(&Value::Null));
        assert!(!json_truthy(&json!("")));
        assert!(json_truthy(&json!("secret")));
    }

    #[test]
    fn instance_channel_list_response_matches_golden() {
        let response = InstanceChannelListResponse::from_records(vec![channel(
            "channel_550e8400",
            "inst_550e8400",
            Utc.with_ymd_and_hms(2024, 1, 15, 10, 30, 0).unwrap(),
            None,
        )]);
        let value = serde_json::to_value(response).expect("channel list must serialize");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/instance_channel_list_response.json"
        ))
        .expect("instance channel list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }
}
