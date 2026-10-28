use super::*;
use async_trait::async_trait;
use std::sync::Mutex;

struct Mock {
    events: broadcast::Sender<BridgeNotification>,
    requests: Mutex<Vec<Value>>,
    loader: Mutex<String>,
}
#[async_trait]
impl BridgeEndpoint for Mock {
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        self.requests
            .lock()
            .unwrap()
            .push(json!({"method":method,"params":params}));
        let result = if params["method"] == "Page.getFrameTree" {
            json!({"frameTree":{"frame":{"id":"frame-1","loaderId":*self.loader.lock().unwrap()}}})
        } else {
            json!({})
        };
        Ok(json!({"result":result}))
    }
    fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
        self.events.subscribe()
    }
}
struct Fixture {
    host: Arc<BrowserToolHost<Mock>>,
    root: PathBuf,
    input: Value,
}
impl Fixture {
    fn new() -> Self {
        let (events, _) = broadcast::channel(64);
        let host = Arc::new(BrowserToolHost::new(Mock {
            events,
            requests: Mutex::new(Vec::new()),
            loader: Mutex::new("loader-1".into()),
        }));
        let root = std::env::temp_dir().join(new_handle("browser-artifacts-test"));
        std::fs::create_dir(&root).unwrap();
        let root = root.canonicalize().unwrap();
        let input =
            json!({"_artifact_root":root,"_authorized_file_roots":[root],"_blocked_file_roots":[]});
        Self { host, root, input }
    }
    fn event(&self, tab: u64, backend: &str, method: &str, params: Value) {
        self.host
            .endpoint
            .events
            .send(BridgeNotification {
                method: "onCDPEvent".into(),
                params: json!({"tabId":tab,"backend":backend,"method":method,"params":params}),
            })
            .unwrap();
    }
    async fn armed(&self, method: &str) -> Value {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let request = self
                    .host
                    .endpoint
                    .requests
                    .lock()
                    .unwrap()
                    .iter()
                    .find(|request| request["params"]["method"] == method)
                    .cloned();
                if let Some(request) = request {
                    return request["params"]["params"].clone();
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap()
    }
    fn wait(&self, event: &str, duration: u64) -> tokio::task::JoinHandle<CoreResult<Value>> {
        let host = self.host.clone();
        let input = self.input.clone();
        let event = event.to_owned();
        tokio::spawn(async move {
            host.facade_artifact_operation(
                Backend::Chrome,
                7,
                "playwright.waitForEvent",
                &[json!(event), json!({"timeoutMs":duration})],
                &input,
            )
            .await
        })
    }
    async fn restored(&self, method: &str, key: &str, value: Value) {
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                if self
                    .host
                    .endpoint
                    .requests
                    .lock()
                    .unwrap()
                    .iter()
                    .any(|request| {
                        request["params"]["method"] == method
                            && request["params"]["params"][key] == value
                    })
                {
                    return;
                }
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

#[tokio::test]
async fn download_wait_returns_start_and_path_waits_for_completed_own_tab() {
    let fixture = Fixture::new();
    let wait = fixture.wait("download", 2000);
    let armed = fixture.armed("Page.setDownloadBehavior").await;
    let directory = PathBuf::from(armed["downloadPath"].as_str().unwrap());
    fixture.event(
        8,
        "chrome",
        "Page.downloadWillBegin",
        json!({"guid":"other","suggestedFilename":"bad.txt"}),
    );
    fixture.event(
        7,
        "iab",
        "Page.downloadWillBegin",
        json!({"guid":"iab","suggestedFilename":"bad.txt"}),
    );
    assert!(!wait.is_finished());
    fixture.event(
        7,
        "chrome",
        "Page.downloadWillBegin",
        json!({"guid":"own","suggestedFilename":"result.txt"}),
    );
    let handle = wait.await.unwrap().unwrap();
    let args = vec![handle["id"].clone()];
    let path_wait = fixture.host.facade_artifact_operation(
        Backend::Chrome,
        7,
        "download.path",
        &args,
        &fixture.input,
    );
    tokio::pin!(path_wait);
    assert!(
        tokio::time::timeout(Duration::from_millis(20), &mut path_wait)
            .await
            .is_err()
    );
    std::fs::write(directory.join("result.txt"), b"completed bytes").unwrap();
    fixture.event(
        7,
        "chrome",
        "Page.downloadProgress",
        json!({"guid":"own","state":"completed"}),
    );
    assert_eq!(
        path_wait.await.unwrap(),
        json!(directory.join("result.txt"))
    );
    fixture
        .restored("Page.setDownloadBehavior", "behavior", json!("default"))
        .await;
    assert!(
        fixture
            .host
            .facade_artifact_operation(Backend::Chrome, 8, "download.path", &args, &fixture.input)
            .await
            .is_err()
    );
    let other = fixture.root.join("other-run");
    std::fs::create_dir(&other).unwrap();
    let input = json!({"_artifact_root":other});
    assert!(
        fixture
            .host
            .facade_artifact_operation(Backend::Chrome, 7, "download.path", &args, &input)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn cancellation_and_timeout_restore_download_interception() {
    let fixture = Fixture::new();
    let wait = fixture.wait("download", 2000);
    fixture.armed("Page.setDownloadBehavior").await;
    wait.abort();
    let _ = wait.await;
    fixture
        .restored("Page.setDownloadBehavior", "behavior", json!("default"))
        .await;
    let result = fixture.wait("download", 10).await.unwrap();
    assert!(result.unwrap_err().to_string().contains("timed out"));
    assert!(
        fixture
            .host
            .state
            .facade_artifacts
            .lock()
            .unwrap()
            .downloading
            .is_empty()
    );
}

#[tokio::test]
async fn canceled_download_is_never_reported_as_a_file() {
    let fixture = Fixture::new();
    let wait = fixture.wait("download", 2000);
    fixture.armed("Page.setDownloadBehavior").await;
    fixture.event(
        7,
        "chrome",
        "Page.downloadWillBegin",
        json!({"guid":"own","suggestedFilename":"result.txt"}),
    );
    let handle = wait.await.unwrap().unwrap();
    fixture.event(
        7,
        "chrome",
        "Page.downloadProgress",
        json!({"guid":"own","state":"canceled"}),
    );
    let result = fixture
        .host
        .facade_artifact_operation(
            Backend::Chrome,
            7,
            "download.path",
            &[handle["id"].clone()],
            &fixture.input,
        )
        .await;
    assert!(result.unwrap_err().to_string().contains("canceled"));
}

#[tokio::test]
async fn file_chooser_upload_enforces_owner_workspace_and_navigation() {
    let fixture = Fixture::new();
    let wait = fixture.wait("filechooser", 2000);
    fixture.armed("Page.setInterceptFileChooserDialog").await;
    fixture.event(
        7,
        "chrome",
        "Page.fileChooserOpened",
        json!({"frameId":"frame-1","backendNodeId":15,"mode":"selectSingle"}),
    );
    let handle = wait.await.unwrap().unwrap();
    assert_eq!(handle["multiple"], false);
    fixture
        .restored(
            "Page.setInterceptFileChooserDialog",
            "enabled",
            json!(false),
        )
        .await;
    let file = fixture.root.join("allowed.txt");
    std::fs::write(&file, b"upload").unwrap();
    let args = vec![handle["id"].clone(), json!([file])];
    assert!(
        fixture
            .host
            .facade_artifact_operation(
                Backend::Chrome,
                8,
                "filechooser.setFiles",
                &args,
                &fixture.input
            )
            .await
            .is_err()
    );
    let blocked = json!({"_artifact_root":fixture.root,"_authorized_file_roots":[fixture.root],"_blocked_file_roots":[fixture.root]});
    assert!(
        fixture
            .host
            .facade_artifact_operation(Backend::Chrome, 7, "filechooser.setFiles", &args, &blocked)
            .await
            .is_err()
    );
    *fixture.host.endpoint.loader.lock().unwrap() = "navigated".into();
    assert!(
        fixture
            .host
            .facade_artifact_operation(
                Backend::Chrome,
                7,
                "filechooser.setFiles",
                &args,
                &fixture.input
            )
            .await
            .unwrap_err()
            .to_string()
            .contains("navigated")
    );
    *fixture.host.endpoint.loader.lock().unwrap() = "loader-1".into();
    fixture
        .host
        .facade_artifact_operation(
            Backend::Chrome,
            7,
            "filechooser.setFiles",
            &args,
            &fixture.input,
        )
        .await
        .unwrap();
    assert!(
        fixture
            .host
            .facade_artifact_operation(
                Backend::Chrome,
                7,
                "filechooser.setFiles",
                &args,
                &fixture.input
            )
            .await
            .is_err()
    );
    assert!(
        fixture.host.endpoint.requests.lock().unwrap().iter().any(
            |request| request["params"]["method"] == "DOM.setFileInputFiles"
                && request["params"]["params"]["backendNodeId"] == 15
        )
    );
}

#[test]
fn files_and_downloads_reject_symlinks_ambiguity_and_private_paths() {
    let root = std::env::temp_dir().join(new_handle("browser-files-test"));
    std::fs::create_dir(&root).unwrap();
    let root = root.canonicalize().unwrap();
    let file = root.join("file.txt");
    std::fs::write(&file, b"file").unwrap();
    let blocked = root.join("private");
    std::fs::create_dir(&blocked).unwrap();
    let secret = blocked.join("vault");
    std::fs::write(&secret, b"private").unwrap();
    let input = json!({"_authorized_file_roots":[root],"_blocked_file_roots":[blocked]});
    assert_eq!(
        authorized_files(&json!(file), &input).unwrap(),
        vec![file.clone()]
    );
    assert!(authorized_files(&json!(secret), &input).is_err());
    assert!(authorized_files(&json!("relative.txt"), &input).is_err());
    assert!(completed_file(&root, "file.txt").is_err());
    #[cfg(unix)]
    {
        let link = root.join("link");
        std::os::unix::fs::symlink(&secret, &link).unwrap();
        assert!(authorized_files(&json!(link), &input).is_err());
    }
    std::fs::remove_dir_all(&root).unwrap();
}
