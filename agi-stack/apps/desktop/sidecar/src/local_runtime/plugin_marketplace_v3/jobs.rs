//! Durable jobs continue when their HTTP waiter disconnects.
use super::*;
#[derive(Clone, Deserialize, Serialize)]
pub(super) struct Job {
    id: String,
    operation: String,
    status: String,
    stage: String,
    request_hash: String,
    created_at: String,
    updated_at: String,
    error: Option<String>,
    result: Option<Value>,
}
impl Job {
    fn public(&self) -> Value {
        json!({"id":self.id,"operation":self.operation,"status":self.status,"stage":self.stage,"created_at":self.created_at,"updated_at":self.updated_at,"error":self.error,"result":self.result})
    }
}
pub(super) async fn start_install(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<Request>,
) -> Response {
    dispatch(state, auth, body, None).await
}
pub(super) async fn start_lifecycle(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(target): Path<(String, String)>,
    Json(body): Json<Request>,
) -> Response {
    dispatch(state, auth, body, Some(target)).await
}
async fn dispatch(
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
    mut body: Request,
    target: Option<(String, String)>,
) -> Response {
    authorize(&auth, &body.scope, true)?;
    if body.idempotency_key.is_empty() || body.idempotency_key.len() > 128 {
        return Err(fail("idempotency key is required (maximum 128 characters)"));
    }
    let root = auth_root(&state, &auth)?;
    let operation = target
        .as_ref()
        .map(|(id, action)| format!("{id}:{action}"))
        .unwrap_or_else(|| "install".into());
    let hash = request_hash(&body, &operation);
    let id = uuid::Uuid::new_v5(
        &uuid::Uuid::NAMESPACE_URL,
        format!(
            "{}:{}:{}:{}",
            auth.workspace.tenant_id, auth.workspace.project_id, operation, body.idempotency_key
        )
        .as_bytes(),
    )
    .to_string();
    {
        let _guard = MUTATION.lock().await;
        let mut data = load(&root).map_err(fail)?;
        data.scope = Some(StoredScope {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
        });
        if let Some(job) = data.jobs.get(&id) {
            if job.request_hash != hash {
                return Err(fail("idempotency conflict"));
            }
            if let Some(result) = &job.result {
                return Ok(Json(result.clone()));
            }
            if job.status == "failed" {
                return Err(fail(
                    job.error.as_deref().unwrap_or("plugin operation failed"),
                ));
            }
            return Ok(Json(
                json!({"job_id":id,"status":"running","stage":job.stage}),
            ));
        }
        let now = chrono::Utc::now().to_rfc3339();
        data.jobs.insert(
            id.clone(),
            Job {
                id: id.clone(),
                operation: operation.clone(),
                status: "running".into(),
                stage: "validating".into(),
                request_hash: hash,
                created_at: now.clone(),
                updated_at: now,
                error: None,
                result: None,
            },
        );
        save(&root, &data).map_err(fail)?;
    }
    body.job_id = Some(id.clone());
    // Dropping this waiter does not abort the spawned owner of the operation.
    tokio::spawn(async move {
        let outcome = match target {
            Some(target) => {
                lifecycle(
                    State(state.clone()),
                    Extension(auth),
                    Path(target),
                    Json(body),
                )
                .await
            }
            None => install(State(state.clone()), Extension(auth), Json(body)).await,
        };
        let _guard = MUTATION.lock().await;
        let mut data = load(&root).map_err(fail)?;
        let job = data
            .jobs
            .get_mut(&id)
            .ok_or_else(|| fail("plugin task disappeared"))?;
        job.updated_at = chrono::Utc::now().to_rfc3339();
        let result = match outcome {
            Ok(Json(mut value)) => {
                value["job_id"] = json!(id);
                job.status = if value["status"] == "failed" {
                    "failed"
                } else {
                    "succeeded"
                }
                .into();
                job.stage = "complete".into();
                job.error = value
                    .get("error")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
                job.result = Some(value.clone());
                Ok(Json(value))
            }
            Err(error) => {
                job.status = "failed".into();
                job.stage = "failed".into();
                job.error = error
                    .1
                     .0
                    .get("detail")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
                Err(error)
            }
        };
        save(&root, &data).map_err(fail)?;
        result
    })
    .await
    .map_err(|_| fail("plugin task interrupted; inspect its saved job status"))?
}
pub(super) fn stage(
    root: &std::path::Path,
    data: &mut Database,
    request: &Request,
    stage: &str,
) -> Result<(), Failure> {
    if let Some(id) = &request.job_id {
        if let Some(job) = data.jobs.get_mut(id) {
            job.stage = stage.into();
            job.updated_at = chrono::Utc::now().to_rfc3339();
            save(root, data).map_err(fail)?;
        }
    }
    Ok(())
}
pub(super) async fn get_job(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(id): Path<String>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, false)?;
    let data = load(&auth_root(&state, &auth)?).map_err(fail)?;
    let job = data.jobs.get(&id).ok_or_else(|| {
        (
            StatusCode::NOT_FOUND,
            Json(json!({"detail":"plugin job not found"})),
        )
    })?;
    Ok(Json(job.public()))
}
pub(super) async fn list_jobs(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Query(scope): Query<Scope>,
) -> Response {
    authorize(&auth, &scope, false)?;
    Ok(Json(
        json!({"items":load(&auth_root(&state,&auth)?).map_err(fail)?.jobs.values().map(Job::public).collect::<Vec<_>>()}),
    ))
}
pub(super) fn interrupt_running(data: &mut Database) {
    for job in data.jobs.values_mut().filter(|job| job.status == "running") {
        job.status = "failed".into();
        job.stage = "interrupted".into();
        job.error=Some("application stopped before the operation completed; inspect installation and retry with a new key".into());
        job.updated_at = chrono::Utc::now().to_rfc3339();
    }
}
