use super::*;
use async_trait::async_trait;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use tokio::sync::{broadcast, Notify};

struct Endpoint {
    hidden: bool,
    calls: Mutex<Vec<Value>>,
    pressed: Notify,
    resume: Notify,
    hold_press: AtomicBool,
    hold_enable: AtomicBool,
    hold_release: AtomicBool,
    fail_press: AtomicBool,
    fail_restore: AtomicBool,
    fail_releases: AtomicUsize,
}
impl Endpoint {
    fn new(hidden: bool) -> Self {
        Self {
            hidden,
            calls: Mutex::new(Vec::new()),
            pressed: Notify::new(),
            resume: Notify::new(),
            hold_press: AtomicBool::new(false),
            hold_enable: AtomicBool::new(false),
            hold_release: AtomicBool::new(false),
            fail_press: AtomicBool::new(false),
            fail_restore: AtomicBool::new(false),
            fail_releases: AtomicUsize::new(0),
        }
    }
    fn events(&self) -> Vec<String> {
        self.calls
            .lock()
            .unwrap()
            .iter()
            .filter_map(|call| match call["method"].as_str()? {
                FOCUS_METHOD => Some(format!("focus:{}", call["params"]["enabled"])),
                "Input.dispatchMouseEvent" => Some(call["params"]["type"].as_str()?.to_string()),
                _ => None,
            })
            .collect()
    }
}
#[async_trait]
impl BridgeEndpoint for Endpoint {
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        self.request_on("chrome-extension", method, params).await
    }
    async fn request_on(&self, _backend: &str, method: &str, params: Value) -> CoreResult<Value> {
        if method != "executeCdp" {
            return Ok(json!({}));
        }
        self.calls.lock().unwrap().push(params.clone());
        if params["method"] == "Page.getFrameTree" {
            return Ok(json!({"result":{"frameTree":{"frame":{"id":"root"}}}}));
        }
        if params["method"] == "Page.createIsolatedWorld" {
            return Ok(json!({"result":{"executionContextId":1}}));
        }
        if params["method"] == "Runtime.evaluate" {
            return Ok(
                json!({"result":{"result":{"value":if self.hidden {"hidden"}else{"visible"}}}}),
            );
        }
        if params["params"]["type"] == "mousePressed" {
            self.pressed.notify_one();
            if self.hold_press.load(Ordering::SeqCst) {
                self.resume.notified().await;
            }
            if self.fail_press.load(Ordering::SeqCst) {
                return Err(tool_err("press failed"));
            }
        }
        if params["method"] == FOCUS_METHOD
            && params["params"]["enabled"] == true
            && self.hold_enable.load(Ordering::SeqCst)
        {
            self.resume.notified().await;
        }
        if params["method"] == FOCUS_METHOD
            && params["params"]["enabled"] == false
            && self.fail_restore.swap(false, Ordering::SeqCst)
        {
            return Err(tool_err("bridge disconnected during restoration"));
        }
        if params["params"]["type"] == "mouseReleased" && self.hold_release.load(Ordering::SeqCst) {
            self.resume.notified().await;
        }
        if params["params"]["type"] == "mouseReleased"
            && self
                .fail_releases
                .try_update(Ordering::SeqCst, Ordering::SeqCst, |count| {
                    count.checked_sub(1)
                })
                .is_ok()
        {
            return Err(tool_err("release failed"));
        }
        Ok(json!({"result":{}}))
    }
    fn subscribe_notifications(&self) -> broadcast::Receiver<crate::protocol::BridgeNotification> {
        broadcast::channel(16).1
    }
}

async fn click(host: &BrowserToolHost<Endpoint>, backend: Backend) -> CoreResult<Value> {
    host.facade_input(backend, 1, "cua.click", &[json!({"x":20,"y":20})])
        .await
}

#[tokio::test]
async fn hidden_input_restores_once_and_visible_preserves_state() {
    for (backend, hidden, expected) in [
        (
            Backend::Chrome,
            true,
            vec!["focus:true", "mousePressed", "mouseReleased", "focus:false"],
        ),
        (
            Backend::Edge,
            true,
            vec!["focus:true", "mousePressed", "mouseReleased", "focus:false"],
        ),
        (
            Backend::Chrome,
            false,
            vec!["mousePressed", "mouseReleased"],
        ),
        (
            Backend::Iab,
            true,
            vec!["focus:true", "mousePressed", "mouseReleased", "focus:false"],
        ),
        (Backend::Iab, false, vec!["mousePressed", "mouseReleased"]),
    ] {
        let host = BrowserToolHost::new(Endpoint::new(hidden));
        click(&host, backend).await.unwrap();
        assert_eq!(host.endpoint.events(), expected);
    }
}

#[tokio::test]
async fn failed_input_releases_before_restoration_without_replaying_press() {
    for backend in [Backend::Chrome, Backend::Edge, Backend::Iab] {
        let host = BrowserToolHost::new(Endpoint::new(true));
        host.endpoint.fail_press.store(true, Ordering::SeqCst);
        assert!(click(&host, backend).await.is_err());
        assert_eq!(
            host.endpoint.events(),
            ["focus:true", "mousePressed", "mouseReleased", "focus:false"]
        );
    }
}

