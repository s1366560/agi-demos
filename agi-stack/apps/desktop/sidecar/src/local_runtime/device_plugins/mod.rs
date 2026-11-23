//! Signed device packages for a trusted cloud principal, independent of local chat and ACKs.
use super::{device_mcp::CloudOwner, LocalRuntimeState};
use crate::{local_plugin_packages_v2 as packages, trusted_session::TrustedSessionBroker};
use agistack_plugin_host::protocol_v2::{
    signed_archive::{TrustedEd25519KeyV2, VerifiedBundleArchiveV2},
    BundleReferenceV2, ScopeKindV2, ScopeV2,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{collections::BTreeSet, sync::Arc};
mod grant;
mod local_chat;
mod runtime;
mod store;
#[cfg(test)]
mod tests;
use grant::Device;
use store::Selection;
pub(super) const SCHEMA: &str = store::SCHEMA;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    tenant_id: String,
    project_id: String,
    context_token: Option<String>,
    plugin_id: Option<String>,
    operation: Action,
}
#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum Action {
    List,
    Inspect {
        archive_id: String,
    },
    Install {
        archive_id: String,
        reference: BundleReferenceV2,
        approved_permissions: BTreeSet<String>,
        approve_for_day: bool,
        workspace_token: Option<String>,
        local_model: Option<local_chat::LocalModel>,
    },
    Revoke {
        reference: BundleReferenceV2,
        grant_id: String,
    },
    Invoke {
        reference: BundleReferenceV2,
        grant_id: String,
        tool: String,
        input: Value,
    },
}

fn generation_id(state: &LocalRuntimeState) -> Result<String, String> {
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .map_err(|_| "device_plugin_generation_unavailable")?;
    if lease.descriptor().publication_version.is_none() {
        return Err("device_plugin_cloud_generation_required".into());
    }
    Ok(grant::digest_hex(&lease.descriptor().digest)?.to_owned())
}
fn require_generation(state: &LocalRuntimeState, expected: &str) -> Result<(), String> {
    // Project generations are fenced online by Device::check before executing Wasm.
    if expected.starts_with('p') {
        return Ok(());
    }
    if generation_id(state)? != expected {
        return Err("device_plugin_generation_changed".into());
    }
    Ok(())
}

fn archive_bytes(state: &LocalRuntimeState, id: &str) -> Result<Vec<u8>, String> {
    use std::io::Read;
    let id = uuid::Uuid::parse_str(id).map_err(|_| "device_plugin_transfer_invalid")?;
    let root = state
        .app_data_dir
        .as_ref()
        .ok_or("device_plugin_data_root_required")?;
    let path = root.join("device-plugin-transfers").join(id.to_string());
    let meta = std::fs::symlink_metadata(&path).map_err(|_| "device_plugin_transfer_missing")?;
    if !meta.is_file() || meta.len() > packages::MAX_ARCHIVE_BYTES as u64 {
        return Err("device_plugin_archive_invalid".into());
    }
    let file = std::fs::File::open(&path).map_err(|_| "device_plugin_transfer_missing")?;
    let mut bytes = Vec::new();
    file.take(packages::MAX_ARCHIVE_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| "device_plugin_transfer_invalid")?;
    if bytes.is_empty() || bytes.len() > packages::MAX_ARCHIVE_BYTES {
        return Err("device_plugin_archive_invalid".into());
    }
    Ok(bytes)
}

fn device_target(
    raw: &[u8],
    keys: &[TrustedEd25519KeyV2],
) -> Result<(BundleReferenceV2, VerifiedBundleArchiveV2), String> {
    let outer = packages::inspect(raw, keys)?;
    let reference = outer.reference().clone();
    local_chat::declares(&outer)?;
    let Some(bytes) = outer.artifact_at_path("targets/desktop-sidecar.mspkg") else {
        return Ok((reference, outer));
    };
    let target = packages::inspect(bytes, keys)?;
    if target.reference().bundle_id != reference.bundle_id
        || target.reference().version != reference.version
    {
        return Err("device_plugin_target_mismatch".into());
    }
    Ok((reference, target))
}

