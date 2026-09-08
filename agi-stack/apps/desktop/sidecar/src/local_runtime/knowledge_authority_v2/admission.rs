//! Local acceptance is a host qualification, distinct from joint feature release.
use super::*;
use crate::local_knowledge_acceptance::LocalKnowledgeAcceptance;

pub(super) enum KnowledgeAdmission {
    Closed,
    LocalAcceptance(LocalKnowledgeAcceptance),
    SyncAcceptance(LocalKnowledgeAcceptance),
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
            Self::LocalAcceptance(qualification) | Self::SyncAcceptance(qualification) => {
                qualification
                    .require_storage(path)
                    .map_err(|_| KnowledgeAuthorityErrorV2::ReleaseClosed)
            }
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
            Self::LocalAcceptance(_) | Self::SyncAcceptance(_) if publication_version.is_some() => {
                Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
            }
            Self::LocalAcceptance(qualification) | Self::SyncAcceptance(qualification) => {
                qualification
                    .require_profile(profile, digest)
                    .map_err(|_| KnowledgeAuthorityErrorV2::GenerationMismatch)
            }
            _ => Ok(()),
        }
    }
    pub(super) fn permits_action(&self, action: &str) -> bool {
        match self {
            Self::Closed => false,
            Self::LocalAcceptance(_) => {
                super::capabilities_generated::LOCAL_ACCEPTANCE_ACTIONS.contains(&action)
            }
            Self::SyncAcceptance(_) => {
                super::capabilities_generated::READ_ACTIONS.contains(&action)
                    || super::capabilities_generated::WRITE_ACTIONS.contains(&action)
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
        if state.disposed {
            return Err(KnowledgeAuthorityErrorV2::Disposed);
        }
        match &state.admission {
            KnowledgeAdmission::SyncAcceptance(qualification) => qualification
                .require_storage(
                    state
                        .app_data_dir
                        .as_deref()
                        .ok_or(KnowledgeAuthorityErrorV2::ReleaseClosed)?,
                )
                .map_err(|_| KnowledgeAuthorityErrorV2::ReleaseClosed),
            #[cfg(test)]
            KnowledgeAdmission::InternalValidation => Ok(()),
            _ => Err(KnowledgeAuthorityErrorV2::ReleaseClosed),
        }
    }

    /// A live cloud descriptor must belong to the exact compiled joint QA profile.
    /// The connector separately fences its dynamic generation and authenticated actor.
    pub(super) fn require_sync_cloud_profile(
        &self,
        profile_id: &str,
        generation: u64,
        digest: &str,
    ) -> Result<(), KnowledgeAuthorityErrorV2> {
        if generation == 0
            || generation > 9_007_199_254_740_991
            || profile_id.is_empty()
            || profile_id.trim() != profile_id
            || digest.len() != 64
            || !digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(KnowledgeAuthorityErrorV2::GenerationMismatch);
        }
        let state = self
            .inner
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Disposed)?;
        if state.disposed {
            return Err(KnowledgeAuthorityErrorV2::Disposed);
        }
        match &state.admission {
            KnowledgeAdmission::SyncAcceptance(qualification) => qualification
                .require_cloud_profile(profile_id, generation, digest)
                .map_err(|_| KnowledgeAuthorityErrorV2::GenerationMismatch),
            #[cfg(test)]
            KnowledgeAdmission::InternalValidation => Ok(()),
            _ => Err(KnowledgeAuthorityErrorV2::ReleaseClosed),
        }
    }
    pub(super) fn capability_reason(&self) -> Result<&'static str, KnowledgeAuthorityErrorV2> {
        let state = self
            .inner
            .lock()
            .map_err(|_| KnowledgeAuthorityErrorV2::Disposed)?;
        Ok(
            if matches!(state.admission, KnowledgeAdmission::LocalAcceptance(_)) {
                "knowledge_local_acceptance_only"
            } else if matches!(state.admission, KnowledgeAdmission::SyncAcceptance(_)) {
                "knowledge_sync_acceptance_only"
            } else {
                "desktop_project_memories_actions_partial"
            },
        )
    }
}
