//! Schema view over a strict mock cloud. Exact receipt bytes, scope, generation
//! and local-fence behavior are exercised end to end; no admission is opened.
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

use super::*;
use crate::application_vault::ApplicationCredentialVault;
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
    TrustedSessionRuntimeMode,
};
use agistack_core::project_schema::cloud_rpc::{
    CloudSchemaHistoryQuery, CloudSchemaReceipt, CloudSchemaReceiptQuery, CloudSchemaReplaceRequest,
};
use agistack_core::project_schema::ProjectSchemaDocument;
use axum::{
    extract::{Request, State},
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};

const SCHEMA: &str = "00000000-0000-4000-8000-000000000001";
const MEMBER: &str = "00000000-0000-4000-8000-000000000002";
const SECOND: &str = "00000000-0000-4000-8000-000000000003";
const CHANGE: &str = "00000000-0000-4000-8000-999999999999";
const NEXT_CHANGE: &str = "00000000-0000-4000-8000-999999999998";

fn generation_value(number: u64) -> Value {
    json!({"contract_version":"1.0.0","descriptor":{"profile_id":"cloud-sync-fixture","generation":number,"digest":"ab".repeat(32)}})
}

fn document(revision: u32, members: Value) -> Value {
    json!({"format_version":1,"tenant_id":"remote-tenant","project_id":"remote-project",
        "schema_id":SCHEMA,"revision":revision,"deleted":false,
        "entity_types":members,"edge_types":[],"mappings":[],"tombstones":[]})
}

fn member(id: &str, name: &str) -> Value {
    json!({"id":id,"name":name,"description":"","schema":{},"status":"ENABLED","source":"user"})
}

fn receipt_json(document: &Value, change: &str) -> String {
    format!("{{ \"schema_id\" : \"{SCHEMA}\", \"revision\" : {}, \"sequence\" : {}, \"change_id\" : \"{change}\", \"document\" : {} }}",
        document["revision"], document["revision"], document)
}

#[derive(Default)]
struct Cloud {
    receipts: Mutex<Vec<String>>,
    bodies: Mutex<Vec<String>>,
    auth_calls: AtomicUsize,
    generation: Mutex<u64>,
    wrong_scope: AtomicBool,
}

impl Cloud {
    fn current(&self) -> (Option<Value>, u64) {
        let receipts = self.receipts.lock().unwrap();
        let document = receipts
            .last()
            .map(|raw| serde_json::from_str::<Value>(raw).unwrap()["document"].clone());
        (document, *self.generation.lock().unwrap())
    }
}

async fn user(State(cloud): State<Arc<Cloud>>) -> Json<Value> {
    cloud.auth_calls.fetch_add(1, Ordering::SeqCst);
    Json(super::sync_auth_tests::auth_me_fixture())
}

async fn project() -> Json<Value> {
    Json(json!({"id":"remote-project","tenant_id":"remote-tenant"}))
}

async fn read(State(cloud): State<Arc<Cloud>>, body: String) -> Json<Value> {
    assert_eq!(body, "{}");
    let (mut document, generation) = cloud.current();
    if cloud.wrong_scope.load(Ordering::SeqCst) {
        if let Some(document) = document.as_mut() {
            document["tenant_id"] = json!("other-tenant");
        }
    }
    Json(json!({"document":document,"generation":generation_value(generation)}))
}

async fn history(State(cloud): State<Arc<Cloud>>, body: String) -> Response {
    cloud.bodies.lock().unwrap().push(body.clone());
    let query: Value = serde_json::from_str(&body).unwrap();
    let after = query["after_revision"].as_u64().unwrap() as usize;
    let limit = query["limit"].as_u64().unwrap() as usize;
    let receipts = cloud.receipts.lock().unwrap();
    let upper = receipts.len();
    let page: Vec<String> = receipts.iter().skip(after).take(limit).cloned().collect();
    let next = after + page.len();
    let raw = format!(
        "{{\"schema_id\":\"{SCHEMA}\",\"upper_revision\":{upper},\"next_after_revision\":{next},\"has_more\":{},\"receipts\":[{}]}}",
        next < upper,
        page.join(",")
    );
    (StatusCode::OK, raw).into_response()
}

async fn replace(State(cloud): State<Arc<Cloud>>, body: String) -> Response {
    cloud.bodies.lock().unwrap().push(body.clone());
    let request: Value = serde_json::from_str(&body).unwrap();
    let expected = request["expected_revision"].as_u64().unwrap() as usize;
    let mut receipts = cloud.receipts.lock().unwrap();
    if expected != receipts.len() {
        return (
            StatusCode::CONFLICT,
            Json(
                json!({"detail":{"code":"project_schema_revision_conflict","message":"rejected"}}),
            ),
        )
            .into_response();
    }
    let mut document = request["document"].clone();
    document["revision"] = json!(expected + 1);
    let receipt = receipt_json(&document, request["change_id"].as_str().unwrap());
    receipts.push(receipt.clone());
    (StatusCode::OK, receipt).into_response()
}

