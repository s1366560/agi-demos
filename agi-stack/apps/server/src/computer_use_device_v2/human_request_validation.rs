//! Structural target checks run before the engine suspends or emits a human request.
use super::*;
use agistack_core::{agent::hitl_validation::HitlValidationContext, HitlRequest};

#[derive(Clone)]
pub(crate) struct NativeHumanRequestValidation {
    broker: Broker,
    owner: Owner,
    run: authority::RunAuthority,
    conversation: String,
}

impl NativeHumanRequestValidation {
    pub(crate) fn capture(bound: &BoundRun, conversation: &str) -> Self {
        Self {
            broker: bound.broker.clone(),
            owner: bound.owner.clone(),
            run: bound.run.clone(),
            conversation: conversation.into(),
        }
    }

    pub(crate) async fn validate(
        &self,
        context: &HitlValidationContext<'_>,
        request: &HitlRequest,
    ) -> CoreResult<()> {
        self.broker
            .authority
            .as_ref()
            .ok_or_else(|| CoreError::Tool("computer_use_authority_unavailable".into()))?
            .recheck_running(&self.owner, &self.conversation, &self.run)
            .await?;
        let (claim, _, _, permission) = hitl::matching_permission(
            &self.broker,
            &self.owner,
            &self.run,
            &self.conversation,
            context.session_id,
            request,
        )?;
        if permission.kind() != agistack_core::ports::PermissionKind::ServerMcpTool {
            self.broker
                .validate_permission_claim(
                    &claim,
                    &permission::WirePermission {
                        kind: permission.kind(),
                        binding: permission.binding().clone(),
                        demand: permission.demand().clone(),
                    },
                )
                .await?;
        }
        Ok(())
    }
}
