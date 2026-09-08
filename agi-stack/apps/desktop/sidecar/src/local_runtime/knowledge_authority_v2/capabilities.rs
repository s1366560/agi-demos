//! Publication and processing admission share the declared protocol action roster.
use super::capabilities_generated::{READ_ACTIONS, WRITE_ACTIONS};
use super::*;

impl KnowledgeAuthorityV2 {
    pub(super) fn allowed_actions(
        &self,
        role: &str,
    ) -> Result<Vec<&'static str>, KnowledgeAuthorityErrorV2> {
        let state = self
            .inner
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Disposed)?;
        if state.disposed {
            return Err(KnowledgeAuthorityErrorV2::Disposed);
        }
        if !state.admitted_for_validation {
            return Ok(Vec::new());
        }
        let writer = matches!(role, "owner" | "admin" | "member" | "contributor");
        if !writer && role != "viewer" {
            return Err(KnowledgeAuthorityErrorV2::Forbidden);
        }
        let mut actions: std::collections::BTreeSet<_> = READ_ACTIONS.iter().copied().collect();
        if writer {
            actions.extend(WRITE_ACTIONS.iter().copied());
        }
        #[cfg(test)]
        if let Some(allowed) = &state.validation_actions {
            actions.retain(|action| allowed.contains(*action));
        }
        Ok(actions.into_iter().collect())
    }

    pub(super) fn require_action(
        &self,
        role: &str,
        action: &str,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        if self.allowed_actions(role)?.contains(&action) {
            Ok(())
        } else {
            Err(KnowledgeAuthorityErrorV2::Forbidden)
        }
    }
}

impl KnowledgeOperationV2 {
    pub(super) fn admit_capability(
        mut self,
        state: &super::super::LocalRuntimeState,
        auth: &AuthenticatedContext,
        action: &'static str,
    ) -> Result<Self, KnowledgeAuthorityErrorV2> {
        self.capability_action = Some(action);
        // Every later processing_context check repeats this exact action admission,
        // including final publication after a provider request has completed.
        processing_context::with_read_current(&self, state, auth, |_| Ok(()))?;
        Ok(self)
    }
}
