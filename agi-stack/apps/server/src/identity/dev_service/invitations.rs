use super::*;

impl DevIdentityService {
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

    pub(super) async fn dev_create_invitation(
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

    pub(super) async fn dev_list_invitations(
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

    pub(super) async fn dev_cancel_invitation(
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

    pub(super) async fn dev_verify_invitation(
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

    pub(super) async fn dev_accept_invitation(
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
