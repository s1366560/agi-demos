use super::*;
use crate::application_vault::ApplicationCredentialVault;
use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    routing::{get, post},
    Json, Router,
};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

struct HttpState {
    distribution: Value,
    bearers: Mutex<Vec<String>>,
    posts: Mutex<Vec<Value>>,
    fail_post: AtomicBool,
    block_get: AtomicBool,
    entered: tokio::sync::Notify,
    release: tokio::sync::Notify,
}
struct Fixture {
    service: DesktopRendererReceiptServiceV2,
    broker: PluginDataPlaneCredentialBrokerV2,
    http: Arc<HttpState>,
    task: tokio::task::JoinHandle<()>,
    directory: std::path::PathBuf,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.task.abort();
        let _ = std::fs::remove_dir_all(&self.directory);
    }
}
async fn get_distribution(State(state): State<Arc<HttpState>>, headers: HeaderMap) -> Json<Value> {
    state
        .bearers
        .lock()
        .unwrap()
        .push(headers["authorization"].to_str().unwrap().to_owned());
    if state.block_get.load(Ordering::SeqCst) {
        state.entered.notify_one();
        state.release.notified().await;
    }
    Json(state.distribution.clone())
}
async fn receive_receipt(
    State(state): State<Arc<HttpState>>,
    headers: HeaderMap,
    Json(body): Json<Value>,
) -> StatusCode {
    state
        .bearers
        .lock()
        .unwrap()
        .push(headers["authorization"].to_str().unwrap().to_owned());
    state.posts.lock().unwrap().push(body);
    if state.fail_post.load(Ordering::SeqCst) {
        StatusCode::SERVICE_UNAVAILABLE
    } else {
        StatusCode::OK
    }
}
fn cloud() -> Result<Selection, String> {
    Ok((PlatformPluginAuthorityModeV2::Cloud, 7))
}
async fn fixture(participation: bool) -> Fixture {
    let snapshot: Value = serde_json::from_str(include_str!(
        "../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    let distribution = json!({"schema_version":2,"descriptor":{"profile_id":snapshot["profile_id"],"generation":snapshot["generation"],"digest":snapshot["digest"]},"envelope":{"version":12,"nonce":"renderer-request","snapshot_digest":snapshot["digest"],"type_url":"memstack.plugin.v2.ProfileSnapshot"},"snapshot":snapshot});
    // Use the protocol's declared type URL rather than a synthetic accepted parser.
    let mut distribution = distribution;
    distribution["envelope"]["type_url"] =
        json!(agistack_plugin_host::protocol_v2::PLATFORM_PLUGIN_SNAPSHOT_TYPE_URL_V2);
    let http = Arc::new(HttpState {
        distribution,
        bearers: Mutex::new(Vec::new()),
        posts: Mutex::new(Vec::new()),
        fail_post: AtomicBool::new(false),
        block_get: AtomicBool::new(false),
        entered: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let router = Router::new()
        .route(
            "/control/api/v1/platform-plugins/v2/distribution",
            get(get_distribution),
        )
        .route(
            "/control/api/v1/platform-plugins/v2/data-plane-state",
            post(receive_receipt),
        )
        .with_state(http.clone());
    let task = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let directory = std::env::temp_dir().join(format!("renderer-receipt-test-{}", Uuid::new_v4()));
    let vault = ApplicationCredentialVault::open(&directory).unwrap();
    let broker = PluginDataPlaneCredentialBrokerV2::native_renderer(vault);
    broker
        .save(&PluginDataPlaneCredentialRecordV2 {
            version: 2,
            api_base_url: format!("http://{address}/control"),
            data_plane_id: DESKTOP_RENDERER_DATA_PLANE_ID_V2.to_owned(),
            credential: format!("ms_dp_{}", "a".repeat(64)),
            ack_participation: participation,
        })
        .unwrap();
    let service = DesktopRendererReceiptServiceV2::new(broker.clone()).unwrap();
    Fixture {
        service,
        broker,
        http,
        task,
        directory,
    }
}
fn submission(value: &Value, owner: &str) -> RendererReceiptSubmissionV2 {
    RendererReceiptSubmissionV2 {
        owner_id: owner.to_owned(),
        delivery_token: value["delivery_token"].as_str().unwrap().to_owned(),
        receipt: SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Ack,
            requested_version: 12,
            requested_digest: value["distribution"]["snapshot"]["digest"]
                .as_str()
                .unwrap()
                .to_owned(),
            applied_version: Some(12),
            applied_digest: Some(
                value["distribution"]["snapshot"]["digest"]
                    .as_str()
                    .unwrap()
                    .to_owned(),
            ),
            error_code: None,
            error_message: None,
        },
    }
}

#[tokio::test]
async fn renderer_delivery_posts_exact_plane_receipt_and_retries_without_reapplying() {
    let f = fixture(true).await;
    let first = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    let repeat = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    assert_eq!(first, repeat);
    f.http.fail_post.store(true, Ordering::SeqCst);
    assert!(f
        .service
        .submit(submission(&first, "owner"), cloud)
        .await
        .is_err());
    f.http.fail_post.store(false, Ordering::SeqCst);
    f.service
        .submit(submission(&first, "owner"), cloud)
        .await
        .unwrap();
    f.service
        .submit(submission(&first, "owner"), cloud)
        .await
        .unwrap();
    let posts = f.http.posts.lock().unwrap();
    assert_eq!(posts.len(), 2);
    assert_eq!(posts[0], posts[1]);
    assert_eq!(posts[0]["data_plane_id"], "desktop-renderer-v2");
    assert_eq!(posts[0]["nonce"], "renderer-request");
    assert_eq!(posts[0]["schema_version"], 2);
    assert!(f
        .http
        .bearers
        .lock()
        .unwrap()
        .iter()
        .all(|value| value == &format!("Bearer ms_dp_{}", "a".repeat(64))));
}

#[tokio::test]
async fn renderer_delivery_rejects_owner_identity_scope_rotation_and_replays() {
    let f = fixture(true).await;
    let first = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    assert!(f
        .service
        .submit(submission(&first, "other"), cloud)
        .await
        .is_err());
    assert!(f
        .service
        .submit(submission(&first, "owner"), || Ok((
            PlatformPluginAuthorityModeV2::Cloud,
            8
        )))
        .await
        .is_err());
    assert!(f
        .service
        .submit(submission(&first, "owner"), || Ok((
            PlatformPluginAuthorityModeV2::Local,
            7
        )))
        .await
        .is_err());
    let mut invalid = submission(&first, "owner");
    invalid.receipt.requested_version = 13;
    assert!(f.service.submit(invalid, cloud).await.is_err());
    let mut record = f.broker.load().unwrap().unwrap();
    record.credential = format!("ms_dp_{}", "b".repeat(64));
    f.broker.save(&record).unwrap();
    assert!(f
        .service
        .submit(submission(&first, "owner"), cloud)
        .await
        .is_err());
    let rotated = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    assert_ne!(first["delivery_token"], rotated["delivery_token"]);
    assert_eq!(first["authority_id"], rotated["authority_id"]);
    f.service.invalidate().unwrap();
    assert!(f
        .service
        .submit(submission(&rotated, "owner"), cloud)
        .await
        .is_err());
    let replacement = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    assert_ne!(replacement["delivery_token"], rotated["delivery_token"]);
    f.service.retire_owner("owner").unwrap();
    assert!(f
        .service
        .submit(submission(&replacement, "owner"), cloud)
        .await
        .is_err());
    assert!(f.http.posts.lock().unwrap().is_empty());
}

#[tokio::test]
async fn renderer_delivery_nack_is_original_and_post_requires_explicit_participation() {
    let f = fixture(false).await;
    let first = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    assert_eq!(
        f.service
            .submit(submission(&first, "owner"), cloud)
            .await
            .unwrap_err(),
        "renderer_ack_disabled"
    );
    assert!(f.http.posts.lock().unwrap().is_empty());
    let mut record = f.broker.load().unwrap().unwrap();
    record.ack_participation = true;
    f.broker.save(&record).unwrap();
    let next = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    let mut nack = submission(&next, "owner");
    nack.receipt.status = ApplyStatusV2::Nack;
    nack.receipt.applied_version = None;
    nack.receipt.applied_digest = None;
    nack.receipt.error_code = Some("candidate_failed".into());
    nack.receipt.error_message = Some("renderer candidate failed".into());
    f.service.submit(nack, cloud).await.unwrap();
    assert_eq!(f.http.posts.lock().unwrap()[0]["receipt"]["status"], "nack");
    assert!(f
        .service
        .submit(submission(&next, "owner"), cloud)
        .await
        .is_err());
}

#[tokio::test]
async fn renderer_delivery_local_and_missing_credentials_never_fetch_cloud() {
    let f = fixture(true).await;
    assert!(f
        .service
        .fetch("owner", || Ok((PlatformPluginAuthorityModeV2::Local, 0)))
        .await
        .is_err());
    f.broker.clear().unwrap();
    assert!(f.service.fetch("owner", cloud).await.is_err());
    assert!(f.http.bearers.lock().unwrap().is_empty());
}

#[tokio::test]
async fn renderer_fetch_late_result_cannot_restore_retired_owner() {
    let f = fixture(true).await;
    f.http.block_get.store(true, Ordering::SeqCst);
    let request = f.service.fetch("owner", cloud);
    let retire = async {
        tokio::time::timeout(Duration::from_secs(2), f.http.entered.notified())
            .await
            .unwrap();
        f.service.retire_owner("owner").unwrap();
        f.http.release.notify_one();
    };
    let (result, ()) = tokio::join!(request, retire);
    assert_eq!(result.unwrap_err(), "renderer_delivery_superseded");
    assert!(f.service.deliveries.lock().unwrap().owners.is_empty());
}

#[tokio::test]
async fn renderer_fetch_late_result_rechecks_selection_and_configuration() {
    for rotate in [false, true] {
        let f = fixture(true).await;
        f.http.block_get.store(true, Ordering::SeqCst);
        let selected = std::sync::atomic::AtomicU64::new(7);
        let request = f.service.fetch("owner", || {
            Ok((
                PlatformPluginAuthorityModeV2::Cloud,
                selected.load(Ordering::SeqCst),
            ))
        });
        let change = async {
            tokio::time::timeout(Duration::from_secs(2), f.http.entered.notified())
                .await
                .unwrap();
            if rotate {
                f.service.invalidate().unwrap();
            } else {
                selected.store(8, Ordering::SeqCst);
            }
            f.http.release.notify_one();
        };
        let (result, ()) = tokio::join!(request, change);
        assert_eq!(result.unwrap_err(), "renderer_delivery_superseded");
        assert!(f.service.deliveries.lock().unwrap().owners.is_empty());
    }
}

#[tokio::test]
async fn renderer_owner_capacity_is_bounded_and_retirement_frees_a_slot() {
    let f = fixture(true).await;
    {
        let mut state = f.service.deliveries.lock().unwrap();
        for index in 0..MAX_OWNERS {
            state
                .requests
                .insert(format!("owner-{index}"), Uuid::new_v4());
        }
    }
    assert_eq!(
        f.service.fetch("overflow", cloud).await.unwrap_err(),
        "renderer_owner_capacity"
    );
    assert!(f.http.bearers.lock().unwrap().is_empty());
    f.service.retire_owner("owner-0").unwrap();
    assert!(f.service.fetch("overflow", cloud).await.unwrap().is_some());
}

#[tokio::test]
async fn renderer_stale_nack_preserves_a_newer_applied_identity() {
    let f = fixture(true).await;
    let value = f.service.fetch("owner", cloud).await.unwrap().unwrap();
    let mut request = submission(&value, "owner");
    request.receipt.status = ApplyStatusV2::Nack;
    request.receipt.applied_version = Some(13);
    request.receipt.error_code = Some("stale_version".into());
    request.receipt.error_message = Some("snapshot version is stale".into());
    f.service.submit(request, cloud).await.unwrap();
    assert_eq!(
        f.http.posts.lock().unwrap()[0]["receipt"]["applied_version"],
        13
    );
}
