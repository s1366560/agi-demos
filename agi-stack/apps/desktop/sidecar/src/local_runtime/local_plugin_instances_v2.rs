//! Authenticated local project configuration and scope-private renderer delivery.

use super::{
    ensure_managed_resource_manager, ensure_project_scope, ensure_tenant_scope,
    AuthenticatedContext, LocalRuntimeState,
};
use crate::{local_plugin_configuration_v2 as configuration, plugin_snapshots_v2 as snapshots};
use agistack_plugin_host::protocol_v2::{ProfileSnapshotV2, ScopeKindV2, ScopeV2};
use agistack_plugin_host::{
    parse_control_plane_distribution_v2, ApplyStatusV2, SnapshotApplyReceiptV2,
};
use axum::{
    extract::{Extension, Query, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::Arc;

type Failure = (StatusCode, Json<Value>);
type ResultJson = Result<Json<Value>, Failure>;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScopeRequest {
    tenant_id: String,
    project_id: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ApplyRequest {
    tenant_id: String,
    project_id: String,
    expected_revision: u64,
    changes: Vec<configuration::InstanceChangeV2>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReceiptRequest {
    tenant_id: String,
    project_id: Option<String>,
    snapshot_digest: String,
    status: ApplyStatusV2,
    error_code: Option<String>,
}

fn failed(code: impl ToString) -> Failure {
    (
        StatusCode::CONFLICT,
        Json(json!({"code":code.to_string(),"detail":"Local plugin configuration is unavailable"})),
    )
}

fn require_scope(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    request: &ScopeRequest,
) -> Result<ScopeV2, Failure> {
    ensure_tenant_scope(auth, Some(&request.tenant_id))?;
    if let Some(project) = &request.project_id {
        ensure_project_scope(auth, Some(project))?;
    }
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .map_err(|_| failed("local_plugin_authority_unavailable"))?;
    if lease.descriptor().publication_version.is_some() {
        return Err(failed("local_plugin_authority_required"));
    }
    Ok(ScopeV2 {
        kind: if request.project_id.is_some() {
            ScopeKindV2::Project
        } else {
            ScopeKindV2::Tenant
        },
        tenant_id: Some(request.tenant_id.clone()),
        project_id: request.project_id.clone(),
        session_id: None,
    })
}

fn current(
    state: &LocalRuntimeState,
    scope: &ScopeV2,
) -> Result<
    (
        ProfileSnapshotV2,
        snapshots::LocalProfileConfigurationV2,
        String,
    ),
    Failure,
> {
    let base = super::platform_plugin_sync_v2::local_current_snapshot(state)
        .map_err(|_| failed("local_plugin_source_unavailable"))?;
    let identity = configuration::authority(scope).map_err(failed)?;
    snapshots::initialize_schema(&*state.session_store.connection().map_err(failed)?)
        .map_err(failed)?;
    let stored = snapshots::read_state(
        &*state.session_store.connection().map_err(failed)?,
        &identity,
    )
    .map_err(failed)?;
    let configuration = match stored.and_then(|state| state.configuration) {
        Some(configuration) => configuration,
        None => configuration::baseline(&base, scope).map_err(failed)?,
    };
    Ok((base, configuration, identity))
}

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/local-plugins/v2/instances", get(list))
        .route("/api/v1/local-plugins/v2/instances/apply", post(apply))
        .route("/api/v1/local-plugins/v2/renderer-view", get(renderer_view))
        .route(
            "/api/v1/local-plugins/v2/renderer-receipt",
            post(renderer_receipt),
        )
}

async fn list(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(request): Query<ScopeRequest>,
) -> ResultJson {
    let scope = require_scope(&state, &auth, &request)?;
    if scope.kind != ScopeKindV2::Project {
        return Err(failed("instance_project_required"));
    }
    instance_view(&state, &auth, &scope)
}

fn instance_view(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    scope: &ScopeV2,
) -> ResultJson {
    let (base, current, identity) = current(state, scope)?;
    let snapshot = configuration::compose(&base, &current, scope)
        .map_err(|_| failed("instance_configuration_invalid"))?;
    let editable = ensure_managed_resource_manager(auth).is_ok();
    let stored = snapshots::read_state(
        &*state.session_store.connection().map_err(failed)?,
        &identity,
    )
    .map_err(failed)?;
    let current_receipt = stored
        .as_ref()
        .and_then(|state| state.receipt.as_ref())
        .filter(|receipt| receipt.requested_digest == snapshot.digest);
    let status = match current_receipt {
        Some(receipt) if receipt.status == ApplyStatusV2::Ack => "ready",
        Some(_) => "degraded",
        None if stored.is_some() => "reconciling",
        None => "ready",
    };
    let active = accepted_snapshot(&base, scope, stored.as_ref())?;
    let mut rows = configuration::rows(&snapshot, scope, editable).map_err(failed)?;
    for row in &mut rows {
        let id = row["entry_id"].as_str().unwrap_or_default();
        let desired = snapshot.entries.iter().find(|entry| entry.entry_id == id);
        let applied = active.entries.iter().find(|entry| entry.entry_id == id);
        if desired != applied {
            row["state"] = json!({"status":if status=="degraded" {"failed"} else {"applying"},
                "reason_code":if status=="degraded" {Some("renderer_apply_failed")} else {None}});
        }
    }
    Ok(Json(
        json!({"scope":scope,"revision":current.desired.revision,
        "publication":{"status":status,"publication_id":identity,"generation":snapshot.generation},"instances":rows}),
    ))
}

fn accepted_snapshot(
    base: &ProfileSnapshotV2,
    scope: &ScopeV2,
    stored: Option<&snapshots::PluginSnapshotStateV2>,
) -> Result<ProfileSnapshotV2, Failure> {
    if let Some(accepted) = stored.and_then(|state| state.last_good.as_ref()) {
        return Ok(accepted.snapshot.clone());
    }
    let baseline = configuration::baseline(base, scope).map_err(failed)?;
    configuration::compose(base, &baseline, scope).map_err(failed)
}

async fn renderer_view(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(request): Query<ScopeRequest>,
) -> ResultJson {
    let scope = require_scope(&state, &auth, &request)?;
    // Keep candidate reads and requested-publication writes ordered with local edits
    // and installation changes; an older view must not replace a newer publication.
    let _guard = super::local_plugin_routes_v2::MUTATION.lock().await;
    let (base, current, identity) = current(&state, &scope)?;
    let snapshot = configuration::compose(&base, &current, &scope)
        .map_err(|_| failed("instance_configuration_invalid"))?;
    let connection = state.session_store.connection().map_err(failed)?;
    let stored = snapshots::read_state(&connection, &identity).map_err(failed)?;
    let requested_matches = stored.as_ref().is_some_and(|stored| {
        stored
            .requested
            .as_ref()
            .is_some_and(|value| value.snapshot.digest == snapshot.digest)
    });
    if !requested_matches {
        snapshots::record_requested(
            &connection,
            &identity,
            &distribution(&snapshot, current.desired.revision)?,
        )
        .map_err(failed)?;
    } else if stored.as_ref().is_some_and(|stored| {
        stored
            .receipt
            .as_ref()
            .is_some_and(|receipt| receipt.status == ApplyStatusV2::Nack)
    }) {
        let retained = accepted_snapshot(&base, &scope, stored.as_ref())?;
        return Ok(Json(json!({"source":"local","snapshot":retained})));
    }
    Ok(Json(json!({"source":"local","snapshot":snapshot})))
}

fn distribution(
    snapshot: &ProfileSnapshotV2,
    version: u64,
) -> Result<agistack_plugin_host::ControlPlaneDistributionV2, Failure> {
    parse_control_plane_distribution_v2(&json!({"schema_version":2,
        "descriptor":{"profile_id":snapshot.profile_id,"generation":snapshot.generation,"digest":snapshot.digest},
        "snapshot":snapshot,"envelope":{"version":version,"nonce":uuid::Uuid::new_v4().to_string(),
        "snapshot_digest":snapshot.digest,"type_url":"types.memstack.ai/plugin.profile.v2"}}).to_string()).map_err(|_| failed("instance_configuration_invalid"))
}

async fn renderer_receipt(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<ReceiptRequest>,
) -> ResultJson {
    let scope = require_scope(
        &state,
        &auth,
        &ScopeRequest {
            tenant_id: request.tenant_id,
            project_id: request.project_id,
        },
    )?;
    let identity = configuration::authority(&scope).map_err(failed)?;
    let mut connection = state.session_store.connection().map_err(failed)?;
    let Some(stored) = snapshots::read_state(&connection, &identity).map_err(failed)? else {
        return Err(failed("instance_publication_missing"));
    };
    let pending = stored
        .requested
        .as_ref()
        .ok_or_else(|| failed("instance_publication_missing"))?;
    if pending.snapshot.digest != request.snapshot_digest {
        return Err(failed("instance_receipt_superseded"));
    }
    let accepted = request.status == ApplyStatusV2::Ack;
    let receipt = SnapshotApplyReceiptV2 {
        status: request.status,
        requested_version: pending.envelope.version,
        requested_digest: pending.snapshot.digest.clone(),
        applied_version: if accepted {
            Some(pending.envelope.version)
        } else {
            stored
                .last_good
                .as_ref()
                .map(|value| value.envelope.version)
        },
        applied_digest: if accepted {
            Some(pending.snapshot.digest.clone())
        } else {
            stored
                .last_good
                .as_ref()
                .map(|value| value.snapshot.digest.clone())
        },
        error_code: if accepted {
            None
        } else {
            Some(
                request
                    .error_code
                    .filter(|value| !value.is_empty() && value.len() <= 128)
                    .unwrap_or_else(|| "renderer_apply_failed".into()),
            )
        },
        error_message: if accepted {
            None
        } else {
            Some("Renderer rejected configuration".into())
        },
    };
    snapshots::record_receipt(
        &mut connection,
        &identity,
        &pending.envelope.nonce,
        &receipt,
    )
    .map_err(failed)?;
    Ok(Json(
        json!({"status":if accepted {"ready"} else {"degraded"}}),
    ))
}

async fn apply(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(request): Json<ApplyRequest>,
) -> ResultJson {
    ensure_managed_resource_manager(&auth)?;
    let requested_scope = ScopeRequest {
        tenant_id: request.tenant_id,
        project_id: Some(request.project_id),
    };
    let scope = require_scope(&state, &auth, &requested_scope)?;
    let _guard = super::local_plugin_routes_v2::MUTATION.lock().await;
    let (base, current, identity) = current(&state, &scope)?;
    let candidate = configuration::revise(
        &base,
        &current,
        &scope,
        request.expected_revision,
        &request.changes,
    )
    .map_err(failed)?;
    let snapshot = configuration::compose(&base, &candidate, &scope)
        .map_err(|_| failed("instance_configuration_invalid"))?;
    let distribution = distribution(&snapshot, candidate.desired.revision)?;
    // The final permission and CAS checks run while holding the same application DB mutex.
    let connection = super::local_plugin_routes_v2::manager_connection(&state, &auth)?;
    snapshots::record_configuration(
        &connection,
        &identity,
        request.expected_revision,
        candidate,
        distribution.clone(),
    )
    .map_err(|_| failed("instance_revision_conflict"))?;
    drop(connection);
    instance_view(&state, &auth, &scope)
}

#[cfg(test)]
mod tests;
