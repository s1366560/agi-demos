#[cfg(test)]
use std::sync::Arc;

use async_trait::async_trait;
use axum::http::StatusCode;
use serde_json::json;

use agistack_adapters_postgres::{
    normalize_email, ProjectDashboardStatsRecord, ProjectUpdatePatch, TenantUpdatePatch,
};
use agistack_adapters_redis::DeviceGrant;
use agistack_adapters_secrets::generate_api_key;

use super::device_grants::{
    create_device_code_with_store, normalize_device_user_code, poll_device_token_from_store,
};
#[cfg(test)]
use super::InMemoryDeviceGrantStore;
use super::{
    clamp_limit_offset, clamp_pagination, default_graph_config, default_memory_rules,
    default_project_member_role, default_tenant_member_role, is_valid_agent_conversation_mode,
    is_valid_project_member_role, is_valid_tenant_member_role, normalize_backend_store_id,
    project_graph_config_for_write, project_memory_rules_for_write, sandbox_config, unprocessable,
    BackendStoreSummary, DeviceApproveView, DeviceCodeView, DeviceTokenView, IdentityError,
    IdentityService, InvitationListView, InvitationVerifyView, InvitationView, LoginOutcome,
    ProjectCreateInput, ProjectListInput, ProjectMemberMutationView, ProjectMemberView,
    ProjectMembersView, ProjectPage, ProjectStatsView, ProjectView, SharedDeviceGrantStore,
    TenantMemberMutationView, TenantPage, TenantView, DEVICE_CODE_TTL_SECS,
};

// ---- offline dev impl -----------------------------------------------------

/// Offline identity service: mints a fake `ms_sk_` key for any non-empty
/// credentials and serves a single deterministic dev tenant. Never used when
/// `DATABASE_URL` is set. Keeps `cargo run`/tests keyless and DB-free, exactly
/// like [`crate::auth::DevAuthenticator`].
pub struct DevIdentityService {
    dev_user_id: String,
    device_grants: SharedDeviceGrantStore,
}

impl DevIdentityService {
    #[cfg(test)]
    pub fn new(dev_user_id: impl Into<String>) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            device_grants: Arc::new(InMemoryDeviceGrantStore::new()),
        }
    }

    pub fn with_device_grants(
        dev_user_id: impl Into<String>,
        device_grants: SharedDeviceGrantStore,
    ) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            device_grants,
        }
    }

    /// The single deterministic tenant the dev service exposes.
    fn dev_tenant(&self) -> TenantView {
        TenantView {
            id: "dev-tenant".to_string(),
            name: "Dev Tenant".to_string(),
            slug: "dev".to_string(),
            description: None,
            owner_id: self.dev_user_id.clone(),
            plan: "free".to_string(),
            max_projects: 10,
            max_users: 5,
            max_storage: 1_073_741_824,
            created_at: "1970-01-01T00:00:00Z".to_string(),
            updated_at: None,
        }
    }

    fn dev_project(&self) -> ProjectView {
        ProjectView {
            id: "dev-project".to_string(),
            tenant_id: "dev-tenant".to_string(),
            name: "Default project".to_string(),
            description: None,
            owner_id: self.dev_user_id.clone(),
            member_ids: vec![self.dev_user_id.clone()],
            memory_rules: default_memory_rules(),
            graph_config: default_graph_config(),
            graph_store_id: None,
            retrieval_store_id: None,
            graph_store: Some(BackendStoreSummary {
                id: "__env_neo4j__".to_string(),
                name: "neo4j (env)".to_string(),
                engine_type: "neo4j".to_string(),
                source: "env".to_string(),
                status: "connected".to_string(),
            }),
            retrieval_store: Some(BackendStoreSummary {
                id: "__env_memstack_pgvector__".to_string(),
                name: "memstack_pgvector (env)".to_string(),
                engine_type: "memstack_pgvector".to_string(),
                source: "env".to_string(),
                status: "connected".to_string(),
            }),
            sandbox_config: json!({
                "sandbox_type": "cloud",
                "local_config": null
            }),
            is_public: false,
            agent_conversation_mode: "single_agent".to_string(),
            created_at: "1970-01-01T00:00:00Z".to_string(),
            updated_at: None,
            stats: Some(ProjectStatsView {
                memory_count: 0,
                conversation_count: 0,
                storage_used: 0,
                storage_limit: 1_073_741_824,
                node_count: 0,
                member_count: 1,
                collaborators: 0,
                active_nodes: 0,
                last_active: None,
                system_status: None,
                recent_activity: Vec::new(),
            }),
        }
    }

    fn dev_invitation(&self) -> InvitationView {
        InvitationView {
            id: "dev-invitation".to_string(),
            tenant_id: "dev-tenant".to_string(),
            email: "invitee@example.test".to_string(),
            role: "member".to_string(),
            status: "pending".to_string(),
            invited_by: self.dev_user_id.clone(),
            expires_at: "1970-01-08T00:00:00Z".to_string(),
            created_at: "1970-01-01T00:00:00Z".to_string(),
        }
    }
}