async fn receipt(State(cloud): State<Arc<Cloud>>, body: String) -> Response {
    cloud.bodies.lock().unwrap().push(body.clone());
    let query: Value = serde_json::from_str(&body).unwrap();
    let change = query["change_id"].as_str().unwrap();
    let receipts = cloud.receipts.lock().unwrap();
    for raw in receipts.iter() {
        let parsed: Value = serde_json::from_str(raw).unwrap();
        if parsed["change_id"] == change {
            return (StatusCode::OK, raw.clone()).into_response();
        }
    }
    (
        StatusCode::NOT_FOUND,
        Json(json!({"detail":{"code":"project_schema_receipt_not_found","message":"absent"}})),
    )
        .into_response()
}

async fn schema_generation(
    State(cloud): State<Arc<Cloud>>,
    request: Request,
    next: Next,
) -> Response {
    let path = request.uri().path();
    if !path.contains("/schema/document/") {
        return next.run(request).await;
    }
    let required = !path.ends_with("/read");
    let values: Vec<_> = request
        .headers()
        .get_all(super::trusted_cloud_connection::GENERATION_HEADER)
        .iter()
        .collect();
    let current = generation_value(*cloud.generation.lock().unwrap());
    let matches = values.len() == 1
        && serde_json::from_slice::<Value>(values[0].as_bytes())
            .ok()
            .as_ref()
            == Some(&current);
    if values.len() > 1 || (required && !matches) {
        return StatusCode::PRECONDITION_FAILED.into_response();
    }
    next.run(request).await
}

async fn cloud(seed: Vec<String>) -> (Arc<Cloud>, String, tokio::task::JoinHandle<()>) {
    let cloud = Arc::new(Cloud {
        receipts: Mutex::new(seed),
        generation: Mutex::new(1),
        ..Cloud::default()
    });
    let app = Router::new()
        .route("/api/v1/auth/me", get(user))
        .route("/api/v1/projects/remote-project", get(project))
        .route(
            "/api/v1/projects/remote-project/schema/document/read",
            post(read),
        )
        .route(
            "/api/v1/projects/remote-project/schema/document/history",
            post(history),
        )
        .route(
            "/api/v1/projects/remote-project/schema/document/replace",
            post(replace),
        )
        .route(
            "/api/v1/projects/remote-project/schema/document/receipt",
            post(receipt),
        )
        .layer(axum::middleware::from_fn_with_state(
            Arc::clone(&cloud),
            schema_generation,
        ))
        .with_state(Arc::clone(&cloud));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (cloud, base, task)
}

fn broker(directory: &TestDirectory, base: &str) -> TrustedSessionBroker {
    let broker = TrustedSessionBroker::native(
        ApplicationCredentialVault::open(&directory.0.join("schema-view-vault")).unwrap(),
    );
    broker
        .save(TrustedSessionRecord {
            version: 1,
            api_base_url: base.into(),
            runtime_mode: TrustedSessionRuntimeMode::Cloud,
            credential_kind: TrustedSessionCredentialKind::CloudBearer,
            credential: "cloud-test-credential".into(),
            expires_at: None,
        })
        .unwrap();
    broker
}

fn authority(base: &str) -> String {
    format!("{}/api/v1", base.trim_end_matches('/'))
}

type View = super::sync_transport::schema::SchemaCloudView;

async fn connect(broker: &TrustedSessionBroker, base: &str) -> View {
    View::connect(
        broker,
        &authority(base),
        "remote-tenant",
        "remote-project",
        "remote-actor",
    )
    .await
    .unwrap()
}

fn cloud_receipt(document: &Value, change: &str) -> CloudSchemaReceipt {
    CloudSchemaReceipt::from_json(
        &receipt_json(document, change),
        "remote-tenant",
        "remote-project",
    )
    .unwrap()
}

#[tokio::test]
async fn schema_view_reads_history_replaces_and_looks_up_receipts() {
    let directory = TestDirectory::new();
    let root = document(1, json!([member(MEMBER, "人物")]));
    let (cloud, base, task) = cloud(vec![receipt_json(&root, CHANGE)]).await;
    let broker = broker(&directory, &base);
    let view = connect(&broker, &base).await;
    let observed = view.document().unwrap();
    assert_eq!(observed.revision(), 1);
    assert_eq!(observed.entity_types()[0].name, "人物");
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 100).unwrap();
    let page = view.history(&query, None, &|| Ok(())).await.unwrap();
    assert_eq!(page.upper_revision(), 1);
    assert!(!page.has_more());
    assert_eq!(page.receipts()[0].as_json(), receipt_json(&root, CHANGE));
    let next = document(2, json!([member(MEMBER, "人物"), member(SECOND, "组织")]));
    let candidate = ProjectSchemaDocument::from_json(&next.to_string()).unwrap();
    let request =
        CloudSchemaReplaceRequest::new(&page.receipts()[0], &candidate, NEXT_CHANGE).unwrap();
    let accepted = view.replace(&request, &|| Ok(())).await.unwrap();
    assert_eq!(accepted.revision(), 2);
    assert_eq!(accepted.change_id(), NEXT_CHANGE);
    let bodies = cloud.bodies.lock().unwrap().clone();
    assert!(bodies.contains(&request.as_json().to_owned()));
    let lookup = CloudSchemaReceiptQuery::new(SCHEMA, NEXT_CHANGE).unwrap();
    let found = view.receipt(&lookup, &|| Ok(())).await.unwrap().unwrap();
    assert_eq!(found, accepted);
    let missing = CloudSchemaReceiptQuery::new(SCHEMA, MEMBER).unwrap();
    assert!(view.receipt(&missing, &|| Ok(())).await.unwrap().is_none());
    let resume = CloudSchemaHistoryQuery::new(SCHEMA, 1, 100).unwrap();
    let page = view
        .history(&resume, Some(&page.receipts()[0]), &|| Ok(()))
        .await
        .unwrap();
    assert_eq!(page.receipts()[0].revision(), 2);
    let refreshed = view.read(&|| Ok(())).await.unwrap().unwrap();
    assert_eq!(refreshed.revision(), 2);
    task.abort();
}

