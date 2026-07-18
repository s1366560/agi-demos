use super::*;

/// Production identity service over the shared Python `users`/`api_keys`/
/// `tenants` tables (`agistack-adapters-postgres` + `agistack-adapters-secrets`).
pub struct PgIdentityService {
    pub(super) users: PgUserStore,
    pub(super) tenants: PgTenantRepository,
    pub(super) projects: PgProjectReadRepository,
    pub(super) workspace_contexts: PgWorkspaceContextRepository,
    pub(super) invitations: PgInvitationRepository,
    pub(super) email: Arc<dyn EmailSender>,
    pub(super) device_grants: SharedDeviceGrantStore,
    pub(super) invitation_base_url: String,
}

pub struct PgIdentityRepositories {
    users: PgUserStore,
    tenants: PgTenantRepository,
    projects: PgProjectReadRepository,
    workspace_contexts: PgWorkspaceContextRepository,
    invitations: PgInvitationRepository,
}

impl PgIdentityRepositories {
    pub fn new(
        users: PgUserStore,
        tenants: PgTenantRepository,
        projects: PgProjectReadRepository,
        workspace_contexts: PgWorkspaceContextRepository,
        invitations: PgInvitationRepository,
    ) -> Self {
        Self {
            users,
            tenants,
            projects,
            workspace_contexts,
            invitations,
        }
    }
}

impl PgIdentityService {
    pub fn new(
        repositories: PgIdentityRepositories,
        email: Arc<dyn EmailSender>,
        device_grants: SharedDeviceGrantStore,
        invitation_base_url: impl Into<String>,
    ) -> Self {
        Self {
            users: repositories.users,
            tenants: repositories.tenants,
            projects: repositories.projects,
            workspace_contexts: repositories.workspace_contexts,
            invitations: repositories.invitations,
            email,
            device_grants,
            invitation_base_url: invitation_base_url.into(),
        }
    }

    pub(super) async fn require_invitation_admin(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<(), IdentityError> {
        match self
            .invitations
            .tenant_admin_status(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            TenantAdminStatus::Authorized => Ok(()),
            TenantAdminStatus::TenantNotFound => Err(IdentityError::not_found("Tenant not found")),
            TenantAdminStatus::NotMember => Err(IdentityError::forbidden("Tenant access required")),
            TenantAdminStatus::NotAdmin => Err(IdentityError::forbidden("Admin access required")),
        }
    }

    pub(super) async fn valid_invitation_at(
        &self,
        token: &str,
        now_ms: i64,
    ) -> Result<Option<InvitationRecord>, IdentityError> {
        let Some(record) = self
            .invitations
            .find_by_token(token)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Ok(None);
        };
        if record.status != "pending" || record.deleted_at.is_some() {
            return Ok(None);
        }
        if record.expires_at < ms_to_datetime(now_ms) {
            self.invitations
                .update_status(&record.id, "expired", None)
                .await
                .map_err(IdentityError::internal)?;
            return Ok(None);
        }
        Ok(Some(record))
    }

    pub(super) async fn send_invitation_email(
        &self,
        record: &InvitationRecord,
        message: Option<&str>,
    ) -> Result<(), IdentityError> {
        let link = format!(
            "{}/api/v1/invitations/accept/{}",
            self.invitation_base_url.trim_end_matches('/'),
            record.token
        );
        let extra = message
            .map(str::trim)
            .filter(|m| !m.is_empty())
            .map(|m| format!("\n\nMessage from inviter:\n{m}"))
            .unwrap_or_default();
        let body_text = format!(
            "You have been invited to tenant {} as {}.\n\nAccept the invitation: {}{}",
            record.tenant_id, record.role, link, extra
        );
        let body_html = format!(
            "<p>You have been invited to tenant <b>{}</b> as <b>{}</b>.</p><p><a href=\"{}\">Accept the invitation</a></p>{}",
            escape_html(&record.tenant_id),
            escape_html(&record.role),
            escape_html(&link),
            message
                .map(str::trim)
                .filter(|m| !m.is_empty())
                .map(|m| format!("<p>{}</p>", escape_html(m)))
                .unwrap_or_default()
        );
        self.email
            .send(&EmailMessage {
                from: "MemStack <no-reply@memstack.ai>".to_string(),
                to: vec![record.email.clone()],
                subject: "You have been invited to MemStack".to_string(),
                body_text,
                body_html: Some(body_html),
            })
            .await
            .map_err(IdentityError::internal)
    }