#[async_trait]
impl IdentityService for DevIdentityService {
    async fn login(
        &self,
        username: &str,
        password: &str,
        _now_ms: i64,
    ) -> Result<LoginOutcome, IdentityError> {
        // Offline: accept any non-empty credentials so the flow is exercisable
        // without a database; reject empties to keep the error path testable.
        if username.is_empty() || password.is_empty() {
            return Err(IdentityError::unauthorized(
                "Incorrect username or password",
                true,
            ));
        }
        Ok(LoginOutcome {
            access_token: generate_api_key(),
            token_type: "bearer".to_string(),
            must_change_password: false,
        })
    }

    async fn create_device_code(&self) -> Result<DeviceCodeView, IdentityError> {
        create_device_code_with_store(&*self.device_grants).await
    }

    async fn approve_device_code(
        &self,
        user_id: &str,
        user_code: &str,
        _now_ms: i64,
    ) -> Result<DeviceApproveView, IdentityError> {
        let user_code = normalize_device_user_code(user_code);
        if user_code.is_empty() {
            return Err(IdentityError::bad_request("user_code required"));
        }
        let device_code = self
            .device_grants
            .device_code_for_user_code(&user_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::not_found("user_code expired or unknown"))?;
        let grant = self
            .device_grants
            .get(&device_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::gone("device code expired"))?;
        if grant.status != "pending" {
            return Err(IdentityError::conflict(
                "Device code has already been handled",
            ));
        }

        let approved = DeviceGrant::approved(grant.user_code, user_id, generate_api_key());
        self.device_grants
            .save_preserving_ttl(&device_code, &approved, DEVICE_CODE_TTL_SECS)
            .await
            .map_err(IdentityError::internal)?;
        Ok(DeviceApproveView {
            status: "approved".to_string(),
        })
    }

    async fn poll_device_token(&self, device_code: &str) -> Result<DeviceTokenView, IdentityError> {
        poll_device_token_from_store(&*self.device_grants, device_code).await
    }