#[tokio::test]
async fn cancellation_releases_and_restores_before_next_sequence() {
    for backend in [Backend::Chrome, Backend::Edge, Backend::Iab] {
        let host = Arc::new(BrowserToolHost::new(Endpoint::new(true)));
        host.endpoint.hold_press.store(true, Ordering::SeqCst);
        let task_host = host.clone();
        let task = tokio::spawn(async move { click(&task_host, backend).await });
        host.endpoint.pressed.notified().await;
        task.abort();
        let _ = task.await;
        host.endpoint.hold_press.store(false, Ordering::SeqCst);
        tokio::time::timeout(Duration::from_secs(1), click(&host, backend))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            host.endpoint.events(),
            [
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false",
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false"
            ]
        );
    }
}

#[tokio::test]
async fn concurrent_full_cdp_focus_waits_for_sequence_restoration() {
    for backend in [Backend::Chrome, Backend::Edge, Backend::Iab] {
        let host = Arc::new(BrowserToolHost::new(Endpoint::new(true)));
        host.endpoint.hold_press.store(true, Ordering::SeqCst);
        let task_host = host.clone();
        let task = tokio::spawn(async move { click(&task_host, backend).await });
        host.endpoint.pressed.notified().await;
        let raw_host = host.clone();
        let raw = tokio::spawn(async move {
            raw_host
                .execute_cdp(backend, 1, FOCUS_METHOD, json!({"enabled":true}))
                .await
        });
        tokio::task::yield_now().await;
        assert_eq!(host.endpoint.events(), ["focus:true", "mousePressed"]);
        host.endpoint.resume.notify_one();
        task.await.unwrap().unwrap();
        raw.await.unwrap().unwrap();
        assert_eq!(
            host.endpoint.events(),
            [
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false",
                "focus:true"
            ]
        );
    }
}

#[tokio::test]
async fn failed_restoration_is_repaired_before_next_input() {
    for backend in [Backend::Chrome, Backend::Edge, Backend::Iab] {
        let host = BrowserToolHost::new(Endpoint::new(true));
        host.endpoint.fail_restore.store(true, Ordering::SeqCst);
        assert!(click(&host, backend).await.is_err());
        click(&host, backend).await.unwrap();
        assert_eq!(
            host.endpoint.events(),
            [
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false",
                "focus:false",
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false"
            ]
        );
    }
}

#[tokio::test]
async fn timeout_during_preparation_restores_before_next_input() {
    for backend in [Backend::Chrome, Backend::Edge, Backend::Iab] {
        let host = BrowserToolHost::new(Endpoint::new(true));
        host.endpoint.hold_enable.store(true, Ordering::SeqCst);
        assert!(
            tokio::time::timeout(Duration::from_millis(20), click(&host, backend))
                .await
                .is_err()
        );
        host.endpoint.hold_enable.store(false, Ordering::SeqCst);
        tokio::time::timeout(Duration::from_secs(1), click(&host, backend))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            host.endpoint.events(),
            [
                "focus:true",
                "focus:false",
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false"
            ]
        );
    }
}

#[tokio::test]
async fn failed_release_is_retained_and_blocks_fresh_input_until_repaired() {
    for backend in [Backend::Chrome, Backend::Edge, Backend::Iab] {
        let host = BrowserToolHost::new(Endpoint::new(true));
        // Fail the normal up, cleanup up, and first recovery up.
        host.endpoint.fail_releases.store(3, Ordering::SeqCst);
        assert!(click(&host, backend).await.is_err());
        assert!(click(&host, backend).await.is_err());
        assert_eq!(
            host.endpoint.events(),
            [
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "mouseReleased",
                "focus:false",
                "mouseReleased"
            ]
        );
        click(&host, backend).await.unwrap();
        assert_eq!(
            host.endpoint.events(),
            [
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "mouseReleased",
                "focus:false",
                "mouseReleased",
                "mouseReleased",
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false"
            ]
        );
    }
}

#[tokio::test]
async fn cancelled_recovery_does_not_forget_unacknowledged_release() {
    for backend in [Backend::Chrome, Backend::Edge, Backend::Iab] {
        let host = BrowserToolHost::new(Endpoint::new(true));
        host.endpoint.fail_releases.store(2, Ordering::SeqCst);
        assert!(click(&host, backend).await.is_err());
        host.endpoint.hold_release.store(true, Ordering::SeqCst);
        assert!(
            tokio::time::timeout(Duration::from_millis(20), click(&host, backend))
                .await
                .is_err()
        );
        host.endpoint.hold_release.store(false, Ordering::SeqCst);
        click(&host, backend).await.unwrap();
        assert_eq!(
            host.endpoint.events(),
            [
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "mouseReleased",
                "focus:false",
                "mouseReleased",
                "mouseReleased",
                "focus:true",
                "mousePressed",
                "mouseReleased",
                "focus:false"
            ]
        );
    }
}
