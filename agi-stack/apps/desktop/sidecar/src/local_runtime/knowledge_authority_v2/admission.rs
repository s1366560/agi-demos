//! Local acceptance is a host qualification, distinct from joint feature release.
use super::*;
use crate::local_knowledge_acceptance::LocalKnowledgeAcceptance;

pub(super) enum KnowledgeAdmission {
    Closed,
    LocalAcceptance(LocalKnowledgeAcceptance),
    #[cfg(test)]
    InternalValidation,
}

impl KnowledgeAdmission {
    pub(super) fn require_storage(
        &self,
        path: &std::path::Path,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        match self {
            Self::Closed => Err(KnowledgeAuthorityErrorV2::ReleaseClosed),
            Self::LocalAcceptance(qualification) => qualification
                .require_storage(path)
                .map_err(|_| KnowledgeAuthorityErrorV2::ReleaseClosed),
            #[cfg(test)]
            Self::InternalValidation => Ok(()),
        }
    }
    pub(super) fn require_profile(
        &self,
        profile: &str,
        digest: &str,
        publication_version: Option<u64>,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        match self {
            Self::LocalAcceptance(_) if publication_version.is_some() => {
                Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
            }
            Self::LocalAcceptance(qualification) => qualification
                .require_profile(profile, digest)
                .map_err(|_| KnowledgeAuthorityErrorV2::GenerationMismatch),
            _ => Ok(()),
        }
    }
    pub(super) fn permits_action(&self, action: &str) -> bool {
        match self {
            Self::Closed => false,
            Self::LocalAcceptance(_) => {
                super::capabilities_generated::LOCAL_ACCEPTANCE_ACTIONS.contains(&action)
            }
            #[cfg(test)]
            Self::InternalValidation => true,
        }
    }
}

impl KnowledgeAuthorityV2 {
    pub(super) fn require_profile(
        &self,
        profile: &str,
        digest: &str,
        publication_version: Option<u64>,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        self.inner
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Disposed)?
            .admission
            .require_profile(profile, digest, publication_version)
    }
    pub(super) fn require_sync_release(&self) -> Result<(), KnowledgeAuthorityErrorV2> {
        let state = self
            .inner
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Disposed)?;
        #[cfg(test)]
        if matches!(state.admission, KnowledgeAdmission::InternalValidation) {
            return Ok(());
        }
        drop(state);
        Err(KnowledgeAuthorityErrorV2::ReleaseClosed)
    }
    pub(super) fn capability_reason(&self) -> Result<&'static str, KnowledgeAuthorityErrorV2> {
        let state = self
            .inner
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Disposed)?;
        Ok(
            if matches!(state.admission, KnowledgeAdmission::LocalAcceptance(_)) {
                "knowledge_local_acceptance_only"
            } else {
                "desktop_project_memories_actions_partial"
            },
        )
    }
}
