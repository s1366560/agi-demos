use super::*;

impl PgIdentityService {
    pub(super) async fn pg_create_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        email: &str,
        role: &str,
        message: Option<&str>,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        self.require_invitation_admin(user_id, tenant_id).await?;
        if self
            .invitations
            .find_pending_by_email_and_tenant(email, tenant_id)
            .await
            .map_err(IdentityError::internal)?
            .is_some()
        {
            return Err(IdentityError::conflict("Invitation already exists"));
        }

        let now = ms_to_datetime(now_ms);
        let invitation = InvitationRecord {
            id: try_generate_uuid_v4().map_err(IdentityError::internal)?,
            tenant_id: tenant_id.to_string(),
            email: normalize_email(email),
            role: if role.trim().is_empty() {
                "member".to_string()
            } else {
                role.to_string()
            },
            token: try_generate_urlsafe_token(32).map_err(IdentityError::internal)?,
            status: "pending".to_string(),
            invited_by: user_id.to_string(),
            accepted_by: None,
            expires_at: ms_to_datetime(now_ms + INVITATION_EXPIRY_MS),
            created_at: now,
            deleted_at: None,
        };
        let saved = self
            .invitations
            .create(&invitation)
            .await
            .map_err(IdentityError::internal)?;
        self.send_invitation_email(&saved, message).await?;
        Ok(InvitationView::from(saved))
    }

    pub(super) async fn pg_list_invitations(
        &self,
        user_id: &str,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<InvitationListView, IdentityError> {
        self.require_invitation_admin(user_id, tenant_id).await?;
        let (limit, offset) = clamp_limit_offset(limit, offset);
        let total = self
            .invitations
            .count_pending_by_tenant(tenant_id)
            .await
            .map_err(IdentityError::internal)?;
        let items = self
            .invitations
            .list_pending_by_tenant(tenant_id, limit, offset)
            .await
            .map_err(IdentityError::internal)?
            .into_iter()
            .map(InvitationView::from)
            .collect();
        Ok(InvitationListView {
            items,
            total,
            limit,
            offset,
        })
    }

    pub(super) async fn pg_cancel_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        invitation_id: &str,
        now_ms: i64,
    ) -> Result<(), IdentityError> {
        self.require_invitation_admin(user_id, tenant_id).await?;
        let Some(invitation) = self
            .invitations
            .find_by_id(invitation_id)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Err(IdentityError::not_found("Invitation not found"));
        };
        if invitation.tenant_id != tenant_id {
            return Err(IdentityError::forbidden(
                "Not authorized to manage this invitation",
            ));
        }
        if invitation.status != "pending" {
            return Err(IdentityError::not_found("Invitation not found"));
        }
        self.invitations
            .soft_delete(invitation_id, ms_to_datetime(now_ms))
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }

    pub(super) async fn pg_verify_invitation(
        &self,
        token: &str,
        now_ms: i64,
    ) -> Result<InvitationVerifyView, IdentityError> {
        match self.valid_invitation_at(token, now_ms).await? {
            Some(invitation) => Ok(InvitationVerifyView::valid(invitation)),
            None => Ok(InvitationVerifyView::invalid()),
        }
    }

    pub(super) async fn pg_accept_invitation(
        &self,
        token: &str,
        user_id: &str,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        let Some(mut invitation) = self.valid_invitation_at(token, now_ms).await? else {
            return Err(IdentityError::bad_request("Invalid or expired invitation"));
        };
        self.invitations
            .update_status(&invitation.id, "accepted", Some(user_id))
            .await
            .map_err(IdentityError::internal)?;
        self.invitations
            .ensure_user_tenant_membership(
                &try_generate_uuid_v4().map_err(IdentityError::internal)?,
                user_id,
                &invitation.tenant_id,
                &invitation.role,
            )
            .await
            .map_err(IdentityError::internal)?;
        invitation.status = "accepted".to_string();
        invitation.accepted_by = Some(user_id.to_string());
        Ok(InvitationView::from(invitation))
    }
}