    pub(super) async fn normalize_graph_store_binding(
        &self,
        tenant_id: &str,
        store_id: Option<&str>,
    ) -> Result<Option<String>, IdentityError> {
        let Some(store_id) = normalize_backend_store_id(store_id) else {
            return Ok(None);
        };
        if !self
            .projects
            .graph_store_exists(tenant_id, &store_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::bad_request(
                "Graph store not found in tenant",
            ));
        }
        Ok(Some(store_id))
    }

    pub(super) async fn normalize_retrieval_store_binding(
        &self,
        tenant_id: &str,
        store_id: Option<&str>,
    ) -> Result<Option<String>, IdentityError> {
        let Some(store_id) = normalize_backend_store_id(store_id) else {
            return Ok(None);
        };
        if !self
            .projects
            .retrieval_store_exists(tenant_id, &store_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::bad_request(
                "Retrieval store not found in tenant",
            ));
        }
        Ok(Some(store_id))
    }
}

#[async_trait]
impl IdentityService for PgIdentityService {
    async fn login(
        &self,
        username: &str,
        password: &str,
        now_ms: i64,
    ) -> Result<LoginOutcome, IdentityError> {
        self.pg_login(username, password, now_ms).await
    }

    async fn current_user(&self, user_id: &str) -> Result<CurrentUserView, IdentityError> {
        self.users
            .find_current_user_by_id(user_id)
            .await
            .map_err(IdentityError::internal)?
            .map(CurrentUserView::from)
            .ok_or_else(|| IdentityError::not_found("User not found"))
    }

    async fn workspace_context(
        &self,
        user_id: &str,
        now_ms: i64,
    ) -> Result<WorkspaceContextResponseView, IdentityError> {
        self.workspace_contexts
            .get_or_initialize(user_id, ms_to_datetime(now_ms))
            .await
            .map(WorkspaceContextResponseView::from)
            .map_err(workspace_context_error)
    }

    async fn switch_workspace_context(
        &self,
        user_id: &str,
        actor_api_key_id: Option<&str>,
        input: WorkspaceContextSwitchInput,
        now_ms: i64,
    ) -> Result<WorkspaceContextSwitchOutcomeView, IdentityError> {
        validate_workspace_context_input(&input)?;
        let request = agistack_adapters_postgres::WorkspaceContextSwitchRequest {
            tenant_id: input.tenant_id,
            project_id: input.project_id,
            expected_revision: input.expected_revision,
            idempotency_key: input.idempotency_key,
        };
        self.workspace_contexts
            .switch(user_id, actor_api_key_id, &request, ms_to_datetime(now_ms))
            .await
            .map(WorkspaceContextSwitchOutcomeView::from)
            .map_err(workspace_context_error)
    }

    async fn create_device_code(&self) -> Result<DeviceCodeView, IdentityError> {
        self.pg_create_device_code().await
    }

    async fn approve_device_code(
        &self,
        user_id: &str,
        user_code: &str,
        now_ms: i64,
    ) -> Result<DeviceApproveView, IdentityError> {
        self.pg_approve_device_code(user_id, user_code, now_ms)
            .await
    }

    async fn poll_device_token(&self, device_code: &str) -> Result<DeviceTokenView, IdentityError> {
        self.pg_poll_device_token(device_code).await
    }

    async fn cancel_device_code(
        &self,
        device_code: &str,
    ) -> Result<DeviceCancelView, IdentityError> {
        self.pg_cancel_device_code(device_code).await
    }

