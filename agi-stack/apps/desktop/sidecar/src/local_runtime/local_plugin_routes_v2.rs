//! Authenticated project-manager import and lifecycle of host-trusted local packages.
use super::{
    ensure_managed_resource_manager, ensure_project_scope, ensure_tenant_scope,
    AuthenticatedContext, LocalRuntimeState,
};
use crate::{local_plugin_installations_v2 as store, local_plugin_packages_v2 as packages};
use agistack_plugin_host::protocol_v2::{
    signed_archive::verify_signed_bundle_archive_v2, BundleReferenceV2, ScopeKindV2, ScopeV2,
};
use axum::{
    extract::{DefaultBodyLimit, Extension, Path, Query, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{collections::BTreeSet, sync::Arc};
type Failure = (StatusCode, Json<Value>);
type ResultJson = Result<Json<Value>, Failure>;
static MUTATION: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScopeRequest {
    tenant_id: String,
    project_id: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct InspectRequest {
    tenant_id: String,
    project_id: String,
    archive_base64: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ImportRequest {
    tenant_id: String,
    project_id: String,
    reference: BundleReferenceV2,
    archive_base64: String,
    approved_permissions: BTreeSet<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LifecycleRequest {
    tenant_id: String,
    project_id: String,
    reference: BundleReferenceV2,
}
fn failure(status: StatusCode, code: &str, detail: impl ToString) -> Failure {
    (
        status,
        Json(json!({"code":code,"detail":detail.to_string()})),
    )
}
fn invalid(detail: impl ToString) -> Failure {
    failure(
        StatusCode::UNPROCESSABLE_ENTITY,
        "local_plugin_request_invalid",
        detail,
    )
}
fn verification(detail: impl ToString) -> Failure {
    failure(
        StatusCode::UNPROCESSABLE_ENTITY,
        "local_plugin_verification_failed",
        detail,
    )
}
fn storage(detail: impl ToString) -> Failure {
    failure(StatusCode::CONFLICT, "local_plugin_not_found", detail)
}
fn keys(
    state: &LocalRuntimeState,
) -> Result<Vec<agistack_plugin_host::protocol_v2::signed_archive::TrustedEd25519KeyV2>, Failure> {
    let keys = state.local_plugin_signing_keys.clone().map_err(|error| {
        failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "local_plugin_trust_unavailable",
            error,
        )
    })?;
    if keys.is_empty() {
        return Err(failure(
            StatusCode::SERVICE_UNAVAILABLE,
            "local_plugin_trust_unavailable",
            "No host signing trust is configured",
        ));
    }
    Ok(keys)
}
fn scope(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    tenant: &str,
    project: &str,
) -> Result<ScopeV2, Failure> {
    ensure_tenant_scope(auth, Some(tenant))?;
    ensure_project_scope(auth, Some(project))?;
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .map_err(|_| {
            failure(
                StatusCode::SERVICE_UNAVAILABLE,
                "local_plugin_activation_failed",
                "Local plugin authority is unavailable",
            )
        })?;
    if lease.descriptor().publication_version.is_some() {
        return Err(failure(
            StatusCode::CONFLICT,
            "local_plugin_request_invalid",
            "Local plugin management requires local authority",
        ));
    }
    Ok(ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: Some(tenant.into()),
        project_id: Some(project.into()),
        session_id: None,
    })
}
fn decode(raw: &str) -> Result<Vec<u8>, Failure> {
    if raw.len() > packages::MAX_ARCHIVE_BYTES.div_ceil(3) * 4 {
        return Err(invalid("Plugin archive exceeds 64 MiB"));
    }
    let bytes = STANDARD
        .decode(raw)
        .map_err(|_| invalid("Plugin archive base64 is invalid"))?;
    if bytes.len() > packages::MAX_ARCHIVE_BYTES {
        return Err(invalid("Plugin archive exceeds 64 MiB"));
    }
    Ok(bytes)
}
pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/local-plugins/v2/installations", get(list))
        .route(
            "/api/v1/local-plugins/v2/installations/:bundle_id/:action",
            post(lifecycle),
        )
        .merge(
            Router::new()
                .route(
                    "/api/v1/local-plugins/v2/installations/inspect",
                    post(inspect),
                )
                .route(
                    "/api/v1/local-plugins/v2/installations/import",
                    post(import),
                )
                .layer(DefaultBodyLimit::max(90 * 1024 * 1024)),
        )
}
async fn list(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(request): Query<ScopeRequest>,
) -> ResultJson {
    let scope = scope(&state, &auth, &request.tenant_id, &request.project_id)?;
    let active_generation = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .ok()
        .map(|lease| lease.descriptor().generation);
    let base_generation = super::platform_plugin_sync_v2::local_base_snapshot(&state)
        .map_err(storage)?
        .generation;
    let activation_error = state
        .local_plugin_activation_error
        .lock()
        .map_err(storage)?
        .clone();
    let connection = state.session_store.connection().map_err(storage)?;
    let expected_generation =
        base_generation.checked_add(store::revision(&connection).map_err(storage)?);
    let installations: Vec<_> = store::list(&connection, &scope)
        .map_err(storage)?
        .into_iter()
        .map(|item| {
            let status = if !item.enabled || item.authorization_status == "revoked" {
                "inactive"
            } else if activation_error.is_some() {
                "failed"
            } else if active_generation == expected_generation {
                "active"
            } else {
                "pending"
            };
            let mut value = serde_json::to_value(item).map_err(storage)?;
            value["activation_status"] = status.into();
            value["activation_error"] = if status == "failed" {
                json!(activation_error)
            } else {
                Value::Null
            };
            Ok(value)
        })
        .collect::<Result<_, Failure>>()?;
    Ok(Json(
        json!({"installations":installations,"trust_configured":state.local_plugin_signing_keys.as_ref().is_ok_and(|keys|!keys.is_empty())}),
    ))
}
async fn inspect(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<InspectRequest>,
) -> ResultJson {
    ensure_managed_resource_manager(&auth)?;
    let scope = scope(&state, &auth, &request.tenant_id, &request.project_id)?;
    let keys = keys(&state)?;
    let bytes = decode(&request.archive_base64)?;
    let archive = tokio::task::spawn_blocking(move || packages::inspect(&bytes, &keys))
        .await
        .map_err(verification)?
        .map_err(verification)?;
    Ok(Json(
        json!({"reference":archive.reference(),"scope":scope,"declared_permissions":archive.approved_permissions(),"plugins":archive.manifest().manifests.iter().map(|item|json!({"plugin_id":item.plugin_id,"version":item.version})).collect::<Vec<_>>(),"verified":true}),
    ))
}
async fn import(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<ImportRequest>,
) -> ResultJson {
    ensure_managed_resource_manager(&auth)?;
    let scope = scope(&state, &auth, &request.tenant_id, &request.project_id)?;
    if request.reference.source
        != format!(
            "local-file://{}/{}",
            request.reference.bundle_id, request.reference.version
        )
    {
        return Err(invalid("Local package source is invalid"));
    }
    let keys = keys(&state)?;
    let bytes = decode(&request.archive_base64)?;
    let _guard = MUTATION.lock().await;
    let archive = verify_signed_bundle_archive_v2(
        &bytes,
        &request.reference,
        &keys,
        &request.approved_permissions,
    )
    .map_err(verification)?;
    preflight_candidate(
        &state,
        &keys,
        store::InstalledBundleV2 {
            scope: scope.clone(),
            archive,
        },
    )
    .await?;
    // Recheck session context after asynchronous compilation before persisting approvals.
    if !state
        .session_store
        .session_context_is_current(&auth, chrono::Utc::now().timestamp_millis())
        .map_err(storage)?
    {
        return Err(failure(
            StatusCode::FORBIDDEN,
            "local_plugin_request_invalid",
            "Session context changed",
        ));
    }
    self::scope(&state, &auth, &request.tenant_id, &request.project_id)?;
    store::install(
        &*manager_connection(&state, &auth)?,
        &keys,
        &scope,
        &request.reference,
        &bytes,
        &request.approved_permissions,
    )
    .map_err(verification)?;
    state.local_plugin_changes.notify_one();
    Ok(Json(
        json!({"reference":request.reference,"scope":scope,"status":"installed"}),
    ))
}
async fn lifecycle(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path((bundle_id, action)): Path<(String, String)>,
    Json(request): Json<LifecycleRequest>,
) -> ResultJson {
    ensure_managed_resource_manager(&auth)?;
    let scope = scope(&state, &auth, &request.tenant_id, &request.project_id)?;
    if bundle_id != request.reference.bundle_id {
        return Err(invalid("Plugin identity differs from route"));
    }
    let _guard = MUTATION.lock().await;
    if action == "enable" {
        let signing_keys = keys(&state)?;
        let candidate = {
            let connection = manager_connection(&state, &auth)?;
            store::for_activation(&connection, &signing_keys, &scope, &request.reference)
                .map_err(verification)?
        };
        preflight_candidate(&state, &signing_keys, candidate).await?;
        self::scope(&state, &auth, &request.tenant_id, &request.project_id)?;
    }
    let connection = manager_connection(&state, &auth)?;
    let status = match action.as_str() {
        "enable" => {
            store::set_enabled(
                &connection,
                &keys(&state)?,
                &scope,
                &request.reference,
                true,
            )
            .map_err(verification)?;
            "enabled"
        }
        "disable" => {
            store::set_enabled(&connection, &[], &scope, &request.reference, false)
                .map_err(storage)?;
            "disabled"
        }
        "revoke" => {
            store::revoke(&connection, &scope, &request.reference).map_err(storage)?;
            "revoked"
        }
        "uninstall" => {
            store::uninstall(&connection, &scope, &request.reference).map_err(storage)?;
            "uninstalled"
        }
        _ => return Err(invalid("Unknown plugin lifecycle action")),
    };
    state.local_plugin_changes.notify_one();
    Ok(Json(
        json!({"reference":request.reference,"scope":scope,"status":status}),
    ))
}

// Serialize the final approval check and mutation on the same application-store connection.
fn manager_connection<'a>(
    state: &'a LocalRuntimeState,
    auth: &AuthenticatedContext,
) -> Result<std::sync::MutexGuard<'a, rusqlite::Connection>, Failure> {
    let connection = state.session_store.connection().map_err(storage)?;
    let allowed:bool=connection.query_row("SELECT EXISTS(SELECT 1 FROM desktop_user_sessions s
        JOIN desktop_workspace_contexts c ON c.user_id=s.user_id
        JOIN desktop_tenant_memberships m ON m.user_id=s.user_id AND m.tenant_id=c.tenant_id
        JOIN desktop_tenants t ON t.id=c.tenant_id
        JOIN desktop_projects p ON p.id=c.project_id AND p.tenant_id=c.tenant_id
        WHERE s.id=?1 AND s.user_id=?2 AND s.status='active' AND s.expires_at_ms>?3
        AND c.tenant_id=?4 AND c.project_id=?5 AND c.revision=?6
        AND m.status='active' AND m.role IN ('owner','admin') AND t.status='active' AND p.status='active')",
        rusqlite::params![auth.session_id,auth.user.user_id,chrono::Utc::now().timestamp_millis(),auth.workspace.tenant_id,auth.workspace.project_id,auth.workspace.revision],|row|row.get(0)).map_err(storage)?;
    if !allowed {
        return Err(failure(
            StatusCode::FORBIDDEN,
            "local_plugin_request_invalid",
            "Current project manager authority is required",
        ));
    }
    Ok(connection)
}

