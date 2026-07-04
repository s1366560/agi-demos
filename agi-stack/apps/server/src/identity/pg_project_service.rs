use super::*;

impl PgIdentityService {
    pub(super) async fn pg_list_projects(
        &self,
        user_id: &str,
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
        let offset = (page - 1) * page_size;
        let records = self
            .projects
            .list_for_user(ProjectListForUserQuery {
                user_id,
                tenant_id,
                search,
                visibility,
                owner_id,
                offset,
                limit: page_size,
            })
            .await
            .map_err(IdentityError::internal)?;
        Ok(ProjectPage {
            projects: records
                .projects
                .into_iter()
                .map(ProjectView::from)
                .collect(),
            total: records.total,
            page,
            page_size,
            owner_ids: records.owner_ids,
        })
    }

    pub(super) async fn pg_get_project(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<ProjectView, IdentityError> {
        match self
            .projects
            .get_for_user(user_id, project_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            ProjectLookup::Found(record) => Ok(ProjectView::from(*record)),
            ProjectLookup::Forbidden => Err(IdentityError::forbidden("Access denied to project")),
            ProjectLookup::NotFound => Err(IdentityError::not_found("Project not found")),
            ProjectLookup::TenantMismatch => Err(IdentityError::not_found(
                "Project not found in requested tenant",
            )),
        }
    }

    pub(super) async fn pg_create_project(
        &self,
        user_id: &str,
        input: ProjectCreateInput,
    ) -> Result<ProjectView, IdentityError> {
        if !is_valid_agent_conversation_mode(&input.agent_conversation_mode) {
            return Err(unprocessable("Invalid agent_conversation_mode"));
        }
        if !self
            .projects
            .user_is_tenant_project_admin(user_id, &input.tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "User does not have permission to create projects in this tenant",
            ));
        }

        let graph_store_id = self
            .normalize_graph_store_binding(&input.tenant_id, input.graph_store_id.as_deref())
            .await?;
        let retrieval_store_id = self
            .normalize_retrieval_store_binding(
                &input.tenant_id,
                input.retrieval_store_id.as_deref(),
            )
            .await?;
        let record = ProjectCreateRecord {
            id: generate_uuid_v4(),
            membership_id: generate_uuid_v4(),
            tenant_id: input.tenant_id,
            name: input.name,
            description: input.description,
            owner_id: user_id.to_string(),
            memory_rules: project_memory_rules_for_write(input.memory_rules),
            graph_config: project_graph_config_for_write(input.graph_config),
            graph_store_id,
            retrieval_store_id,
            sandbox_type: "cloud".to_string(),
            sandbox_config: json!({}),
            is_public: input.is_public,
            agent_conversation_mode: input.agent_conversation_mode,
            owner_permissions: project_owner_permissions(),
        };
        self.projects
            .create_project(&record)
            .await
            .map(ProjectView::from)
            .map_err(IdentityError::internal)
    }

    pub(super) async fn pg_update_project(
        &self,
        user_id: &str,
        project_id: &str,
        mut patch: ProjectUpdatePatch,
    ) -> Result<ProjectView, IdentityError> {
        if let Some(mode) = patch.agent_conversation_mode.as_deref() {
            if !is_valid_agent_conversation_mode(mode) {
                return Err(unprocessable("Invalid agent_conversation_mode"));
            }
        }
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update project",
            ));
        }
        let Some(current) = self
            .projects
            .get_by_id(project_id)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Err(IdentityError::not_found("Project not found"));
        };

        if let Some(store_id) = patch.graph_store_id.take() {
            patch.graph_store_id = Some(
                self.normalize_graph_store_binding(&current.tenant_id, store_id.as_deref())
                    .await?,
            );
        }
        if let Some(store_id) = patch.retrieval_store_id.take() {
            patch.retrieval_store_id = Some(
                self.normalize_retrieval_store_binding(&current.tenant_id, store_id.as_deref())
                    .await?,
            );
        }
        if let Some(memory_rules) = patch.memory_rules.take() {
            patch.memory_rules = Some(project_memory_rules_for_write(Some(memory_rules)));
        }
        if let Some(graph_config) = patch.graph_config.take() {
            patch.graph_config = Some(project_graph_config_for_write(Some(graph_config)));
        }

        self.projects
            .update_project(project_id, &patch)
            .await
            .map_err(IdentityError::internal)?
            .map(ProjectView::from)
            .ok_or_else(|| IdentityError::not_found("Project not found"))
    }

    pub(super) async fn pg_delete_project(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<(), IdentityError> {
        if !self
            .projects
            .user_is_project_owner(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner can delete project",
            ));
        }
        if !self
            .projects
            .project_exists(project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Project not found"));
        }
        self.projects
            .delete_project(project_id)
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }

    pub(super) async fn pg_get_project_stats(
        &self,
        user_id: &str,
        project_id: &str,
        now_ms: i64,
    ) -> Result<ProjectStatsView, IdentityError> {
        match self
            .projects
            .stats_for_user(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            ProjectStatsLookup::Found(record) => Ok(ProjectStatsView::dashboard(record, now_ms)),
            ProjectStatsLookup::Forbidden => {
                Err(IdentityError::forbidden("Access denied to project"))
            }
            ProjectStatsLookup::NotFound => Err(IdentityError::not_found("Project not found")),
        }
    }

    pub(super) async fn pg_list_project_members(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMembersView, IdentityError> {
        match self
            .projects
            .members_for_user(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            ProjectMembersLookup::Found(record) => Ok(ProjectMembersView::from(record)),
            ProjectMembersLookup::InvalidId => Err(IdentityError {
                status: StatusCode::UNPROCESSABLE_ENTITY,
                detail: "Invalid UUID".to_string(),
                detail_value: None,
                www_authenticate: false,
            }),
            ProjectMembersLookup::Forbidden => {
                Err(IdentityError::forbidden("Access denied to project"))
            }
            ProjectMembersLookup::NotFound => Err(IdentityError::not_found("Project not found")),
        }
    }

    pub(super) async fn pg_add_project_member(
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
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can add members",
            ));
        }
        if !self
            .projects
            .project_exists(project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Project not found"));
        }
        if !self
            .projects
            .user_exists(target_user_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("User not found"));
        }
        if self
            .projects
            .project_member_role(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_some()
        {
            return Err(IdentityError::bad_request(
                "User is already a member of this project",
            ));
        }

        let membership_id = generate_uuid_v4();
        self.projects
            .add_project_member(
                &membership_id,
                project_id,
                target_user_id,
                &role,
                &project_member_add_permissions(&role),
            )
            .await
            .map_err(IdentityError::internal)?;

        Ok(ProjectMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    pub(super) async fn pg_update_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update members",
            ));
        }

        let Some(existing) = self
            .projects
            .project_member_role(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Err(IdentityError::not_found(
                "User is not a member of this project",
            ));
        };
        if existing.role == "owner" {
            return Err(IdentityError::bad_request(
                "Cannot update project owner role",
            ));
        }

        self.projects
            .update_project_member(
                project_id,
                target_user_id,
                role,
                &project_member_update_permissions(role),
            )
            .await
            .map_err(IdentityError::internal)?;

        Ok(ProjectMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    pub(super) async fn pg_remove_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove project owner"));
        }
        if self
            .projects
            .project_member_role(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_none()
        {
            return Err(IdentityError::not_found(
                "User is not a member of this project",
            ));
        }
        self.projects
            .remove_project_member(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }
}
