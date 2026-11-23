//! Online device possession and exact package admission, separate from publication credentials.
use super::*;
use sha2::{Digest, Sha256};
use zeroize::Zeroizing;

pub(super) fn digest_hex(digest: &str) -> Result<&str, String> {
    let hex = digest.strip_prefix("sha256:").unwrap_or(digest);
    if hex.len() != 64
        || !hex
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err("device_plugin_digest_invalid".into());
    }
    Ok(hex)
}

#[derive(Deserialize)]
pub(super) struct ProjectSelection {
    pub plugin_id: String,
    pub generation_id: String,
    digest: String,
}
impl ProjectSelection {
    pub async fn resolve(owner: &CloudOwner, plugin_id: &str) -> Result<Self, String> {
        let response = owner
            .plugin_grant_request(reqwest::Method::GET, "selection")?
            .query(&[("plugin_id", plugin_id)])
            .send()
            .await
            .map_err(|_| "device_plugin_selection_unavailable")?;
        if !response.status().is_success() {
            return Err("device_plugin_selection_unavailable".into());
        }
        let active: Self = response
            .json()
            .await
            .map_err(|_| "device_plugin_selection_invalid")?;
        let generation = active
            .generation_id
            .strip_prefix('p')
            .ok_or("device_plugin_selection_invalid")?;
        if active.plugin_id != plugin_id
            || generation.len() != 63
            || !generation
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err("device_plugin_selection_invalid".into());
        }
        digest_hex(&active.digest)?;
        owner.fence(|| Ok(active))
    }
    pub fn verify(&self, reference: &BundleReferenceV2) -> Result<(), String> {
        if reference.bundle_id != self.plugin_id
            || digest_hex(&reference.digest)? != digest_hex(&self.digest)?
        {
            return Err("device_plugin_selection_changed".into());
        }
        Ok(())
    }
}

pub(super) struct Device {
    pub machine: String,
    pub fingerprint: String,
    proof: Zeroizing<String>,
}
impl Device {
    pub fn current(state: &LocalRuntimeState) -> Result<Self, String> {
        let proof = state.provider_credentials.plugin_device_proof()?;
        Ok(Self {
            machine: state.session_store.installation_id().into(),
            fingerprint: format!("sha256:{:x}", Sha256::digest(proof.as_bytes())),
            proof,
        })
    }

    pub async fn can_manage(owner: &CloudOwner) -> Result<bool, String> {
        let response = owner
            .plugin_grant_request(reqwest::Method::GET, "authority")?
            .send()
            .await
            .map_err(|_| "device_plugin_grant_unavailable")?;
        if !response.status().is_success() {
            return Err("device_plugin_grant_unavailable".into());
        }
        #[derive(Deserialize)]
        struct Capability {
            can_manage: bool,
        }
        let permission: Capability = response
            .json()
            .await
            .map_err(|_| "device_plugin_grant_invalid")?;
        owner.fence(|| Ok(permission.can_manage))
    }

    pub async fn approve(
        &self,
        owner: &CloudOwner,
        reference: &BundleReferenceV2,
        generation: &str,
        permissions: &BTreeSet<String>,
    ) -> Result<(), String> {
        let expires = chrono::Utc::now() + chrono::TimeDelta::hours(24);
        let response = owner.plugin_grant_request(reqwest::Method::POST,"")?.json(&json!({
            "user_id": owner.user_id, "machine_id":self.machine, "device_fingerprint":self.fingerprint,
            "bundle_digest":digest_hex(&reference.digest)?, "generation_id":generation, "permissions":["install","invoke"],
            "approved_permissions":permissions, "expires_at":expires.to_rfc3339()
        })).send().await.map_err(|_| "device_plugin_grant_unavailable")?;
        if !response.status().is_success() {
            return Err("device_plugin_approval_rejected".into());
        }
        owner.fence(|| Ok(()))
    }

    pub async fn revoke(owner: &CloudOwner, id: &str) -> Result<(), String> {
        uuid::Uuid::parse_str(id).map_err(|_| "device_plugin_grant_invalid")?;
        let response = owner
            .plugin_grant_request(reqwest::Method::DELETE, id)?
            .send()
            .await
            .map_err(|_| "device_plugin_grant_unavailable")?;
        if !response.status().is_success() {
            return Err("device_plugin_revocation_rejected".into());
        }
        owner.fence(|| Ok(()))
    }

    pub async fn status(
        &self,
        owner: &CloudOwner,
        item: Selection,
        generation: &str,
        trust: bool,
    ) -> Value {
        let status = if item.generation_id != generation {
            "device_plugin_generation_changed".into()
        } else if !trust {
            "device_plugin_trust_unavailable".into()
        } else {
            match self
                .check(
                    owner,
                    &item.reference,
                    generation,
                    &item.approved_permissions,
                    Some(&item.grant_id),
                )
                .await
            {
                Ok(_) => "approved".into(),
                Err(error) => error,
            }
        };
        let mut result = store::projection(&item);
        result["grant_status"] = json!(status);
        result
    }

    pub async fn check(
        &self,
        owner: &CloudOwner,
        reference: &BundleReferenceV2,
        generation: &str,
        permissions: &BTreeSet<String>,
        grant_id: Option<&str>,
    ) -> Result<String, String> {
        let permission = if grant_id.is_some() {
            "invoke"
        } else {
            "install"
        };
        let mut body = json!({
            "machine_id":self.machine, "device_proof":self.proof.as_str(), "bundle_digest": digest_hex(&reference.digest)?,
            "generation_id":generation, "permission":permission, "approved_permissions":permissions
        });
        if let Some(id) = grant_id {
            body["grant_id"] = json!(id);
        }
        let response = owner
            .plugin_grant_request(reqwest::Method::POST, "check")?
            .json(&body)
            .send()
            .await
            .map_err(|_| "device_plugin_grant_unavailable")?;
        if !response.status().is_success() {
            return Err("device_plugin_grant_denied".into());
        }
        let receipt: Receipt = response
            .json()
            .await
            .map_err(|_| "device_plugin_grant_invalid")?;
        if !receipt.allowed
            || receipt.grant_id.is_empty()
            || grant_id.is_some_and(|id| id != receipt.grant_id)
            || receipt.user_id != owner.user_id
            || receipt.tenant_id != owner.tenant
            || receipt.project_id != owner.project
            || receipt.machine_id != self.machine
            || receipt.bundle_digest != digest_hex(&reference.digest)?
            || receipt.generation_id != generation
            || receipt.permission != permission
            || !permissions.is_subset(&receipt.approved_permissions)
        {
            return Err("device_plugin_grant_denied".into());
        }
        owner.fence(|| Ok(receipt.grant_id))
    }
}
#[derive(Deserialize)]
struct Receipt {
    allowed: bool,
    grant_id: String,
    user_id: String,
    tenant_id: String,
    project_id: String,
    machine_id: String,
    bundle_digest: String,
    generation_id: String,
    permission: String,
    approved_permissions: BTreeSet<String>,
}
