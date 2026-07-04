use super::*;

impl DevIdentityService {
    /// The single deterministic tenant the dev service exposes.
    pub(super) fn dev_tenant(&self) -> TenantView {
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

    pub(super) fn dev_list_tenants(
        &self,
        search: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> TenantPage {
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
        TenantPage {
            tenants,
            total,
            page,
            page_size,
        }
    }

    pub(super) fn dev_get_tenant(
        &self,
        tenant_id_or_slug: &str,
    ) -> Result<TenantView, IdentityError> {
        let dev = self.dev_tenant();
        if tenant_id_or_slug == dev.id || tenant_id_or_slug == dev.slug {
            Ok(dev)
        } else {
            Err(IdentityError::not_found("Tenant not found"))
        }
    }

    pub(super) fn dev_create_tenant(
        &self,
        user_id: &str,
        name: &str,
        description: Option<&str>,
    ) -> TenantView {
        let mut tenant = self.dev_tenant();
        tenant.id = "dev-created-tenant".to_string();
        tenant.name = name.to_string();
        tenant.slug = name.to_lowercase().replace(' ', "-");
        tenant.description = description.map(str::to_string);
        tenant.owner_id = user_id.to_string();
        tenant
    }

    pub(super) fn dev_update_tenant(
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

    pub(super) fn dev_delete_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<(), IdentityError> {
        if tenant_id != "dev-tenant" || user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can delete tenant",
            ));
        }
        Ok(())
    }

    pub(super) fn dev_add_tenant_member(
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

    pub(super) fn dev_update_tenant_member(
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

    pub(super) fn dev_remove_tenant_member(
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
}