    async fn list_tenants(
        &self,
        user_id: &str,
        search: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<TenantPage, IdentityError> {
        self.pg_list_tenants(user_id, search, page, page_size).await
    }

    async fn get_tenant(
        &self,
        user_id: &str,
        tenant_id_or_slug: &str,
    ) -> Result<TenantView, IdentityError> {
        self.pg_get_tenant(user_id, tenant_id_or_slug).await
    }

    async fn create_tenant(
        &self,
        user_id: &str,
        name: &str,
        description: Option<&str>,
    ) -> Result<TenantView, IdentityError> {
        self.pg_create_tenant(user_id, name, description).await
    }

    async fn update_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
        patch: TenantUpdatePatch,
    ) -> Result<TenantView, IdentityError> {
        self.pg_update_tenant(user_id, tenant_id, patch).await
    }

    async fn delete_tenant(&self, user_id: &str, tenant_id: &str) -> Result<(), IdentityError> {
        self.pg_delete_tenant(user_id, tenant_id).await
    }

    async fn add_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        self.pg_add_tenant_member(user_id, tenant_id, target_user_id, role)
            .await
    }

    async fn update_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        self.pg_update_tenant_member(user_id, tenant_id, target_user_id, role)
            .await
    }

    async fn remove_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        self.pg_remove_tenant_member(user_id, tenant_id, target_user_id)
            .await
    }

    async fn list_projects(
        &self,
        user_id: &str,
        input: ProjectListInput<'_>,
    ) -> Result<ProjectPage, IdentityError> {
        self.pg_list_projects(user_id, input).await
    }

    async fn get_project(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<ProjectView, IdentityError> {
        self.pg_get_project(user_id, project_id, tenant_id).await
    }

    async fn create_project(
        &self,
        user_id: &str,
        input: ProjectCreateInput,
    ) -> Result<ProjectView, IdentityError> {
        self.pg_create_project(user_id, input).await
    }

    async fn update_project(
        &self,
        user_id: &str,
        project_id: &str,
        patch: ProjectUpdatePatch,
    ) -> Result<ProjectView, IdentityError> {
        self.pg_update_project(user_id, project_id, patch).await
    }

    async fn delete_project(&self, user_id: &str, project_id: &str) -> Result<(), IdentityError> {
        self.pg_delete_project(user_id, project_id).await
    }

    async fn get_project_stats(
        &self,
        user_id: &str,
        project_id: &str,
        now_ms: i64,
    ) -> Result<ProjectStatsView, IdentityError> {
        self.pg_get_project_stats(user_id, project_id, now_ms).await
    }

    async fn list_project_members(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMembersView, IdentityError> {
        self.pg_list_project_members(user_id, project_id).await
    }

    async fn add_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        self.pg_add_project_member(user_id, project_id, target_user_id, role)
            .await
    }

    async fn update_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        self.pg_update_project_member(user_id, project_id, target_user_id, role)
            .await
    }

    async fn remove_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        self.pg_remove_project_member(user_id, project_id, target_user_id)
            .await
    }

    async fn create_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        email: &str,
        role: &str,
        message: Option<&str>,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        self.pg_create_invitation(user_id, tenant_id, email, role, message, now_ms)
            .await
    }

    async fn list_invitations(
        &self,
        user_id: &str,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<InvitationListView, IdentityError> {
        self.pg_list_invitations(user_id, tenant_id, limit, offset)
            .await
    }

    async fn cancel_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        invitation_id: &str,
        now_ms: i64,
    ) -> Result<(), IdentityError> {
        self.pg_cancel_invitation(user_id, tenant_id, invitation_id, now_ms)
            .await
    }

    async fn verify_invitation(
        &self,
        token: &str,
        now_ms: i64,
    ) -> Result<InvitationVerifyView, IdentityError> {
        self.pg_verify_invitation(token, now_ms).await
    }

    async fn accept_invitation(
        &self,
        token: &str,
        user_id: &str,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        self.pg_accept_invitation(token, user_id, now_ms).await
    }
}