async fn preflight_candidate(
    state: &LocalRuntimeState,
    keys: &[agistack_plugin_host::protocol_v2::signed_archive::TrustedEd25519KeyV2],
    candidate: store::InstalledBundleV2,
) -> Result<(), Failure> {
    let base = super::platform_plugin_sync_v2::local_base_snapshot(state).map_err(verification)?;
    let (mut installed, revision) = {
        let connection = state.session_store.connection().map_err(storage)?;
        (
            store::load_enabled(&connection, keys).map_err(verification)?,
            store::revision(&connection).map_err(storage)?,
        )
    };
    installed.retain(|item| {
        !(item.scope == candidate.scope
            && item.archive.reference().bundle_id == candidate.archive.reference().bundle_id)
    });
    installed.push(candidate);
    let (snapshot, _, archives) =
        packages::compose(&base, installed, revision + 1).map_err(verification)?;
    let staged = super::platform_plugin_sync_v2::desktop_loader(
        state.app_data_dir.clone(),
        state.local_knowledge_acceptance.clone(),
    )
    .with_verified_archives(archives)
    .stage(snapshot)
    .await
    .map_err(|error| {
        failure(
            StatusCode::UNPROCESSABLE_ENTITY,
            "local_plugin_activation_failed",
            error,
        )
    })?;
    agistack_plugin_host::PluginSnapshotReconcilerV2::new(
        agistack_plugin_host::LoaderV2::for_target(
            agistack_plugin_host::DataPlaneTargetV2::DesktopSidecar,
            [],
        ),
    )
    .discard_staged_snapshot(staged)
    .await;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn final_mutation_guard_rechecks_current_role_and_session_inside_store_lock() {
        let state = super::super::tests::test_state("local-plugin-manager-guard");
        let auth = state
            .session_store
            .validate_session_credential(
                "local-plugin-manager-guard",
                chrono::Utc::now().timestamp_millis(),
            )
            .unwrap()
            .unwrap();
        assert!(manager_connection(&state, &auth).is_ok());
        state
            .session_store
            .connection()
            .unwrap()
            .execute(
                "UPDATE desktop_tenant_memberships SET role='viewer' WHERE user_id=?1",
                [&auth.user.user_id],
            )
            .unwrap();
        assert!(manager_connection(&state, &auth).is_err());
        state
            .session_store
            .connection()
            .unwrap()
            .execute(
                "UPDATE desktop_tenant_memberships SET role='owner' WHERE user_id=?1",
                [&auth.user.user_id],
            )
            .unwrap();
        state
            .session_store
            .revoke_session(
                "local-plugin-manager-guard",
                chrono::Utc::now().timestamp_millis(),
            )
            .unwrap();
        assert!(manager_connection(&state, &auth).is_err());
    }
}

/// Read-only projection for the unified marketplace; signed activation remains authoritative here.
pub(super) async fn marketplace_installations(
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
) -> ResultJson {
    let request = ScopeRequest {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    list(State(state), Extension(auth), Query(request)).await
}
