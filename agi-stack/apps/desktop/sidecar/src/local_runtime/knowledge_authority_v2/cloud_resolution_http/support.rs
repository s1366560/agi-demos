use super::*;
#[derive(Default)]
pub(super) struct Data {
    pub(super) requests: Vec<String>,
    pub(super) receipts: BTreeMap<String, Value>,
    pub(super) conflict: Value,
    pub(super) current: Value,
    pub(super) conflict_reads: usize,
    pub(super) calls: Vec<u8>,
}
pub(super) struct Cloud {
    pub(super) data: Mutex<Data>,
    pub(super) forbid_conflict_get: AtomicBool,
    pub(super) stale_next: AtomicBool,
    pub(super) fail_after_commit: AtomicBool,
    pub(super) auth_status: AtomicU16,
    pub(super) phase: AtomicU8,
    pub(super) entered: Notify,
    pub(super) release: Notify,
}
impl Cloud {
    async fn barrier(&self, phase: u8) {
        self.data.lock().unwrap().calls.push(phase);
        if self.phase.load(Ordering::SeqCst) == phase {
            self.entered.notify_one();
            self.release.notified().await;
        }
    }
}
async fn auth(State(cloud): State<Arc<Cloud>>) -> (StatusCode, Json<Value>) {
    cloud.barrier(1).await;
    (
        StatusCode::from_u16(cloud.auth_status.load(Ordering::SeqCst)).unwrap(),
        Json(super::super::sync_auth_tests::auth_me_fixture()),
    )
}
async fn project(State(cloud): State<Arc<Cloud>>) -> Json<Value> {
    cloud.barrier(2).await;
    Json(json!({"id":"remote-project","tenant_id":"remote-tenant"}))
}
async fn mutation(
    State(cloud): State<Arc<Cloud>>,
    Json(request): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let mut data = cloud.data.lock().unwrap();
    let id = Uuid::new_v4().to_string();
    let mut proposed = request.clone();
    proposed.as_object_mut().unwrap().remove("change_id");
    data.conflict = json!({
        "id":id,
        "memory_id":request["memory_id"],
        "proposed":proposed,
        "current":data.current,
        "observed_current":data.current,
        "resolved_change_id":null
    });
    (
        StatusCode::CONFLICT,
        Json(
            json!({"replayed":false,"receipt":{"status":"conflict","change_id":request["change_id"],"conflict_id":id}}),
        ),
    )
}
async fn conflict(
    State(cloud): State<Arc<Cloud>>,
    Path(id): Path<String>,
) -> (StatusCode, Json<Value>) {
    cloud.barrier(3).await;
    let mut data = cloud.data.lock().unwrap();
    data.conflict_reads += 1;
    if cloud.forbid_conflict_get.load(Ordering::SeqCst) || data.conflict["id"] != id {
        return (StatusCode::NOT_FOUND, Json(json!({})));
    }
    let mut value = data.conflict.clone();
    value["observed_current"] = data.current.clone();
    (StatusCode::OK, Json(value))
}
async fn resolve(
    State(cloud): State<Arc<Cloud>>,
    Path(id): Path<String>,
    body: String,
) -> (StatusCode, Json<Value>) {
    cloud.barrier(4).await;
    let mut data = cloud.data.lock().unwrap();
    data.requests.push(body.clone());
    let request: Value = serde_json::from_str(&body).unwrap();
    let key = request["change_id"].as_str().unwrap().to_owned();
    if let Some(receipt) = data.receipts.get(&key) {
        return (
            StatusCode::OK,
            Json(json!({"replayed":true,"receipt":receipt})),
        );
    }
    if cloud.stale_next.swap(false, Ordering::SeqCst) {
        data.current["revision"] = json!(data.current["revision"].as_u64().unwrap() + 1);
    }
    if request["expected_current_revision"] != data.current["revision"] {
        return (
            StatusCode::CONFLICT,
            Json(json!({"detail":{"code":"knowledge_sync_resolution_stale"}})),
        );
    }
    assert_eq!(data.conflict["id"], id);
    let receipt = if request["decision"] == "keep_current" {
        json!({"status":"resolved","change_id":key,"conflict_id":id,"version":data.current})
    } else {
        let revision = data.current["revision"].as_u64().unwrap() + 1;
        data.current["revision"] = json!(revision);
        data.current["deleted"] = json!(false);
        data.current["content"] = if request["decision"] == "merged" {
            request["content"].clone()
        } else {
            data.conflict["proposed"]["content"].clone()
        };
        json!({"status":"applied","change_id":key,"sequence":revision,"version":data.current})
    };
    data.conflict["resolved_change_id"] = json!(key);
    data.receipts.insert(key, receipt.clone());
    if cloud.fail_after_commit.swap(false, Ordering::SeqCst) {
        return (
            StatusCode::BAD_GATEWAY,
            Json(json!({"error":"response lost"})),
        );
    }
    (
        StatusCode::OK,
        Json(json!({"replayed":false,"receipt":receipt})),
    )
}
pub(super) async fn cloud() -> (Arc<Cloud>, String, tokio::task::JoinHandle<()>) {
    let current = json!({
        "memory_id":"knowledge-test-memory",
        "revision":2,
        "deleted":true,
        "author_id":"remote-actor",
        "created_at_ms":100,
        "extension":{
            "preserve":true
        },
        "content":{
            "title":"Remote",
            "content":"remote tombstone",
            "content_type":"text",
            "tags":[],
            "status":"ENABLED",
            "metadata":{
                "remote":true
            }
        }
    });
    let cloud = Arc::new(Cloud {
        data: Mutex::new(Data {
            current,
            ..Data::default()
        }),
        forbid_conflict_get: AtomicBool::new(false),
        stale_next: AtomicBool::new(false),
        fail_after_commit: AtomicBool::new(false),
        auth_status: AtomicU16::new(200),
        phase: AtomicU8::new(0),
        entered: Notify::new(),
        release: Notify::new(),
    });
    let app = Router::new()
        .route("/api/v1/auth/me", get(auth))
        .route("/api/v1/projects/remote-project", get(project))
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/mutations",
            post(mutation),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/conflicts/:id",
            get(conflict),
        )
        .route(
            "/api/v1/projects/remote-project/knowledge-sync/conflicts/:id/resolve",
            post(resolve),
        )
        .with_state(cloud.clone());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (cloud, base, task)
}
pub(super) fn command(cloud: &Cloud) -> Value {
    json!({
        "local_sequence":1,
        "memory_id":"knowledge-test-memory",
        "conflict_id":cloud.data.lock().unwrap().conflict["id"],
        "guard":{
            "expected_local_revision":1,
            "expected_remote_revision":2,
            "expected_baseline_revision":0,
            "conflict_sequences":[]
        },
        "choice":{
            "decision":"use_proposed"
        }
    })
}
pub(super) async fn edit(operation: &KnowledgeOperationV2, content: &str) {
    let mut memory = operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .unwrap();
    let expected_revision = memory.version;
    memory.content = content.into();
    operation
        .mutate(
            "later-edit",
            MemoryMutation::Update {
                memory,
                expected_revision,
            },
        )
        .await
        .unwrap();
}
pub(super) async fn call(
    state: Arc<LocalRuntimeState>,
    path: &str,
    body: Value,
    key: Option<&str>,
) -> (StatusCode, Value) {
    let mut request = Request::builder()
        .method("POST")
        .uri(format!("/api/v1/knowledge/{path}"))
        .header("content-type", "application/json")
        .header("x-agistack-launch", TOKEN)
        .header("authorization", format!("Bearer {TOKEN}"));
    if let Some(key) = key {
        request = request.header("idempotency-key", key);
    }
    let response = local_router_with_generation_required(state)
        .oneshot(request.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    let status = response.status();
    let bytes = to_bytes(response.into_body(), usize::MAX).await.unwrap();
    (
        status,
        serde_json::from_slice(&bytes).unwrap_or(Value::Null),
    )
}