#[tokio::test]
async fn schema_view_rejects_changed_authority_wrong_scope_and_wrong_actor() {
    let directory = TestDirectory::new();
    let root = document(1, json!([member(MEMBER, "人物")]));
    let (cloud, base, task) = cloud(vec![receipt_json(&root, CHANGE)]).await;
    let broker = broker(&directory, &base);
    assert!(matches!(
        View::connect(
            &broker,
            "https://other.example/api/v1",
            "remote-tenant",
            "remote-project",
            "remote-actor",
        )
        .await,
        Err(KnowledgeAuthorityErrorV2::ScopeMismatch)
    ));
    assert_eq!(cloud.auth_calls.load(Ordering::SeqCst), 0);
    assert!(matches!(
        View::connect(
            &broker,
            &authority(&base),
            "remote-tenant",
            "remote-project",
            "another-actor",
        )
        .await,
        Err(KnowledgeAuthorityErrorV2::ScopeMismatch)
    ));
    cloud.wrong_scope.store(true, Ordering::SeqCst);
    assert!(matches!(
        View::connect(
            &broker,
            &authority(&base),
            "remote-tenant",
            "remote-project",
            "remote-actor",
        )
        .await,
        Err(KnowledgeAuthorityErrorV2::ScopeMismatch)
    ));
    task.abort();
}

#[tokio::test]
async fn schema_view_fails_closed_on_generation_change_and_local_fence() {
    let directory = TestDirectory::new();
    let root = document(1, json!([member(MEMBER, "人物")]));
    let (cloud, base, task) = cloud(vec![receipt_json(&root, CHANGE)]).await;
    let broker = broker(&directory, &base);
    let view = connect(&broker, &base).await;
    let sent = cloud.bodies.lock().unwrap().len();
    let fence = || Err(KnowledgeAuthorityErrorV2::TransportUnavailable);
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 100).unwrap();
    assert!(matches!(
        view.history(&query, None, &fence).await,
        Err(KnowledgeAuthorityErrorV2::TransportUnavailable)
    ));
    assert_eq!(cloud.bodies.lock().unwrap().len(), sent);
    *cloud.generation.lock().unwrap() = 2;
    assert!(matches!(
        view.history(&query, None, &|| Ok(())).await,
        Err(KnowledgeAuthorityErrorV2::CloudGenerationMismatch)
    ));
    assert!(matches!(
        view.read(&|| Ok(())).await,
        Err(KnowledgeAuthorityErrorV2::CloudGenerationMismatch)
    ));
    task.abort();
}

#[tokio::test]
async fn schema_view_replace_conflict_stays_explicit_and_recovers_by_receipt() {
    let directory = TestDirectory::new();
    let root = document(1, json!([member(MEMBER, "人物")]));
    let (_cloud, base, task) = cloud(vec![receipt_json(&root, CHANGE)]).await;
    let broker = broker(&directory, &base);
    let view = connect(&broker, &base).await;
    let base_receipt = cloud_receipt(&root, CHANGE);
    let next = document(2, json!([member(MEMBER, "人物"), member(SECOND, "组织")]));
    let candidate = ProjectSchemaDocument::from_json(&next.to_string()).unwrap();
    let request = CloudSchemaReplaceRequest::new(&base_receipt, &candidate, NEXT_CHANGE).unwrap();
    view.replace(&request, &|| Ok(())).await.unwrap();
    // A stale retry of the same CAS base conflicts; the original acceptance is
    // recovered only through an explicit receipt lookup, never by a rebase.
    let stale = CloudSchemaReplaceRequest::new(&base_receipt, &candidate, NEXT_CHANGE).unwrap();
    assert!(matches!(
        view.replace(&stale, &|| Ok(())).await,
        Err(KnowledgeAuthorityErrorV2::RemoteRejected)
    ));
    let lookup = CloudSchemaReceiptQuery::new(SCHEMA, NEXT_CHANGE).unwrap();
    let recovered = view.receipt(&lookup, &|| Ok(())).await.unwrap().unwrap();
    request.require_receipt(&recovered).unwrap();
    task.abort();
}
