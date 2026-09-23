//! Native OAuth authorization. Callback capabilities are single-use and bound to the installation.
use super::super::mcp_supervisor::McpScope;
use super::*;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
static PENDING: std::sync::LazyLock<
    std::sync::Mutex<BTreeMap<String, tokio::sync::oneshot::Sender<()>>>,
> = std::sync::LazyLock::new(|| std::sync::Mutex::new(BTreeMap::new()));
fn cancel(flow: &str) {
    if let Ok(mut pending) = PENDING.lock() {
        if let Some(sender) = pending.remove(flow) {
            let _ = sender.send(());
        }
    }
}
struct Pending(String);
impl Drop for Pending {
    fn drop(&mut self) {
        if let Ok(mut pending) = PENDING.lock() {
            pending.remove(&self.0);
        }
    }
}

#[derive(Clone, Default, Serialize, Deserialize)]
pub(super) struct Service {
    pub name: String,
    pub status: String,
    pub reason: Option<String>,
    #[serde(default)]
    flow: String,
    #[serde(default)]
    user: String,
    #[serde(default)]
    expires_at: Option<i64>,
    #[serde(default)]
    request_key: String,
    #[serde(default)]
    authorization_url: Option<String>,
}
impl Service {
    pub(super) fn public(&self) -> Value {
        json!({"name":self.name,"status":self.status,"reason":self.reason,"expires_at":self.expires_at})
    }
}
pub(super) fn declared(config: &Value) -> Option<Value> {
    config.get("oauth").cloned().or_else(|| {
        config
            .get("auth")
            .filter(|auth| {
                auth["type"]
                    .as_str()
                    .is_some_and(|kind| matches!(kind, "oauth" | "oauth2"))
            })
            .cloned()
    })
}
pub(super) fn supported_transport(config: &Value) -> bool {
    config.get("command").is_none()
        && config.get("url").and_then(Value::as_str).is_some()
        && matches!(
            config["type"].as_str().unwrap_or("http"),
            "http" | "streamable-http"
        )
}
pub(super) fn services(package: &Package) -> Vec<Service> {
    package
        .servers
        .iter()
        .filter(|(_, config)| declared(config).is_some())
        .map(|(name, _)| Service {
            name: name.clone(),
            status: "not_connected".into(),
            ..Service::default()
        })
        .collect()
}
fn scope(auth: &AuthenticatedContext) -> McpScope {
    McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    }
}
fn server(installation: &Installation, name: &str) -> PackageResult<String> {
    installation
        .package
        .servers
        .keys()
        .position(|key| key == name)
        .and_then(|index| installation.server_ids.get(index).cloned())
        .ok_or("oauth_server_missing".into())
}
fn index(data: &Database, id: &str, name: &str) -> PackageResult<(usize, usize)> {
    let i = data
        .installations
        .iter()
        .position(|item| item.id == id && item.status != "uninstalled")
        .ok_or("installation_not_found")?;
    let s = data.installations[i]
        .oauth_services
        .iter()
        .position(|service| service.name == name)
        .ok_or("oauth_service_not_found")?;
    Ok((i, s))
}
#[derive(Deserialize)]
pub(super) struct OAuthRequest {
    #[serde(flatten)]
    scope: Scope,
    idempotency_key: String,
    client_id: Option<String>,
    client_metadata_url: Option<String>,
}
pub(super) async fn status(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path((id, name)): Path<(String, String)>,
    Query(request): Query<Scope>,
) -> Response {
    authorize(&auth, &request, false)?;
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    let (i, s) = index(&data, &id, &name).map_err(fail)?;
    let server_id = server(&data.installations[i], &name).map_err(fail)?;
    let service = &mut data.installations[i].oauth_services[s];
    let pending = service.status == "authorizing"
        && !service.flow.is_empty()
        && service
            .expires_at
            .is_some_and(|expiry| expiry > chrono::Utc::now().timestamp())
        && PENDING
            .lock()
            .is_ok_and(|pending| pending.contains_key(&service.flow));
    if pending {
        return Ok(Json(service.public()));
    }
    if service.status == "authorizing" {
        cancel(&service.flow);
        service.status = "expired".into();
        service.flow.clear();
        service.authorization_url = None;
    }
    let token = state
        .mcp_supervisor
        .oauth_status(&server_id)
        .map_err(fail)?;
    if token["status"] != "not_connected" {
        service.status = token["status"].as_str().unwrap_or("error").into();
        service.expires_at = token["expires_at"].as_i64();
        if service.status == "connected" {
            service.reason = None;
        }
    }
    let result = service.public();
    save(&root, &data).map_err(fail)?;
    Ok(Json(result))
}
pub(super) async fn action(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path((id, name, action)): Path<(String, String, String)>,
    Json(request): Json<OAuthRequest>,
) -> Response {
    authorize(&auth, &request.scope, true)?;
    if request.idempotency_key.is_empty() || request.idempotency_key.len() > 128 {
        return Err(fail("idempotency_key_required"));
    }
    let _guard = MUTATION.lock().await;
    let root = auth_root(&state, &auth)?;
    let mut data = load(&root).map_err(fail)?;
    let (i, s) = index(&data, &id, &name).map_err(fail)?;
    if action == "start" {
        if !supported_transport(&data.installations[i].package.servers[&name]) {
            return Err(fail("oauth_requires_streamable_http"));
        }
    }

    let receipt_key = format!(
        "{}:{id}:{name}:{action}:{}",
        auth.user.user_id, request.idempotency_key
    );
    let fingerprint=format!("{:x}",Sha256::digest(json!({"client_id":request.client_id,"client_metadata_url":request.client_metadata_url}).to_string().as_bytes()));
    if let Some((prior, value)) = data.oauth_receipts.get(&receipt_key) {
        if prior != &fingerprint {
            return Err(fail("idempotency_conflict"));
        }
        return Ok(Json(value.clone()));
    }
    let server_id = server(&data.installations[i], &name).map_err(fail)?;
    if action == "cancel" || action == "disconnect" {
        let mut error = None;
        if action == "disconnect" {
            error = state
                .mcp_supervisor
                .oauth_disconnect(&server_id)
                .await
                .err()
                .map(|_| "oauth_revocation_failed".to_owned());
            resources::set_enabled(&state, &auth, &mut data.installations[i], false)
                .map_err(fail)?;
            data.installations[i].status = "needs_configuration".into();
        }
        let service = &mut data.installations[i].oauth_services[s];
        cancel(&service.flow);
        service.flow.clear();
        service.authorization_url = None;
        service.status = "not_connected".into();
        service.reason = error;
        let result = service.public();
        data.oauth_receipts
            .insert(receipt_key, (fingerprint, result.clone()));
        save(&root, &data).map_err(fail)?;
        return Ok(Json(result));
    }
    if action != "start" {
        return Err(fail("oauth_action_invalid"));
    }
    let existing = &data.installations[i].oauth_services[s];
    if existing.status == "authorizing"
        && existing
            .expires_at
            .is_some_and(|expiry| expiry > chrono::Utc::now().timestamp())
    {
        if existing.request_key == request.idempotency_key && existing.user == auth.user.user_id {
            let mut value = existing.public();
            value["authorization_url"] = json!(existing.authorization_url);
            return Ok(Json(value));
        }
        return Err(fail("oauth_authorization_already_pending"));
    }
    let config = &data.installations[i].package.servers[&name];
    let resource = config["url"]
        .as_str()
        .ok_or_else(|| fail("oauth_http_required"))?
        .to_owned();
    let mut declared = declared(config).ok_or_else(|| fail("oauth_service_not_found"))?;
    if let Some(client) = request.client_id {
        declared["client_id"] = json!(client);
    }
    if let Some(url) = request.client_metadata_url {
        declared["client_metadata_url"] = json!(url);
    }
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|_| fail("oauth_callback_unavailable"))?;
    let redirect = format!(
        "http://127.0.0.1:{}/callback",
        listener.local_addr().map_err(fail)?.port()
    );
    let setup = async {
        let metadata = super::oauth_http::discover(&resource, &declared).await?;
        let client = super::oauth_http::registration(&metadata, &declared, &redirect).await?;
        Ok::<_, String>((metadata, client))
    }
    .await;
    let (metadata, client) = match setup {
        Ok(value) => value,
        Err(reason) => {
            let service = &mut data.installations[i].oauth_services[s];
            service.status = "needs_configuration".into();
            service.reason = Some(reason);
            let result = service.public();
            data.oauth_receipts
                .insert(receipt_key, (fingerprint, result.clone()));
            save(&root, &data).map_err(fail)?;
            return Ok(Json(result));
        }
    };
    let random = || -> PackageResult<String> {
        let mut bytes = [0u8; 32];
        getrandom::getrandom(&mut bytes).map_err(|_| "oauth_random_unavailable")?;
        Ok(URL_SAFE_NO_PAD.encode(bytes))
    };
    let csrf = random().map_err(fail)?;
    let verifier = zeroize::Zeroizing::new(random().map_err(fail)?);
    let flow = format!("{:x}", Sha256::digest(csrf.as_bytes()));
    let mut url = url::Url::parse(
        metadata["authorization_endpoint"]
            .as_str()
            .unwrap_or_default(),
    )
    .map_err(fail)?;
    url.query_pairs_mut().extend_pairs([
        ("response_type", "code"),
        ("client_id", &client),
        ("redirect_uri", &redirect),
        ("state", &csrf),
        ("code_challenge_method", "S256"),
        (
            "code_challenge",
            &URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes())),
        ),
        ("resource", &resource),
        ("scope", metadata["scope"].as_str().unwrap_or_default()),
    ]);
    let expires = chrono::Utc::now().timestamp() + 600;
    data.installations[i].oauth_services[s] = Service {
        name: name.clone(),
        status: "authorizing".into(),
        flow: flow.clone(),
        user: auth.user.user_id.clone(),
        expires_at: Some(expires),
        request_key: request.idempotency_key,
        authorization_url: Some(url.to_string()),
        reason: None,
    };
    let version = data.installations[i].version.clone();
    let mut result = data.installations[i].oauth_services[s].public();
    result["authorization_url"] = json!(url.as_str());
    data.oauth_receipts
        .insert(receipt_key, (fingerprint, result.clone()));
    save(&root, &data).map_err(fail)?;
    let (sender, cancelled) = tokio::sync::oneshot::channel();
    PENDING
        .lock()
        .map_err(|_| fail("oauth_pending_unavailable"))?
        .insert(flow.clone(), sender);
    tokio::spawn(async move {
        callback(
            listener,
            Flow {
                state,
                auth,
                id,
                name,
                version,
                server_id,
                flow,
                csrf,
                verifier,
                redirect,
                resource,
                client,
                metadata,
            },
            cancelled,
        )
        .await;
    });
    Ok(Json(result))
}
struct Flow {
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
    id: String,
    name: String,
    version: String,
    server_id: String,
    flow: String,
    csrf: String,
    verifier: zeroize::Zeroizing<String>,
    redirect: String,
    resource: String,
    client: String,
    metadata: Value,
}
async fn callback(
    listener: tokio::net::TcpListener,
    flow: Flow,
    mut cancelled: tokio::sync::oneshot::Receiver<()>,
) {
    let _pending = Pending(flow.flow.clone());
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(600);
    loop {
        let accepted = tokio::select! {value=tokio::time::timeout_at(deadline,listener.accept())=>value,_=&mut cancelled=>return};
        let Ok(Ok((mut socket, peer))) = accepted else {
            return;
        };
        if !peer.ip().is_loopback() {
            continue;
        }
        let mut bytes = [0u8; 8192];
        let Ok(Ok(size)) =
            tokio::time::timeout(std::time::Duration::from_secs(5), socket.read(&mut bytes)).await
        else {
            continue;
        };
        let text = String::from_utf8_lossy(&bytes[..size]);
        let Some(path) = text
            .lines()
            .next()
            .and_then(|line| line.strip_prefix("GET "))
            .and_then(|line| line.split_once(' ').map(|(path, _)| path))
        else {
            continue;
        };
        let Ok(url) = url::Url::parse(&format!("http://127.0.0.1{path}")) else {
            continue;
        };
        let query = url.query_pairs().collect::<BTreeMap<_, _>>();
        if url.path() != "/callback"
            || query.get("state").map(|value| value.as_ref()) != Some(flow.csrf.as_str())
        {
            let _ = socket
                .write_all(
                    b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .await;
            continue;
        }
        let code = query.get("code").map(|value| value.to_string());
        let outcome = complete(&flow, code).await;
        let message = if outcome.is_ok() {
            "Authorization complete. Return to AGIStack."
        } else {
            "Authorization failed. Return to AGIStack and retry."
        };
        let response=format!("HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nCache-Control: no-store\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{message}",message.len());
        let _ = socket.write_all(response.as_bytes()).await;
        return;
    }
}
async fn complete(flow: &Flow, code: Option<String>) -> PackageResult<()> {
    let _guard = MUTATION.lock().await;
    let root = root(
        &flow.state,
        &flow.auth.workspace.tenant_id,
        &flow.auth.workspace.project_id,
    )?;
    let mut data = load(&root)?;
    let (i, s) = index(&data, &flow.id, &flow.name)?;
    let service = &mut data.installations[i].oauth_services[s];
    if service.flow != flow.flow
        || service.user != flow.auth.user.user_id
        || service.status != "authorizing"
        || service
            .expires_at
            .is_none_or(|expiry| expiry <= chrono::Utc::now().timestamp())
    {
        return Err("oauth_state_invalid".into());
    }
    service.flow.clear();
    service.authorization_url = None;
    service.status = "error".into();
    service.reason = Some("oauth_callback_interrupted".into());
    save(&root, &data)?;
    let outcome = async {
        if data.installations[i].version != flow.version
            || server(&data.installations[i], &flow.name)? != flow.server_id
        {
            return Err("oauth_installation_changed".into());
        }
        let tokens = super::oauth_http::post(
            flow.metadata["token_endpoint"]
                .as_str()
                .ok_or("oauth_token_endpoint_missing")?,
            &[
                ("grant_type".into(), "authorization_code".into()),
                ("code".into(), code.ok_or("oauth_authorization_denied")?),
                ("redirect_uri".into(), flow.redirect.clone()),
                ("client_id".into(), flow.client.clone()),
                ("code_verifier".into(), flow.verifier.to_string()),
                ("resource".into(), flow.resource.clone()),
            ],
        )
        .await?;
        flow.state
            .mcp_supervisor
            .oauth_connect(
                &scope(&flow.auth),
                &flow.server_id,
                &flow.metadata,
                &flow.client,
                &flow.resource,
                &tokens,
            )
            .map_err(|e| e.to_string())?;
        let status = flow
            .state
            .mcp_supervisor
            .oauth_status(&flow.server_id)
            .map_err(|e| e.to_string())?;
        data.installations[i].oauth_services[s].status = "connected".into();
        data.installations[i].oauth_services[s].expires_at = status["expires_at"].as_i64();
        data.installations[i].oauth_services[s].reason = None;
        if data.installations[i]
            .oauth_services
            .iter()
            .all(|service| service.status == "connected")
            && resources::missing_credentials(
                &flow.state,
                &flow.auth,
                &data.installations[i].package,
                Some(&data.installations[i]),
            )?
            .is_empty()
        {
            resources::set_enabled(&flow.state, &flow.auth, &mut data.installations[i], true)?;
            resources::verify(&flow.state, &flow.auth, &data.installations[i]).await?;
            resources::publish(&flow.state, &flow.auth, &data.installations[i], None)?;
        }
        Ok::<_, String>(())
    }
    .await;
    if let Err(reason) = &outcome {
        let _ = resources::set_enabled(&flow.state, &flow.auth, &mut data.installations[i], false);
        data.installations[i].status = "failed".into();
        data.installations[i].error = Some(reason.clone());
        data.installations[i].oauth_services[s].status = "error".into();
        data.installations[i].oauth_services[s].reason = Some(reason.clone());
    }
    save(&root, &data)?;
    outcome
}
pub(super) fn inherit(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    old: &Installation,
    new: &mut Installation,
) -> PackageResult<()> {
    for index in 0..new.oauth_services.len() {
        let name = new.oauth_services[index].name.clone();
        let old_config = old
            .package
            .servers
            .get(&name)
            .ok_or("oauth_authorization_required")?;
        let new_config = &new.package.servers[&name];
        if old_config["url"] != new_config["url"] || declared(old_config) != declared(new_config) {
            return Err("oauth_authorization_required".into());
        }
        if !state
            .mcp_supervisor
            .oauth_inherit(&scope(auth), &server(old, &name)?, &server(new, &name)?)
            .map_err(|e| e.to_string())?
        {
            return Err("oauth_authorization_required".into());
        }
        new.oauth_services[index].status = "connected".into();
    }
    Ok(())
}
/// Discard only receipts whose installation segment belongs to a scoped tombstone.
/// Validate installation liveness before replaying receipts, including legacy records.
pub(super) fn cleanup_uninstalled(data: &mut Database) {
    let mut removed = std::collections::BTreeSet::new();
    for installation in &mut data.installations {
        if installation.status != "uninstalled" {
            continue;
        }
        removed.insert(installation.id.clone());
        for service in &installation.oauth_services {
            cancel(&service.flow);
        }
        installation.oauth_services.clear();
    }
    data.oauth_receipts.retain(|key, _| {
        !key.splitn(3, ':')
            .nth(1)
            .is_some_and(|id| removed.contains(id))
    });
}

pub(super) fn recover_services(installation: &mut Installation) {
    for service in &mut installation.oauth_services {
        recover_service(service);
    }
}
fn recover_service(service: &mut Service) {
    if service.status == "authorizing"
        && !PENDING
            .lock()
            .is_ok_and(|pending| pending.contains_key(&service.flow))
    {
        service.status = "expired".into();
        service.reason = Some("oauth_authorization_interrupted".into());
        service.flow.clear();
        service.authorization_url = None;
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn interrupted_authorization_does_not_keep_a_dead_callback_pending() {
        let mut service = Service {
            name: "mcp".into(),
            status: "authorizing".into(),
            flow: "dead-process-flow".into(),
            authorization_url: Some("https://example.org/authorize".into()),
            ..Service::default()
        };
        recover_service(&mut service);
        assert_eq!(service.status, "expired");
        assert!(service.authorization_url.is_none());
        let (sender, _receiver) = tokio::sync::oneshot::channel();
        PENDING
            .lock()
            .unwrap()
            .insert("live-process-flow".into(), sender);
        service.flow = "live-process-flow".into();
        service.status = "authorizing".into();
        recover_service(&mut service);
        assert_eq!(service.status, "authorizing");
        cancel(&service.flow);
    }
}