pub(super) async fn operation(
    state: &Arc<LocalRuntimeState>,
    broker: &TrustedSessionBroker,
    input: Value,
) -> Result<Value, String> {
    let request: Request =
        serde_json::from_value(input).map_err(|_| "device_plugin_request_invalid")?;
    let owner = CloudOwner::resolve_for_plugin(
        broker,
        state.session_store.installation_id(),
        &request.tenant_id,
        &request.project_id,
    )
    .await?;
    let device = Device::current(state)?;
    let selected = match request.plugin_id.as_deref() {
        Some(plugin_id) => Some(grant::ProjectSelection::resolve(&owner, plugin_id).await?),
        None => None,
    };
    let generation = match &selected {
        Some(selection) => selection.generation_id.clone(),
        None => generation_id(state)?,
    };
    let context_token = {
        use sha2::{Digest, Sha256};
        format!(
            "{:x}",
            Sha256::digest(
                serde_json::to_vec(&json!([owner.token, generation]))
                    .map_err(|_| "device_plugin_context_invalid")?
            )
        )
    };
    if !matches!(request.operation, Action::List)
        && request.context_token.as_ref() != Some(&context_token)
    {
        return Err("device_plugin_context_changed".into());
    }
    let scope = ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some(owner.tenant.clone()),
        project_id: Some(owner.project.clone()),
        session_id: None,
    };
    let keys = state
        .local_plugin_signing_keys
        .as_ref()
        .map_err(|_| "device_plugin_trust_unavailable")?;
    // Serialize installs and calls, including their final authorization check.
    let _mutation = super::local_plugin_routes_v2::MUTATION.lock().await;
    owner.fence(|| require_generation(state, &generation))?;
    match request.operation {
        Action::List => {
            use futures_util::{stream, StreamExt};
            let selections = {
                let db = state
                    .session_store
                    .connection()
                    .map_err(|_| "device_plugin_store_unavailable")?;
                store::list(&db, &owner.scope.project_id)?
            };
            let can_manage = Device::can_manage(&owner).await?;
            let selections = selections.into_iter().filter(|item| {
                selected
                    .as_ref()
                    .is_none_or(|selection| item.reference.bundle_id == selection.plugin_id)
            });
            let statuses = stream::iter(selections)
                .map(|item| device.status(&owner, item, &generation, !keys.is_empty()))
                .buffered(4)
                .collect::<Vec<_>>()
                .await;
            owner.fence(|| require_generation(state, &generation))?;
            Ok(
                json!({"context_token":context_token,"can_manage":can_manage,"machine_id":device.machine,"device_fingerprint":device.fingerprint,
                "generation_id":generation,"user_id": owner.user_id,"installations":statuses, "trust_configured":!keys.is_empty()}),
            )
        }
        Action::Inspect { archive_id } => {
            let bytes = archive_bytes(state, &archive_id)?;
            let (reference, archive) = device_target(&bytes, keys)?;
            if let Some(selection) = &selected {
                selection.verify(&reference)?;
            }
            let (permissions, names, workspace) =
                local_chat::review(state, &scope, archive, &reference.digest, &context_token)
                    .await?;
            owner.fence(|| require_generation(state, &generation))?;
            Ok(
                json!({"reference":reference,"declared_permissions":permissions,"tools":names, "workspace": workspace.as_ref().map(|w| w.offer())}),
            )
        }
        Action::Install {
            archive_id,
            reference,
            approved_permissions,
            approve_for_day,
            workspace_token,
            local_model,
        } => {
            let bytes = archive_bytes(state, &archive_id)?;
            let (reviewed, archive) = device_target(&bytes, keys)?;
            if let Some(selection) = &selected {
                selection.verify(&reviewed)?;
            }
            let (permissions, tools, workspace) =
                local_chat::review(state, &scope, archive, &reference.digest, &context_token)
                    .await?;
            if workspace.as_ref().map(|w| &w.token) != workspace_token.as_ref() {
                return Err("device_local_workspace_review_required".into());
            }
            if let Some(model) = &local_model {
                if workspace.is_none() {
                    return Err("device_plugin_review_changed".into());
                }
                model.validate()?;
            }
            if reviewed != reference || permissions != approved_permissions {
                return Err("device_plugin_review_changed".into());
            }
            owner.recheck().await?;
            require_generation(state, &generation)?;
            if approve_for_day {
                device
                    .approve(&owner, &reference, &generation, &approved_permissions)
                    .await?;
            }
            let grant_id = device
                .check(&owner, &reference, &generation, &approved_permissions, None)
                .await?;
            let selection = Selection {
                reference,
                grant_id,
                generation_id: generation.clone(),
                approved_permissions,
                tools,
                workspace: workspace.map(|w| w.root),
                local_model,
                last_invoked_at: None,
                last_error: None,
            };
            owner.fence(|| {
                require_generation(state, &generation)?;
                let db = state
                    .session_store
                    .connection()
                    .map_err(|_| "device_plugin_store_unavailable")?;
                store::install(&db, &owner.scope.project_id, &selection, &bytes)
            })?;
            Ok(store::projection(&selection))
        }
        Action::Revoke {
            reference,
            grant_id,
        } => {
            {
                let db = state
                    .session_store
                    .connection()
                    .map_err(|_| "device_plugin_store_unavailable")?;
                store::load(&db, &owner.scope.project_id, &reference, &grant_id)?;
            }
            Device::revoke(&owner, &grant_id).await?;
            Ok(json!({"revoked":true}))
        }
        Action::Invoke {
            reference,
            grant_id,
            tool,
            input,
        } => {
            let (selection, bytes) = {
                let db = state
                    .session_store
                    .connection()
                    .map_err(|_| "device_plugin_store_unavailable")?;
                store::load(&db, &owner.scope.project_id, &reference, &grant_id)?
            };
            if selection.generation_id != generation {
                return Err("device_plugin_generation_changed".into());
            }
            if let Some(active) = &selected {
                active.verify(&reference)?;
            }
            require_generation(state, &selection.generation_id)?;
            let (reviewed, archive) = device_target(&bytes, keys)?;
            if local_chat::declares(&archive)? {
                if selected.is_none()
                    || reviewed != reference
                    || selection.workspace.is_none()
                    || tool != local_chat::TOOL
                {
                    return Err("device_plugin_review_changed".into());
                }
                drop(_mutation);
                return local_chat::invoke(state.clone(), owner, device, selection, input).await;
            }
            if reviewed != reference
                || archive.approved_permissions() != &selection.approved_permissions
            {
                return Err("device_plugin_review_changed".into());
            }
            let executable = archive.reference().clone();
            let prepared = runtime::Prepared::stage(&scope, archive).await?;
            let authority = Arc::new(runtime::Authority {
                state: state.clone(),
                device,
                scope,
                owner,
                selection,
                executable,
                tool,
            });
            let result = prepared.call(authority.clone(), input).await;
            prepared.close().await;
            authority.owner.fence(|| {
                let db = state
                    .session_store
                    .connection()
                    .map_err(|_| "device_plugin_store_unavailable")?;
                store::record_attempt(
                    &db,
                    &authority.owner.scope.project_id,
                    &authority.selection,
                    &result,
                )
            })?;
            result
        }
    }
}
