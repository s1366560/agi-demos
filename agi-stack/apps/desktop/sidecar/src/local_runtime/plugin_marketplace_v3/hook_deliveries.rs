//! Project-owned post-tool notifications survive failed delivery or a sidecar restart.
use super::*;
use crate::local_runtime::plugin_marketplace_v3::hooks::Hooks;
use std::path::Path as FsPath;

#[derive(Clone, Deserialize, Serialize)]
pub(super) struct Delivery {
    pub(super) id: String,
    pub(super) invocation_id: String,
    installation_id: String,
    version: String,
    snapshot: PathBuf,
    hook_index: usize,
    attempts: u32,
    #[serde(default)]
    claim: Option<String>,
    claimed_until_ms: i64,
}

impl Delivery {
    pub(super) fn public(&self) -> Value {
        json!({
            "id":self.id, "invocation_id":self.invocation_id,
            "installation_id":self.installation_id, "version":self.version,
            "attempts":self.attempts,
            "status": if self.claimed_until_ms > chrono::Utc::now().timestamp_millis() {
                "delivering"
            } else { "pending" }
        })
    }

    fn matches(&self, package: &Package) -> bool {
        self.version == package.descriptor.version && self.snapshot == package.root
    }
}

pub(super) async fn enqueue(
    root: &FsPath,
    packages: &[(String, Package)],
) -> PackageResult<Vec<String>> {
    let invocation_id = uuid::Uuid::new_v4().to_string();
    let _guard = MUTATION.lock().await;
    let mut data = load(root)?;
    let mut ids = Vec::new();
    for (installation_id, package) in packages {
        for (hook_index, _) in package
            .hooks
            .get("after_tool_execute")
            .into_iter()
            .flatten()
            .enumerate()
        {
            let id = uuid::Uuid::new_v4().to_string();
            data.hook_deliveries.insert(
                id.clone(),
                Delivery {
                    id: id.clone(),
                    invocation_id: invocation_id.clone(),
                    installation_id: installation_id.clone(),
                    version: package.descriptor.version.clone(),
                    snapshot: package.root.clone(),
                    hook_index,
                    attempts: 0,
                    claim: None,
                    claimed_until_ms: 0,
                },
            );
            ids.push(id);
        }
    }
    save(root, &data)?;
    Ok(ids)
}

pub(super) async fn deliver(root: &FsPath, id: &str, hooks: &Hooks) -> PackageResult<()> {
    let claim = uuid::Uuid::new_v4().to_string();
    let (delivery, package, hook) = {
        let _guard = MUTATION.lock().await;
        let mut data = load(root)?;
        let delivery = data
            .hook_deliveries
            .get(id)
            .ok_or("unknown hook delivery")?
            .clone();
        let now = chrono::Utc::now().timestamp_millis();
        if delivery.claimed_until_ms > now {
            return Err("hook delivery already claimed".into());
        }
        // Never replay a command from an updated, disabled or removed installation.
        let installed = data.installations.iter().find(|i| {
            i.id == delivery.installation_id
                && i.status == "enabled"
                && delivery.matches(&i.package)
        });
        if installed.is_none() {
            data.hook_deliveries.remove(id);
            save(root, &data)?;
            return Err("hook installation changed".into());
        }
        let package = hooks
            .packages
            .iter()
            .find(|(installation_id, p)| {
                *installation_id == delivery.installation_id && delivery.matches(p)
            })
            .map(|(_, p)| p)
            .ok_or("hook installation unavailable")?;
        let hook = package
            .hooks
            .get("after_tool_execute")
            .and_then(|hooks| hooks.get(delivery.hook_index))
            .ok_or("hook declaration unavailable")?;
        let mut delivery = delivery;
        delivery.claim = Some(claim.clone());
        delivery.claimed_until_ms = now + (hook.timeout_seconds as i64 + 30) * 1000;
        delivery.attempts = delivery.attempts.saturating_add(1);
        data.hook_deliveries.insert(id.to_owned(), delivery.clone());
        save(root, &data)?;
        (delivery, package, hook)
    };

    let result = hooks
        .run_one(
            &delivery.installation_id,
            package,
            hook,
            "after_tool_execute",
            Some(&delivery),
        )
        .await;
    let _guard = MUTATION.lock().await;
    let mut data = load(root)?;
    if let Some(item) = data.hook_deliveries.get_mut(id) {
        if item.claim.as_deref() == Some(&claim) {
            if result.is_ok() {
                data.hook_deliveries.remove(id);
            } else {
                item.claim = None;
                item.claimed_until_ms = 0;
            }
            save(root, &data)?;
        }
    }
    result.map_err(|e| e.to_string())
}

pub(super) async fn list(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, true)?;
    let data = load(&auth_root(&state, &auth)?).map_err(fail)?;
    Ok(Json(
        json!({"items":data.hook_deliveries.values().map(Delivery::public).collect::<Vec<_>>()}),
    ))
}

pub(super) async fn retry(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(id): Path<String>,
    Json(scope): Json<Scope>,
) -> Response {
    authorize(&auth, &scope, true)?;
    let root = auth_root(&state, &auth)?;
    let hooks = Hooks::capture(
        &state,
        &auth.workspace.tenant_id,
        &auth.workspace.project_id,
    )
    .map_err(fail)?;
    // Keep the active process and snapshot lease if the HTTP waiter disconnects.
    let delivery_id = id.clone();
    tokio::spawn(async move { deliver(&root, &delivery_id, &hooks).await })
        .await
        .map_err(|_| fail("hook delivery interrupted"))?
        .map_err(fail)?;
    Ok(Json(json!({"id":id, "status":"delivered"})))
}
