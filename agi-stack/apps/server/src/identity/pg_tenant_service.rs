use super::*;

impl PgIdentityService {
    pub(super) async fn pg_list_tenants(
        &self,
        user_id: &str,
        search: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<TenantPage, IdentityError> {
        let (page, page_size) = clamp_pagination(page, page_size);
        let total = self
            .tenants
            .count_for_user(user_id, search)
            .await
            .map_err(IdentityError::internal)?;
        let offset = (page - 1) * page_size;
        let records = self
            .tenants
            .list_for_user(user_id, search, offset, page_size)
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantPage {
            tenants: records.into_iter().map(TenantView::from).collect(),
            total,
            page,
            page_size,
        })
    }

    pub(super) async fn pg_get_tenant(
        &self,
        user_id: &str,
        tenant_id_or_slug: &str,
    ) -> Result<TenantView, IdentityError> {
        match self
            .tenants
            .get_for_user(user_id, tenant_id_or_slug)
            .await
            .map_err(IdentityError::internal)?
        {
            TenantLookup::Found(record) => Ok(TenantView::from(record)),
            TenantLookup::NotFound => Err(IdentityError::not_found("Tenant not found")),
            TenantLookup::Forbidden => Err(IdentityError::forbidden("Access denied to tenant")),
        }
    }

    pub(super) async fn pg_create_tenant(
        &self,
        user_id: &str,
        name: &str,
        description: Option<&str>,
    ) -> Result<TenantView, IdentityError> {
        let tenant_id = generate_uuid_v4();
        let membership_id = generate_uuid_v4();
        let record = self
            .tenants
            .create_tenant(
                &tenant_id,
                &membership_id,
                user_id,
                name,
                description,
                &tenant_owner_permissions(),
            )
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantView::from(record))
    }

    pub(super) async fn pg_update_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
        patch: TenantUpdatePatch,
    ) -> Result<TenantView, IdentityError> {
        self.tenants
            .update_owned_tenant(user_id, tenant_id, &patch)
            .await
            .map_err(IdentityError::internal)?
            .map(TenantView::from)
            .ok_or_else(|| IdentityError::forbidden("Only tenant owner can update tenant"))
    }

    pub(super) async fn pg_delete_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<(), IdentityError> {
        if !self
            .tenants
            .delete_owned_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can delete tenant",
            ));
        }
        Ok(())
    }

    pub(super) async fn pg_add_tenant_member(
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
        if !self
            .tenants
            .tenant_exists(tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if !self
            .tenants
            .user_owns_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can add members",
            ));
        }
        if !self
            .tenants
            .user_exists(target_user_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("User not found"));
        }
        if self
            .tenants
            .tenant_member_role(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_some()
        {
            return Err(IdentityError::bad_request(
                "User is already a member of this tenant",
            ));
        }
        let membership_id = generate_uuid_v4();
        self.tenants
            .add_tenant_member(
                &membership_id,
                tenant_id,
                target_user_id,
                &role,
                &tenant_member_add_permissions(&role),
            )
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    pub(super) async fn pg_update_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        if !is_valid_tenant_member_role(role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if !self
            .tenants
            .tenant_exists(tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if !self
            .tenants
            .user_owns_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can update member roles",
            ));
        }
        if target_user_id == user_id && role != "owner" {
            return Err(IdentityError::bad_request(
                "Cannot change tenant owner role",
            ));
        }
        if self
            .tenants
            .tenant_member_role(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_none()
        {
            return Err(IdentityError::not_found("Tenant member not found"));
        }
        self.tenants
            .update_tenant_member(
                tenant_id,
                target_user_id,
                role,
                &tenant_member_update_permissions(role),
            )
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    pub(super) async fn pg_remove_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if !self
            .tenants
            .tenant_exists(tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if !self
            .tenants
            .user_owns_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove tenant owner"));
        }
        if self
            .tenants
            .tenant_member_role(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_none()
        {
            return Err(IdentityError::not_found(
                "User is not a member of this tenant",
            ));
        }
        self.tenants
            .remove_tenant_member(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }
}
