use super::*;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, Method},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use std::collections::{BTreeMap, HashMap};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, AtomicU8, Ordering},
    Mutex,
};
use tokio::sync::Notify;

#[derive(Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub(super) enum Phase {
    None,
    Auth,
    Tenants,
    Projects,
    Project,
    Enrollment,
    Enroll,
    Data,
}

pub(super) struct Cloud {
    pub(super) enabled: AtomicBool,
    pub(super) can_enroll: AtomicBool,
    pub(super) generation: AtomicU64,
    pub(super) pause: AtomicU8,
    pub(super) entered: Notify,
    pub(super) release: Notify,
    pub(super) calls: Mutex<Vec<Phase>>,
    pub(super) catalog: Mutex<Value>,
    pub(super) overrides: Mutex<BTreeMap<(String, u64), Value>>,
    pub(super) enrollment_override: Mutex<Option<Value>>,
    pub(super) fail_enroll_response: AtomicBool,
    pub(super) posts: AtomicU64,
}
impl Cloud {
    fn new() -> Self {
        Self {
            enabled: AtomicBool::new(false),
            can_enroll: AtomicBool::new(true),
            generation: AtomicU64::new(1),
            pause: AtomicU8::new(0),
            entered: Notify::new(),
            release: Notify::new(),
            calls: Mutex::new(vec![]),
            catalog: Mutex::new(
                serde_json::from_str(include_str!("../sync_catalog_fixture.json")).unwrap(),
            ),
            overrides: Mutex::new(BTreeMap::new()),
            enrollment_override: Mutex::new(None),
            fail_enroll_response: AtomicBool::new(false),
            posts: AtomicU64::new(0),
        }
    }
    async fn barrier(&self, phase: Phase, headers: &HeaderMap) {
        assert_eq!(headers["authorization"], "Bearer cloud-test-credential");
        self.calls.lock().unwrap().push(phase);
        if self.pause.load(Ordering::SeqCst) == phase as u8 {
            self.entered.notify_one();
            self.release.notified().await;
        }
    }
    pub(super) fn generation(&self) -> Value {
        let mut generation = super::super::sync_cloud_fixture::generation();
        generation["descriptor"]["generation"] = json!(self.generation.load(Ordering::SeqCst));
        generation
    }
    fn conditional(&self, headers: &HeaderMap, required: bool) -> bool {
        let values: Vec<_> = headers
            .get_all(super::super::trusted_cloud_connection::GENERATION_HEADER)
            .iter()
            .collect();
        if values.is_empty() {
            return !required;
        }
        values.len() == 1
            && serde_json::from_slice::<Value>(values[0].as_bytes())
                .ok()
                .as_ref()
                == Some(&self.generation())
    }
    fn enrollment(&self) -> Value {
        if let Some(value) = self.enrollment_override.lock().unwrap().clone() {
            return value;
        }
        let mut value = super::super::sync_cloud_fixture::enrollment_value();
        value["generation"] = self.generation();
        value["enabled"] = json!(self.enabled.load(Ordering::SeqCst));
        value["can_enroll"] = json!(self.can_enroll.load(Ordering::SeqCst));
        value
    }
}
async fn auth(State(cloud): State<Arc<Cloud>>, headers: HeaderMap) -> Json<Value> {
    cloud.barrier(Phase::Auth, &headers).await;
    Json(super::super::sync_auth_tests::auth_me_fixture())
}
async fn tenants(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Json<Value> {
    cloud.barrier(Phase::Tenants, &headers).await;
    Json(page(&cloud, "tenants", query))
}
async fn projects(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Json<Value> {
    cloud.barrier(Phase::Projects, &headers).await;
    assert_eq!(query["tenant_id"], "remote-tenant");
    Json(page(&cloud, "projects", query))
}
fn page(cloud: &Cloud, collection: &str, query: HashMap<String, String>) -> Value {
    let page: u64 = query["page"].parse().unwrap();
    assert_eq!(query["page_size"], "100");
    if let Some(value) = cloud
        .overrides
        .lock()
        .unwrap()
        .get(&(collection.into(), page))
    {
        return value.clone();
    }
    let catalog = cloud.catalog.lock().unwrap();
    let rows = catalog[collection][collection].as_array().unwrap();
    let offset = ((page - 1) * 100) as usize;
    json!({(collection): rows.iter().skip(offset).take(100).cloned().collect::<Vec<_>>(),"total":rows.len(),"page":page,"page_size":100})
}
async fn project(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    Query(query): Query<HashMap<String, String>>,
) -> Json<Value> {
    cloud.barrier(Phase::Project, &headers).await;
    assert_eq!(query["tenant_id"], "remote-tenant");
    Json(cloud.catalog.lock().unwrap()["projects"]["projects"][0].clone())
}
async fn enrollment(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    method: Method,
) -> Response {
    let write = method == Method::POST;
    cloud
        .barrier(
            if write {
                Phase::Enroll
            } else {
                Phase::Enrollment
            },
            &headers,
        )
        .await;
    if !cloud.conditional(&headers, write) {
        return StatusCode::PRECONDITION_FAILED.into_response();
    }
    if write {
        cloud.posts.fetch_add(1, Ordering::SeqCst);
        if !cloud.can_enroll.load(Ordering::SeqCst) {
            return StatusCode::FORBIDDEN.into_response();
        }
        cloud.enabled.store(true, Ordering::SeqCst);
        if cloud.fail_enroll_response.swap(false, Ordering::SeqCst) {
            return StatusCode::BAD_GATEWAY.into_response();
        }
    }
    Json(cloud.enrollment()).into_response()
}
async fn mutate(
    State(cloud): State<Arc<Cloud>>,
    headers: HeaderMap,
    Json(request): Json<Value>,
) -> Response {
    cloud.barrier(Phase::Data, &headers).await;
    if !cloud.conditional(&headers, true) {
        return StatusCode::PRECONDITION_FAILED.into_response();
    }
    cloud.posts.fetch_add(1, Ordering::SeqCst);
    Json(json!({"receipt":{"status":"applied","change_id":request["change_id"],"sequence":1,"version":{"memory_id":request["memory_id"],"revision":1,"deleted":false,"author_id":"remote-actor","created_at_ms":100,"content":request["content"]}},"replayed":false})).into_response()
}

pub(super) struct Fixture {
    pub(super) directory: TestDirectory,
    pub(super) state: Arc<LocalRuntimeState>,
    pub(super) scope: KnowledgeOperationScopeV2,
    pub(super) broker: TrustedSessionBroker,
    pub(super) cloud: Arc<Cloud>,
    pub(super) base: String,
    server: tokio::task::JoinHandle<()>,
}
impl Fixture {
    pub(super) async fn new() -> Self {
        let directory = TestDirectory::new();
        let state = test_state(TOKEN);
        publish(&state, &directory, 1, true).await;
        let authenticated_context = authenticated(&state);
        let lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap();
        let scope = operation_scope(&authenticated_context, &lease);
        let cloud = Arc::new(Cloud::new());
        let app = Router::new()
            .route("/api/v1/auth/me", get(auth))
            .route("/api/v1/tenants/", get(tenants))
            .route("/api/v1/projects/", get(projects))
            .route("/api/v1/projects/remote-project", get(project))
            .route(
                "/api/v1/projects/remote-project/knowledge-sync/enrollment",
                get(enrollment).post(enrollment),
            )
            .route(
                "/api/v1/projects/remote-project/knowledge-sync/mutations",
                post(mutate),
            )
            .with_state(cloud.clone());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let base = format!("http://{}", listener.local_addr().unwrap());
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let broker =
            super::super::sync_cloud_fixture::install_unbound(&state, &directory, base.clone());
        Self {
            directory,
            state,
            scope,
            broker,
            cloud,
            base,
            server,
        }
    }
    pub(super) async fn request(&self, path: &str, body: Value) -> (StatusCode, Value) {
        rpc(self.state.clone(), path, body).await
    }
    pub(super) async fn observation(&self) -> String {
        let (status, result) = self
            .request("sync-connection", json!({"scope":self.scope}))
            .await;
        assert_eq!(status, StatusCode::OK, "{result}");
        result["result"]["connection"]["connection_revision"]
            .as_str()
            .unwrap()
            .into()
    }
    pub(super) fn target(&self, revision: &str) -> Value {
        json!({"scope":self.scope,"expected_connection_revision":revision,"tenant_id":"remote-tenant","project_id":"remote-project","expected_generation":self.cloud.generation()})
    }
    pub(super) fn operation(&self) -> KnowledgeOperationV2 {
        let auth = authenticated(&self.state);
        let lease = Arc::new(
            self.state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        );
        KnowledgeOperationV2::admit(lease, &auth, &self.scope).unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.server.abort();
    }
}
