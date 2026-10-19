//! Previously authenticated cloud identity may only shrink an owned audio resource.
use super::*;
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionRuntimeMode, TrustedSessionSnapshot,
};

#[derive(Clone, PartialEq, Eq)]
pub(super) struct VerifiedOwner {
    pub owner: Owner,
    identity: String,
}

struct Binding {
    owner: Owner,
    identity: String,
}

#[derive(Default)]
pub(super) struct Bindings {
    owners: Mutex<BTreeMap<(String, String), Binding>>,
}

fn identity(snapshot: &TrustedSessionSnapshot) -> Result<String, String> {
    let record = snapshot
        .record
        .as_ref()
        .filter(|record| record.runtime_mode == TrustedSessionRuntimeMode::Cloud)
        .ok_or("cua_trusted_session_required")?;
    // Cache only a digest; no credentials are retained or persisted here.
    super::super::tool_authority::canonical_json_digest(
        &json!({"epoch":snapshot.epoch,"record":record}),
    )
    .map_err(|_| "cua_cleanup_identity_invalid".into())
}

impl Bindings {
    /// Call only after the current cloud authority verified both user and project.
    pub(super) fn remember(
        &self,
        broker: &TrustedSessionBroker,
        expected_epoch: u64,
        owner: &Owner,
    ) -> Result<(), String> {
        broker
            .with_snapshot(|snapshot| {
                if snapshot.epoch != expected_epoch {
                    return Err("cua_identity_changed".into());
                }
                let identity = identity(&snapshot)?;
                let mut owners = self
                    .owners
                    .lock()
                    .map_err(|_| "cua_cleanup_owner_unavailable")?;
                owners.retain(|_, binding| {
                    binding.identity == identity
                        && binding.owner.user_id == owner.user_id
                        && binding.owner.device_id == owner.device_id
                });
                owners.insert(
                    (owner.tenant_id.clone(), owner.project_id.clone()),
                    Binding {
                        owner: owner.clone(),
                        identity,
                    },
                );
                Ok(())
            })
            .map_err(|_| "cua_trusted_session_unavailable")?
    }

    /// This cache is not an execution grant and is never used by start or resume.
    pub(super) fn resolve_audio_stop(
        &self,
        broker: &TrustedSessionBroker,
        tenant_id: &str,
        project_id: &str,
        device_id: &str,
    ) -> Result<VerifiedOwner, String> {
        broker
            .with_snapshot(|snapshot| {
                let identity = identity(&snapshot)?;
                self.owners
                    .lock()
                    .map_err(|_| "cua_cleanup_owner_unavailable")?
                    .get(&(tenant_id.to_owned(), project_id.to_owned()))
                    .filter(|binding| {
                        binding.identity == identity && binding.owner.device_id == device_id
                    })
                    .map(|binding| VerifiedOwner {
                        owner: binding.owner.clone(),
                        identity: binding.identity.clone(),
                    })
                    .ok_or_else(|| "cua_cleanup_owner_unavailable".into())
            })
            .map_err(|_| "cua_trusted_session_unavailable")?
    }
}