    async fn list_tenants(
        &self,
        _user_id: &str,
        search: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<TenantPage, IdentityError> {
        let (page, page_size) = clamp_pagination(page, page_size);
        // The single dev tenant matches when unfiltered or when the term is a
        // substring of its name/slug.
        let matches = match search {
            None => true,
            Some(term) => {
                let t = term.to_lowercase();
                "dev tenant".contains(&t) || "dev".contains(&t)
            }
        };
        let all = if matches {
            vec![self.dev_tenant()]
        } else {
            vec![]
        };
        let total = all.len() as i64;
        let start = ((page - 1) * page_size).min(total);
        let tenants = all
            .into_iter()
            .skip(start as usize)
            .take(page_size as usize)
            .collect();
        Ok(TenantPage {
            tenants,
            total,
            page,
            page_size,
        })
    }

    async fn get_tenant(
        &self,
        _user_id: &str,
        tenant_id_or_slug: &str,
    ) -> Result<TenantView, IdentityError> {
        let dev = self.dev_tenant();
        if tenant_id_or_slug == dev.id || tenant_id_or_slug == dev.slug {
            Ok(dev)
        } else {
            Err(IdentityError::not_found("Tenant not found"))
        }
    }

    async fn create_tenant(
        &self,
        user_id: &str,
        name: &str,
        description: Option<&str>,
    ) -> Result<TenantView, IdentityError> {
        let mut tenant = self.dev_tenant();
        tenant.id = "dev-created-tenant".to_string();
        tenant.name = name.to_string();
        tenant.slug = name.to_lowercase().replace(' ', "-");
        tenant.description = description.map(str::to_string);
        tenant.owner_id = user_id.to_string();
        Ok(tenant)
    }

    async fn update_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
        patch: TenantUpdatePatch,
    ) -> Result<TenantView, IdentityError> {
        let mut tenant = self.dev_tenant();
        if tenant_id != tenant.id || user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can update tenant",
            ));
        }
        if let Some(name) = patch.name {
            tenant.name = name;
        }
        if let Some(description) = patch.description {
            tenant.description = description;
        }
        if let Some(plan) = patch.plan {
            tenant.plan = plan;
        }
        if let Some(max_projects) = patch.max_projects {
            tenant.max_projects = max_projects;
        }
        if let Some(max_users) = patch.max_users {
            tenant.max_users = max_users;
        }
        if let Some(max_storage) = patch.max_storage {
            tenant.max_storage = max_storage;
        }
        tenant.updated_at = Some("1970-01-01T00:00:00Z".to_string());
        Ok(tenant)
    }

    async fn delete_tenant(&self, user_id: &str, tenant_id: &str) -> Result<(), IdentityError> {
        if tenant_id != "dev-tenant" || user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can delete tenant",
            ));
        }
        Ok(())
    }

    async fn add_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        let role = default_tenant_member_role(role);
        if !is_valid_tenant_member_role(&role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can add members",
            ));
        }
        if target_user_id == self.dev_user_id {
            return Err(IdentityError::bad_request(
                "User is already a member of this tenant",
            ));
        }
        Ok(TenantMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    async fn update_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        if !is_valid_tenant_member_role(role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can update member roles",
            ));
        }
        if target_user_id == self.dev_user_id && role != "owner" {
            return Err(IdentityError::bad_request(
                "Cannot change tenant owner role",
            ));
        }
        Ok(TenantMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    async fn remove_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove tenant owner"));
        }
        Ok(())
    }

    async fn list_projects(
        &self,
        _user_id: &str,
        input: ProjectListInput<'_>,
    ) -> Result<ProjectPage, IdentityError> {
        let ProjectListInput {
            tenant_id,
            search,
            visibility,
            owner_id,
            page,
            page_size,
        } = input;
        let (page, page_size) = clamp_pagination(page, page_size);
        let project = self.dev_project();
        let search_matches = search
            .map(|term| {
                let term = term.to_lowercase();
                project.id.to_lowercase().contains(&term)
                    || project.name.to_lowercase().contains(&term)
                    || project.owner_id.to_lowercase().contains(&term)
            })
            .unwrap_or(true);
        let tenant_matches = tenant_id
            .map(|tenant| tenant == project.tenant_id)
            .unwrap_or(true);
        let owner_matches = owner_id
            .map(|owner| owner == project.owner_id)
            .unwrap_or(true);
        let visibility_matches = match visibility {
            "public" => project.is_public,
            "private" => !project.is_public,
            _ => true,
        };
        let all = if search_matches && tenant_matches && owner_matches && visibility_matches {
            vec![project]
        } else {
            vec![]
        };
        let total = all.len() as i64;
        let start = ((page - 1) * page_size).min(total);
        Ok(ProjectPage {
            projects: all
                .into_iter()
                .skip(start as usize)
                .take(page_size as usize)
                .collect(),
            total,
            page,
            page_size,
            owner_ids: if total == 0 {
                Vec::new()
            } else {
                vec![self.dev_user_id.clone()]
            },
        })
    }

    async fn get_project(
        &self,
        _user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<ProjectView, IdentityError> {
        let project = self.dev_project();
        if project_id != project.id {
            return Err(IdentityError::forbidden("Access denied to project"));
        }
        if tenant_id
            .map(|tenant| tenant != project.tenant_id)
            .unwrap_or(false)
        {
            return Err(IdentityError::not_found(
                "Project not found in requested tenant",
            ));
        }
        Ok(project)
    }

    async fn create_project(
        &self,
        user_id: &str,
        input: ProjectCreateInput,
    ) -> Result<ProjectView, IdentityError> {
        if user_id != self.dev_user_id || input.tenant_id != "dev-tenant" {
            return Err(IdentityError::forbidden(
                "User does not have permission to create projects in this tenant",
            ));
        }
        if !is_valid_agent_conversation_mode(&input.agent_conversation_mode) {
            return Err(unprocessable("Invalid agent_conversation_mode"));
        }
        let mut project = self.dev_project();
        project.id = "dev-created-project".to_string();
        project.name = input.name;
        project.description = input.description;
        project.memory_rules = project_memory_rules_for_write(input.memory_rules);
        project.graph_config = project_graph_config_for_write(input.graph_config);
        project.graph_store_id = normalize_backend_store_id(input.graph_store_id.as_deref());
        project.retrieval_store_id =
            normalize_backend_store_id(input.retrieval_store_id.as_deref());
        project.is_public = input.is_public;
        project.agent_conversation_mode = input.agent_conversation_mode;
        Ok(project)
    }

    async fn update_project(
        &self,
        user_id: &str,
        project_id: &str,
        patch: ProjectUpdatePatch,
    ) -> Result<ProjectView, IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update project",
            ));
        }
        if let Some(mode) = patch.agent_conversation_mode.as_deref() {
            if !is_valid_agent_conversation_mode(mode) {
                return Err(unprocessable("Invalid agent_conversation_mode"));
            }
        }
        let mut project = self.dev_project();
        if let Some(name) = patch.name {
            project.name = name;
        }
        if let Some(description) = patch.description {
            project.description = description;
        }
        if let Some(memory_rules) = patch.memory_rules {
            project.memory_rules = project_memory_rules_for_write(Some(memory_rules));
        }
        if let Some(graph_config) = patch.graph_config {
            project.graph_config = project_graph_config_for_write(Some(graph_config));
        }
        if let Some(graph_store_id) = patch.graph_store_id {
            project.graph_store_id = graph_store_id;
        }
        if let Some(retrieval_store_id) = patch.retrieval_store_id {
            project.retrieval_store_id = retrieval_store_id;
        }
        if let Some(raw_sandbox_config) = patch.sandbox_config {
            project.sandbox_config = sandbox_config("cloud", raw_sandbox_config);
        }
        if let Some(is_public) = patch.is_public {
            project.is_public = is_public;
        }
        if let Some(mode) = patch.agent_conversation_mode {
            project.agent_conversation_mode = mode;
        }
        project.updated_at = Some("1970-01-01T00:00:00Z".to_string());
        Ok(project)
    }

    async fn delete_project(&self, user_id: &str, project_id: &str) -> Result<(), IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner can delete project",
            ));
        }
        Ok(())
    }

    async fn get_project_stats(
        &self,
        _user_id: &str,
        project_id: &str,
        now_ms: i64,
    ) -> Result<ProjectStatsView, IdentityError> {
        if project_id != "dev-project" {
            return Err(IdentityError::forbidden("Access denied to project"));
        }
        Ok(ProjectStatsView::dashboard(
            ProjectDashboardStatsRecord {
                memory_count: 0,
                conversation_count: 0,
                storage_used: 0,
                member_count: 1,
                recent_activity: Vec::new(),
            },
            now_ms,
        ))
    }

    async fn list_project_members(
        &self,
        _user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMembersView, IdentityError> {
        if project_id != "dev-project" {
            return Err(IdentityError {
                status: StatusCode::UNPROCESSABLE_ENTITY,
                detail: "Invalid UUID".to_string(),
                detail_value: None,
                www_authenticate: false,
            });
        }
        Ok(ProjectMembersView {
            members: vec![ProjectMemberView {
                user_id: self.dev_user_id.clone(),
                email: "dev@example.test".to_string(),
                name: Some("Dev User".to_string()),
                role: "owner".to_string(),
                permissions: json!({"admin": true, "read": true, "write": true, "delete": true}),
                created_at: "1970-01-01T00:00:00Z".to_string(),
            }],
            total: 1,
        })
    }

    async fn add_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        let role = default_project_member_role(role);
        if !is_valid_project_member_role(&role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can add members",
            ));
        }
        if target_user_id == self.dev_user_id {
            return Err(IdentityError::bad_request(
                "User is already a member of this project",
            ));
        }
        Ok(ProjectMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    async fn update_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update members",
            ));
        }
        if target_user_id == self.dev_user_id {
            return Err(IdentityError::bad_request(
                "Cannot update project owner role",
            ));
        }
        Ok(ProjectMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    async fn remove_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove project owner"));
        }
        Ok(())
    }

    async fn create_invitation(
        &self,
        _user_id: &str,
        tenant_id: &str,
        email: &str,
        role: &str,
        _message: Option<&str>,
        _now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        let mut invitation = self.dev_invitation();
        invitation.email = normalize_email(email);
        invitation.role = if role.trim().is_empty() {
            "member".to_string()
        } else {
            role.to_string()
        };
        Ok(invitation)
    }

    async fn list_invitations(
        &self,
        _user_id: &str,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<InvitationListView, IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        let (limit, offset) = clamp_limit_offset(limit, offset);
        Ok(InvitationListView {
            items: if offset == 0 {
                vec![self.dev_invitation()]
            } else {
                Vec::new()
            },
            total: 1,
            limit,
            offset,
        })
    }

    async fn cancel_invitation(
        &self,
        _user_id: &str,
        tenant_id: &str,
        invitation_id: &str,
        _now_ms: i64,
    ) -> Result<(), IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if invitation_id == "dev-invitation" {
            Ok(())
        } else {
            Err(IdentityError::not_found("Invitation not found"))
        }
    }

    async fn verify_invitation(
        &self,
        token: &str,
        _now_ms: i64,
    ) -> Result<InvitationVerifyView, IdentityError> {
        if token == "dev-token" {
            Ok(InvitationVerifyView {
                valid: true,
                email: Some("invitee@example.test".to_string()),
                tenant_id: Some("dev-tenant".to_string()),
                role: Some("member".to_string()),
                expires_at: Some("1970-01-08T00:00:00Z".to_string()),
            })
        } else {
            Ok(InvitationVerifyView::invalid())
        }
    }

    async fn accept_invitation(
        &self,
        token: &str,
        _user_id: &str,
        _now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        if token != "dev-token" {
            return Err(IdentityError::bad_request("Invalid or expired invitation"));
        }
        let mut invitation = self.dev_invitation();
        invitation.status = "accepted".to_string();
        Ok(invitation)
    }
}
