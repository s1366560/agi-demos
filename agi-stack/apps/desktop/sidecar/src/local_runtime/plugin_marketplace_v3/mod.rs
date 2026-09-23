//! Cloud-independent, project-scoped marketplace. Persist only metadata and vault references.
pub(in crate::local_runtime) mod cache;
mod hook_audit;
pub(super) mod hooks;
mod jobs;
mod oauth;
pub(in crate::local_runtime) mod oauth_http;
mod recovery;
pub(super) use recovery::recover;
#[cfg(test)]
mod cache_tests;
#[cfg(test)]
mod generation_tests;
#[cfg(test)]
mod lifecycle_tests;
#[cfg(test)]
mod oauth_tests;
mod package;
mod resources;
mod signed_v2;
mod sources;
#[cfg(test)]
mod tests;

use super::{
    ensure_managed_resource_manager, ensure_project_scope, ensure_tenant_scope,
    AuthenticatedContext, LocalRuntimeState,
};
use axum::{
    extract::{Extension, Path, Query, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use package::{Package, Result as PackageResult};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use sources::Source;
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};

type Failure = (StatusCode, Json<Value>);
type Response = Result<Json<Value>, Failure>;
static MUTATION: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
#[derive(Clone, Default, Deserialize, Serialize)]
struct Database {
    #[serde(default)]
    scope: Option<StoredScope>,
    #[serde(default)]
    snapshots: BTreeMap<String, cache::Snapshot>,
    #[serde(default)]
    oauth_receipts: BTreeMap<String, (String, Value)>,
    #[serde(default)]
    transition: Option<Transition>,
    sources: Vec<Source>,
    #[serde(default)]
    jobs: BTreeMap<String, jobs::Job>,
    preflights: BTreeMap<String, Preflight>,
    installations: Vec<Installation>,
    receipts: BTreeMap<String, (String, Value)>,
}
#[derive(Clone, Deserialize, Serialize)]
struct StoredScope {
    tenant_id: String,
    project_id: String,
}
#[derive(Clone, Deserialize, Serialize)]
struct Transition {
    installation_id: String,
    replacement: Installation,
}
#[derive(Clone, Deserialize, Serialize)]
struct Preflight {
    #[serde(default)]
    created_at: i64,
    id: String,
    package: Package,
    digest: String,
}
#[derive(Clone, Deserialize, Serialize)]
pub(super) struct Installation {
    id: String,
    plugin_id: String,
    source_id: String,
    name: String,
    version: String,
    status: String,
    capabilities: Vec<String>,
    error: Option<String>,
    package: Package,
    permissions: Vec<String>,
    #[serde(default)]
    server_ids: Vec<String>,
    #[serde(default)]
    skill_ids: Vec<String>,
    #[serde(default)]
    oauth_services: Vec<oauth::Service>,
}
impl Installation {
    fn public(&self) -> Value {
        let credentials: std::collections::BTreeSet<String> = self
            .package
            .servers
            .values()
            .flat_map(|server| {
                ["env", "headers"]
                    .into_iter()
                    .filter_map(move |field| server.get(field).and_then(Value::as_object))
                    .flat_map(|bindings| {
                        bindings.values().filter_map(Value::as_str).map(|value| {
                            value
                                .trim_start_matches("${")
                                .trim_end_matches('}')
                                .to_owned()
                        })
                    })
            })
            .collect();
        json!({"id":self.id,"plugin_id":self.plugin_id,"source_id":self.source_id,"name":self.name,"version":self.version,"status":self.status,"capabilities":self.capabilities,"error":self.error,"required_credentials":credentials,"oauth_services":self.oauth_services.iter().map(oauth::Service::public).collect::<Vec<_>>()})
    }
}
#[derive(Clone, Deserialize)]
struct Scope {
    tenant_id: Option<String>,
    project_id: Option<String>,
}
#[derive(Clone, Deserialize)]
struct Request {
    #[serde(skip)]
    job_id: Option<String>,
    #[serde(flatten)]
    scope: Scope,
    #[serde(default)]
    source_id: String,
    #[serde(default)]
    plugin_id: String,
    version: Option<String>,
    #[serde(default)]
    preflight_id: String,
    #[serde(default)]
    idempotency_key: String,
    #[serde(default)]
    approved_permissions: Vec<String>,
    #[serde(default, alias = "configuration")]
    credentials: BTreeMap<String, String>,
}
fn fail(detail: impl ToString) -> Failure {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({"code":"plugin_marketplace_v3_invalid","detail":detail.to_string()})),
    )
}
fn authorize(auth: &AuthenticatedContext, scope: &Scope, write: bool) -> Result<(), Failure> {
    ensure_tenant_scope(auth, scope.tenant_id.as_deref())?;
    ensure_project_scope(auth, scope.project_id.as_deref())?;
    if write {
        ensure_managed_resource_manager(auth)?;
    }
    Ok(())
}
fn root(state: &LocalRuntimeState, tenant: &str, project: &str) -> PackageResult<PathBuf> {
    let base = state
        .app_data_dir
        .as_ref()
        .ok_or("application data directory unavailable")?;
    let key = format!(
        "{:x}",
        Sha256::digest(format!("{tenant}\0{project}").as_bytes())
    );
    Ok(base.join("plugin-marketplace-v3").join(key))
}
fn auth_root(state: &LocalRuntimeState, auth: &AuthenticatedContext) -> Result<PathBuf, Failure> {
    root(state, &auth.workspace.tenant_id, &auth.workspace.project_id).map_err(fail)
}
fn load(root: &std::path::Path) -> PackageResult<Database> {
    let file = root.join("state.json");
    let mut data: Database = match std::fs::read(file) {
        Ok(bytes) => serde_json::from_slice(&bytes).map_err(|e| e.to_string()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Database::default()),
        Err(e) => Err(e.to_string()),
    }?;
    for (key, kind) in [
        ("PLUGIN_MARKETPLACE_CURATED_DIRECTORY", "local"),
        ("PLUGIN_MARKETPLACE_CATALOG_URL", "https"),
    ] {
        if let Ok(location) = std::env::var(key) {
            if !location.is_empty()
                && !data
                    .sources
                    .iter()
                    .any(|source| source.location == location)
            {
                let id = format!(
                    "curated-{:x}",
                    Sha256::digest(format!("{kind}:{location}").as_bytes())
                );
                data.sources.push(Source {
                    id,
                    name: "MemStack".into(),
                    kind: kind.into(),
                    location,
                    trusted: true,
                });
            }
        }
    }
    Ok(data)
}
fn save(root: &std::path::Path, data: &Database) -> PackageResult<()> {
    std::fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let file = root.join(format!("state-{}.tmp", uuid::Uuid::new_v4()));
    let bytes = serde_json::to_vec(data).map_err(|e| e.to_string())?;
    std::fs::write(&file, bytes).map_err(|e| e.to_string())?;
    std::fs::File::open(&file)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    std::fs::rename(file, root.join("state.json")).map_err(|e| e.to_string())
}
pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/plugin-marketplace/v3/cache",
            get(cache::stats).post(cache::cleanup),
        )
        .route(
            "/api/v1/plugin-marketplace/v3/installations/:id/oauth/:server/status",
            get(oauth::status),
        )
        .route(
            "/api/v1/plugin-marketplace/v3/installations/:id/oauth/:server/:action",
            post(oauth::action),
        )
        .route("/api/v1/plugin-marketplace/v3/catalog", get(catalog))
        .route(
            "/api/v1/plugin-marketplace/v3/sources",
            get(list_sources).post(add_source),
        )
        .route(
            "/api/v1/plugin-marketplace/v3/sources/:id",
            axum::routing::delete(delete_source),
        )
        .route("/api/v1/plugin-marketplace/v3/preflight", post(preflight))
        .route("/api/v1/plugin-marketplace/v3/jobs", get(jobs::list_jobs))
        .route("/api/v1/plugin-marketplace/v3/jobs/:id", get(jobs::get_job))
        .route(
            "/api/v1/plugin-marketplace/v3/installations",
            get(list_installations).post(jobs::start_install),
        )
        .route(
            "/api/v1/plugin-marketplace/v3/installations/:id/:action",
            post(jobs::start_lifecycle),
        )
}
async fn list_sources(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, false)?;
    Ok(Json(
        json!({"items":load(&auth_root(&state,&auth)?).map_err(fail)?.sources}),
    ))
}
async fn add_source(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<Value>,
) -> Response {
    let scope: Scope = serde_json::from_value(body.clone()).map_err(fail)?;
    authorize(&auth, &scope, true)?;
    let source = Source {
        id: uuid::Uuid::new_v4().to_string(),
        name: package::text(&body, "name"),
        kind: package::text(&body, "kind"),
        location: package::text(&body, "location"),
        trusted: body
            .get("trusted")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    };
    sources::validate(&source).map_err(fail)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    if data
        .sources
        .iter()
        .any(|s| s.kind == source.kind && s.location == source.location)
    {
        return Err(fail("source already exists"));
    }
    data.sources.push(source.clone());
    save(&root, &data).map_err(fail)?;
    Ok(Json(json!(source)))
}
async fn delete_source(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(id): Path<String>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, true)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    if data
        .installations
        .iter()
        .any(|i| i.source_id == id && i.status != "uninstalled")
    {
        return Err(fail(
            "uninstall source plugins before removing their source",
        ));
    }
    let before = data.sources.len();
    data.sources.retain(|s| s.id != id);
    if before == data.sources.len() {
        return Err(fail("source not found"));
    }
    save(&root, &data).map_err(fail)?;
    Ok(Json(json!({"id":id,"deleted":true})))
}
async fn catalog(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, false)?;
    let root = auth_root(&state, &auth)?;
    let data = load(&root).map_err(fail)?;
    let mut items = Vec::new();
    let mut errors = Vec::new();
    for source in data.sources {
        let scratch = sources::Scratch::new(&root.join("downloads")).map_err(fail)?;
        match sources::packages(&source, &scratch.0).await {
            Ok(packages) => items.extend(packages.into_iter().map(|p| json!(p.descriptor))),
            Err(error) => errors.push(json!({"source_id":source.id,"detail":error,"error":error})),
        }
    }
    match signed_v2::records(state, auth).await {
        Ok(records) => items.extend(records),
        Err(error) => errors.push(json!({"source_id":"signed-v2","error":error})),
    }
    Ok(Json(json!({"items":items,"errors":errors})))
}
async fn preflight(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<Request>,
) -> Response {
    authorize(&auth, &body.scope, true)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    let source = data
        .sources
        .iter()
        .find(|s| s.id == body.source_id)
        .ok_or_else(|| fail("source not found"))?;
    if !source.trusted {
        return Err(fail(
            "source must be explicitly trusted before installation",
        ));
    }
    let scratch = sources::Scratch::new(&root.join("downloads")).map_err(fail)?;
    let package = sources::packages(source, &scratch.0)
        .await
        .map_err(fail)?
        .into_iter()
        .find(|p| {
            p.descriptor.id == body.plugin_id
                && body
                    .version
                    .as_ref()
                    .is_none_or(|v| &p.descriptor.version == v)
        })
        .ok_or_else(|| fail("plugin/version not found"))?;
    let id = uuid::Uuid::new_v4().to_string();
    let snapshot = root.join("snapshots").join(&id);
    package::snapshot(&package.root, &snapshot).map_err(fail)?;
    let package = package::parse(&snapshot, &source.id).map_err(fail)?;
    let digest = package::digest(&snapshot).map_err(fail)?;
    cache::register(&mut data, &snapshot);
    let previous = data.installations.iter().find(|installation| {
        installation.plugin_id == package.descriptor.id && installation.status != "uninstalled"
    });
    let missing =
        resources::missing_credentials(&state, &auth, &package, previous).map_err(fail)?;
    let mut reasons = package.descriptor.reasons.clone();
    reasons.extend(
        missing
            .iter()
            .map(|key| format!("credentials_required:{key}")),
    );
    let oauth_services = oauth::services(&package);
    let result = json!({"id":id,"plugin":package.descriptor,"permissions":package.descriptor.permissions,"compatible":package.descriptor.compatible,"reasons":reasons,"digest":digest,"needs_configuration":!missing.is_empty() || !oauth_services.is_empty(),"required_credentials":missing,"oauth_services":oauth_services.iter().map(oauth::Service::public).collect::<Vec<_>>()});
    data.preflights.insert(
        id.clone(),
        Preflight {
            created_at: chrono::Utc::now().timestamp(),
            id,
            package,
            digest,
        },
    );
    save(&root, &data).map_err(fail)?;
    Ok(Json(result))
}
async fn list_installations(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, false)?;
    let mut items = load(&auth_root(&state, &auth)?)
        .map_err(fail)?
        .installations
        .iter()
        .filter(|i| i.status != "uninstalled")
        .map(Installation::public)
        .collect::<Vec<_>>();
    let mut errors = Vec::new();
    match signed_v2::records(state, auth).await {
        Ok(records) => items.extend(records),
        Err(error) => errors.push(json!({"source_id":"signed-v2","error":error})),
    }
    Ok(Json(json!({"items":items,"errors":errors})))
}
fn verified(data: &Database, body: &Request) -> Result<Preflight, Failure> {
    let preflight = data
        .preflights
        .get(&body.preflight_id)
        .ok_or_else(|| fail("preflight not found"))?
        .clone();
    if preflight.created_at + 86400 <= chrono::Utc::now().timestamp() {
        return Err(fail("preflight_expired"));
    }
    if !preflight.package.descriptor.compatible {
        return Err(fail(preflight.package.descriptor.reasons.join("; ")));
    }
    if !data
        .sources
        .iter()
        .any(|s| s.id == preflight.package.descriptor.source_id && s.trusted)
    {
        return Err(fail("source trust is no longer available"));
    }
    if preflight.digest != package::digest(&preflight.package.root).map_err(fail)? {
        return Err(fail("snapshot changed since preflight"));
    }
    if preflight
        .package
        .descriptor
        .permissions
        .iter()
        .any(|p| !body.approved_permissions.contains(p))
    {
        return Err(fail("all plugin permissions must be approved"));
    }
    Ok(preflight)
}
fn request_hash(body: &Request, operation: &str) -> String {
    let serialized=json!({"operation":operation,"preflight_id":body.preflight_id,"permissions":body.approved_permissions,"configuration":body.credentials}).to_string();
    format!("{:x}", Sha256::digest(serialized.as_bytes()))
}
fn receipt(data: &Database, body: &Request, operation: &str) -> Result<Option<Value>, Failure> {
    if body.idempotency_key.is_empty() || body.idempotency_key.len() > 128 {
        return Err(fail("idempotency key is required (maximum 128 characters)"));
    }
    let hash = request_hash(body, operation);
    match data.receipts.get(&body.idempotency_key) {
        Some((previous, value)) if previous == &hash => Ok(Some(value.clone())),
        Some(_) => Err(fail("idempotency conflict")),
        None => Ok(None),
    }
}
fn finish(
    root: &std::path::Path,
    data: &mut Database,
    body: &Request,
    operation: &str,
    result: Value,
) -> Response {
    data.receipts.insert(
        body.idempotency_key.clone(),
        (request_hash(body, operation), result.clone()),
    );
    cache::collect(root, data, true).map_err(fail)?;
    save(root, data).map_err(fail)?;
    Ok(Json(result))
}
async fn install(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<Request>,
) -> Response {
    authorize(&auth, &body.scope, true)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    if let Some(value) = receipt(&data, &body, "install")? {
        return Ok(Json(value));
    }
    let preflight = verified(&data, &body)?;
    let descriptor = &preflight.package.descriptor;
    if data
        .installations
        .iter()
        .any(|i| i.plugin_id == descriptor.id && i.status != "uninstalled")
    {
        return Err(fail("plugin is already installed; use update"));
    }
    let mut installation = Installation {
        id: preflight.id.clone(),
        plugin_id: descriptor.id.clone(),
        source_id: descriptor.source_id.clone(),
        name: descriptor.name.clone(),
        version: descriptor.version.clone(),
        status: "downloaded".into(),
        capabilities: descriptor.capabilities.clone(),
        error: None,
        permissions: descriptor.permissions.clone(),
        oauth_services: oauth::services(&preflight.package),
        package: preflight.package,
        server_ids: vec![],
        skill_ids: vec![],
    };
    jobs::stage(&root, &mut data, &body, "registering")?;
    resources::register(&state, &auth, &mut installation).map_err(fail)?;
    jobs::stage(&root, &mut data, &body, "verifying")?;
    if installation.package.required.is_empty() && installation.oauth_services.is_empty() {
        resources::set_enabled(&state, &auth, &mut installation, true).map_err(fail)?;
        check_running(&state, &auth, &mut installation).await?;
    } else {
        installation.status = "needs_configuration".into();
    }
    let result = installation.public();
    data.installations.push(installation);
    data.preflights.remove(&body.preflight_id);
    finish(&root, &mut data, &body, "install", result)
}
async fn lifecycle(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path((id, action)): Path<(String, String)>,
    Json(body): Json<Request>,
) -> Response {
    authorize(&auth, &body.scope, true)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    let operation = format!("{id}:{action}");
    if let Some(value) = receipt(&data, &body, &operation)? {
        return Ok(Json(value));
    }
    let index = data
        .installations
        .iter()
        .position(|i| i.id == id && i.status != "uninstalled")
        .ok_or_else(|| fail("installation not found"))?;
    if action == "update" {
        let preflight = verified(&data, &body)?;
        let old = &data.installations[index];
        if old.plugin_id != preflight.package.descriptor.id
            || old.source_id != preflight.package.descriptor.source_id
        {
            return Err(fail("update must match the installed plugin and source"));
        }
        let mut replacement = old.clone();
        replacement.id = uuid::Uuid::new_v4().to_string();
        replacement.package = preflight.package;
        replacement.version = replacement.package.descriptor.version.clone();
        replacement.permissions = replacement.package.descriptor.permissions.clone();
        replacement.oauth_services = oauth::services(&replacement.package);
        replacement.server_ids.clear();
        replacement.skill_ids.clear();
        jobs::stage(&root, &mut data, &body, "registering")?;
        resources::register(&state, &auth, &mut replacement).map_err(fail)?;
        jobs::stage(&root, &mut data, &body, "verifying")?;
        if let Err(error) =
            oauth::inherit(&state, &auth, &data.installations[index], &mut replacement)
        {
            let _ = resources::remove(&state, &auth, &mut replacement);
            return Err(fail(error));
        }
        let activation = if replacement.package.required.is_empty() {
            resources::set_enabled(&state, &auth, &mut replacement, true)
        } else {
            resources::configure_generation(
                &state,
                &auth,
                &mut replacement,
                &body.credentials,
                Some(&data.installations[index]),
            )
        };
        if let Err(error) = activation {
            let _ = resources::remove(&state, &auth, &mut replacement);
            return Err(fail(error));
        }
        if let Err(error) = resources::verify(&state, &auth, &replacement).await {
            let _ = resources::remove(&state, &auth, &mut replacement);
            return Err(fail(error));
        }
        replacement.id = id.clone();
        data.transition = Some(Transition {
            installation_id: id,
            replacement: replacement.clone(),
        });
        jobs::stage(&root, &mut data, &body, "activating")?;
        save(&root, &data).map_err(fail)?;
        resources::publish(
            &state,
            &auth,
            &replacement,
            Some(&data.installations[index]),
        )
        .map_err(fail)?;
        data.installations[index] = replacement;
        data.preflights.remove(&body.preflight_id);
        data.transition = None;
    } else {
        let installation = &mut data.installations[index];
        match action.as_str() {
            "enable" => {
                resources::set_enabled(&state, &auth, installation, true).map_err(fail)?;
                check_running(&state, &auth, installation).await?;
            }
            "disable" => {
                resources::set_enabled(&state, &auth, installation, false).map_err(fail)?
            }
            "uninstall" => resources::remove(&state, &auth, installation).map_err(fail)?,
            "configure" => {
                resources::configure(&state, &auth, installation, &body.credentials)
                    .map_err(fail)?;
                check_running(&state, &auth, installation).await?;
            }
            "verify" => {
                if installation.status != "enabled" {
                    return Err(fail("enable the plugin before verifying it"));
                }
                check_running(&state, &auth, installation).await?;
            }
            _ => return Err(fail("unknown plugin lifecycle action")),
        }
    }
    oauth::cleanup_uninstalled(&mut data);
    let result = data.installations[index].public();
    finish(&root, &mut data, &body, &operation, result)
}
async fn check_running(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    installation: &mut Installation,
) -> Result<(), Failure> {
    match resources::verify(state, auth, installation).await {
        Ok(()) => {
            resources::publish(state, auth, installation, None).map_err(fail)?;
            installation.error = None;
        }
        Err(error) => {
            resources::set_enabled(state, auth, installation, false).map_err(fail)?;
            installation.status = "failed".into();
            installation.error = Some(error);
        }
    }
    Ok(())
}
