//! Run-scoped browser downloads and native file chooser handles.
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::{
    Arc,
    atomic::{AtomicU64, Ordering},
};
use std::time::{Duration, Instant};

use agistack_core::ports::CoreResult;
use serde_json::{Value, json};
use tokio::sync::{broadcast, oneshot, watch};

use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, HostState, tool_err};
use crate::protocol::{BridgeNotification, OnCdpDetachParams, OnCdpEventParams};

#[path = "facade_download.rs"]
mod download;
use download::download_task;

static NEXT_HANDLE: AtomicU64 = AtomicU64::new(1);
const RETENTION: Duration = Duration::from_secs(900);

#[derive(Default)]
pub(crate) struct ArtifactState {
    downloads: HashMap<String, Download>,
    choosers: HashMap<String, Chooser>,
    downloading: HashSet<Backend>,
    choosing: HashSet<(Backend, u64)>,
    readiness: HashMap<(Backend, u64, bool), watch::Receiver<bool>>,
}

#[derive(Clone, PartialEq, Eq)]
struct Owner {
    root: PathBuf,
    backend: Backend,
    tab: u64,
}
struct Download {
    owner: Owner,
    created: Instant,
    result: watch::Receiver<DownloadResult>,
}
#[derive(Clone)]
enum DownloadResult {
    Pending,
    Ready(PathBuf),
    Failed(String),
}
#[derive(Clone)]
struct Chooser {
    owner: Owner,
    created: Instant,
    frame: String,
    session: Option<String>,
    loader: String,
    node: u64,
    multiple: bool,
}

impl ArtifactState {
    fn prune(&mut self) -> CoreResult<()> {
        self.downloads
            .retain(|_, item| item.created.elapsed() < RETENTION);
        self.choosers
            .retain(|_, item| item.created.elapsed() < RETENTION);
        if self.downloads.len() + self.choosers.len() >= 256 {
            return Err(tool_err("browser artifact handle limit reached"));
        }
        Ok(())
    }
}

fn owner(input: &Value, backend: Backend, tab: u64) -> CoreResult<Owner> {
    let path = input
        .get("_artifact_root")
        .and_then(Value::as_str)
        .ok_or_else(|| tool_err("browser artifact authority is unavailable"))?;
    let root = Path::new(path)
        .canonicalize()
        .map_err(|_| tool_err("browser artifact directory is unavailable"))?;
    if !root.is_dir() {
        return Err(tool_err("browser artifact root must be a directory"));
    }
    Ok(Owner { root, backend, tab })
}

fn timeout(args: &[Value]) -> CoreResult<Duration> {
    let timeout = args
        .get(1)
        .and_then(|value| value.get("timeoutMs").or_else(|| value.get("timeout")));
    let value = match timeout {
        None => 30_000,
        Some(value) => value
            .as_u64()
            .filter(|value| (1..=300_000).contains(value))
            .ok_or_else(|| tool_err("event timeout must be between 1 and 300000 milliseconds"))?,
    };
    Ok(Duration::from_millis(value))
}

async fn cdp<E: BridgeEndpoint>(
    endpoint: &E,
    backend: Backend,
    tab: u64,
    method: &str,
    params: Value,
) -> CoreResult<Value> {
    cdp_session(endpoint, backend, tab, None, method, params).await
}
async fn cdp_session<E: BridgeEndpoint>(
    endpoint: &E,
    backend: Backend,
    tab: u64,
    session: Option<&str>,
    method: &str,
    params: Value,
) -> CoreResult<Value> {
    let mut request = json!({"tabId":tab,"method":method,"params":params});
    if let Some(session) = session {
        request["sessionId"] = json!(session);
    }
    let result = tokio::time::timeout(Duration::from_secs(5), async {
        if backend == Backend::Chrome {
            endpoint.request("executeCdp", request).await
        } else {
            endpoint
                .request_on(
                    &backend.wire_name(),
                    "executeCdp",
                    request,
                )
                .await
        }
    })
    .await
    .map_err(|_| tool_err("browser artifact command timed out"))??;
    Ok(result.get("result").cloned().unwrap_or(Value::Null))
}

/// Restores browser state even if an awaited tool call is canceled.
struct Interception<E: BridgeEndpoint> {
    endpoint: Arc<E>,
    state: Arc<HostState>,
    backend: Backend,
    tab: u64,
    download: bool,
    sessions: Vec<Option<String>>,
    ready: watch::Sender<bool>,
    armed: bool,
}
impl<E: BridgeEndpoint> Interception<E> {
    fn acquire(host: &BrowserToolHost<E>, owner: &Owner, download: bool) -> CoreResult<Self> {
        let mut state = host
            .state
            .facade_artifacts
            .lock()
            .map_err(|_| tool_err("artifact state unavailable"))?;
        state.prune()?;
        let inserted = if download {
            state.downloading.insert(owner.backend)
        } else {
            state.choosing.insert((owner.backend, owner.tab))
        };
        if !inserted {
            return Err(tool_err("another browser artifact wait is already active"));
        }
        let (ready, receiver) = watch::channel(false);
        state
            .readiness
            .insert((owner.backend, owner.tab, download), receiver);
        Ok(Self {
            ready,
            endpoint: host.endpoint.clone(),
            state: host.state.clone(),
            backend: owner.backend,
            tab: owner.tab,
            download,
            sessions: vec![None],
            armed: true,
        })
    }
    async fn reset(&mut self) -> CoreResult<()> {
        let (method, params) = if self.download {
            ("Page.setDownloadBehavior", json!({"behavior":"default"}))
        } else {
            (
                "Page.setInterceptFileChooserDialog",
                json!({"enabled":false}),
            )
        };
        let mut result = Ok(Value::Null);
        for session in &self.sessions {
            let reset = cdp_session(
                self.endpoint.as_ref(),
                self.backend,
                self.tab,
                session.as_deref(),
                method,
                params.clone(),
            )
            .await;
            if reset.is_err() {
                result = reset;
            }
        }
        self.release();
        self.armed = false;
        result.map(|_| ())
    }
    fn release(&self) {
        if let Ok(mut state) = self.state.facade_artifacts.lock() {
            state
                .readiness
                .remove(&(self.backend, self.tab, self.download));
            if self.download {
                state.downloading.remove(&self.backend);
            } else {
                state.choosing.remove(&(self.backend, self.tab));
            }
        }
    }
}
impl<E: BridgeEndpoint> Drop for Interception<E> {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        if let Ok(runtime) = tokio::runtime::Handle::try_current() {
            let mut cleanup = Self {
                endpoint: self.endpoint.clone(),
                state: self.state.clone(),
                backend: self.backend,
                tab: self.tab,
                download: self.download,
                sessions: self.sessions.clone(),
                ready: self.ready.clone(),
                armed: false,
            };
            runtime.spawn(async move {
                let _ = cleanup.reset().await;
            });
        } else {
            self.release();
        }
    }
}

async fn next_event(
    events: &mut broadcast::Receiver<BridgeNotification>,
    owner: &Owner,
) -> CoreResult<OnCdpEventParams> {
    loop {
        let notification = events
            .recv()
            .await
            .map_err(|_| tool_err("browser artifact event stream was interrupted"))?;
        if notification.method == "onBrowserDisconnected" {
            if Backend::from_wire(notification.params["backend"].as_str()) == owner.backend {
                return Err(tool_err("browser instance disconnected during artifact operation"));
            }
        } else if notification.method == "onCDPDetach" {
            if let Ok(detach) = serde_json::from_value::<OnCdpDetachParams>(notification.params) {
                if detach.tab_id == owner.tab
                    && Backend::from_wire(detach.backend.as_deref()) == owner.backend
                {
                    return Err(tool_err("browser tab detached during artifact operation"));
                }
            }
        } else if notification.method == "onCDPEvent" {
            if let Ok(event) = serde_json::from_value::<OnCdpEventParams>(notification.params) {
                if event.tab_id == owner.tab
                    && Backend::from_wire(event.backend.as_deref()) == owner.backend
                {
                    return Ok(event);
                }
            }
        }
    }
}

fn new_handle(prefix: &str) -> String {
    format!(
        "{prefix}-{}-{}",
        std::process::id(),
        NEXT_HANDLE.fetch_add(1, Ordering::Relaxed)
    )
}

fn download_directory(root: &Path, handle: &str) -> CoreResult<PathBuf> {
    let directory = root.join(handle);
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder
        .create(&directory)
        .map_err(|_| tool_err("could not create private browser download directory"))?;
    Ok(directory)
}

fn completed_file(directory: &Path, suggested: &str) -> CoreResult<PathBuf> {
    let entries = std::fs::read_dir(directory)
        .map_err(|_| tool_err("download directory is unavailable"))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| tool_err("download directory cannot be read"))?;
    if entries.len() != 1 {
        return Err(tool_err(
            "completed download did not produce exactly one file",
        ));
    }
    let path = entries[0].path();
    let metadata =
        std::fs::symlink_metadata(&path).map_err(|_| tool_err("download file is unavailable"))?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || path.file_name().and_then(|name| name.to_str()) != Some(suggested)
    {
        return Err(tool_err(
            "download filename or file type did not match the browser event",
        ));
    }
    let path = path
        .canonicalize()
        .map_err(|_| tool_err("download path is unavailable"))?;
    if path.parent() != Some(directory) {
        return Err(tool_err("download escaped its private directory"));
    }
    Ok(path)
}

struct AbortBeforeStart(Option<tokio::task::AbortHandle>);
impl Drop for AbortBeforeStart {
    fn drop(&mut self) {
        if let Some(handle) = self.0.take() {
            handle.abort();
        }
    }
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn wait_artifact_interception(
        &self,
        backend: Backend,
        tab: u64,
    ) -> CoreResult<()> {
        let receivers = self
            .state
            .facade_artifacts
            .lock()
            .map_err(|_| tool_err("artifact state unavailable"))?
            .readiness
            .iter()
            .filter(|((candidate, target, _), _)| *candidate == backend && *target == tab)
            .map(|(_, receiver)| receiver.clone())
            .collect::<Vec<_>>();
        for mut receiver in receivers {
            tokio::time::timeout(Duration::from_secs(10), async {
                loop {
                    if *receiver.borrow_and_update() {
                        return Ok::<(), agistack_core::ports::CoreError>(());
                    }
                    receiver
                        .changed()
                        .await
                        .map_err(|_| tool_err("browser event interception was cancelled"))?;
                }
            })
            .await
            .map_err(|_| tool_err("browser event interception did not become ready"))??;
        }
        Ok(())
    }

    pub(crate) async fn facade_artifact_operation(
        &self,
        backend: Backend,
        tab: u64,
        operation: &str,
        args: &[Value],
        input: &Value,
    ) -> CoreResult<Value> {
        let owner = owner(input, backend, tab)?;
        match operation {
            "download.path" => {
                tokio::time::timeout(timeout(args)?, self.download_path(&owner, args))
                    .await
                    .map_err(|_| tool_err("download path wait timed out"))?
            }
            "filechooser.setFiles" => tokio::time::timeout(
                timeout(&[Value::Null, args.get(2).cloned().unwrap_or(Value::Null)])?,
                self.set_files(&owner, args, input),
            )
            .await
            .map_err(|_| tool_err("file chooser upload timed out"))?,
            "playwright.waitForEvent" => match args.first().and_then(Value::as_str) {
                Some("download") => self.wait_download(owner, timeout(args)?).await,
                Some("filechooser") => self.wait_chooser(owner, timeout(args)?).await,
                _ => Err(tool_err("unsupported browser event")),
            },
            _ => Err(tool_err("unsupported browser artifact operation")),
        }
    }

    async fn wait_download(&self, owner: Owner, duration: Duration) -> CoreResult<Value> {
        let interception = Interception::acquire(self, &owner, true)?;
        self.ensure_page_enabled(owner.backend, owner.tab).await?;
        let id = new_handle("download");
        let directory = download_directory(&owner.root, &id)?;
        let events = self.endpoint.subscribe_notifications();
        let (started, received) = oneshot::channel();
        let task = tokio::spawn(download_task(
            interception,
            owner,
            id,
            directory,
            events,
            started,
            duration,
        ));
        let mut abort = AbortBeforeStart(Some(task.abort_handle()));
        let result = received
            .await
            .map_err(|_| tool_err("download event wait was interrupted"))??;
        abort.0.take();
        Ok(result)
    }

    async fn download_path(&self, owner: &Owner, args: &[Value]) -> CoreResult<Value> {
        let id = args
            .first()
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err("download handle required"))?;
        let mut result = {
            let state = self
                .state
                .facade_artifacts
                .lock()
                .map_err(|_| tool_err("artifact state unavailable"))?;
            let item = state
                .downloads
                .get(id)
                .filter(|item| item.owner == *owner && item.created.elapsed() < RETENTION)
                .ok_or_else(|| {
                    tool_err("download handle expired or belongs to another run or tab")
                })?;
            item.result.clone()
        };
        loop {
            let current = result.borrow_and_update().clone();
            match current {
                DownloadResult::Ready(path) => return Ok(json!(path)),
                DownloadResult::Failed(error) => return Err(tool_err(error)),
                DownloadResult::Pending => result
                    .changed()
                    .await
                    .map_err(|_| tool_err("download completion was interrupted"))?,
            }
        }
    }

    async fn wait_chooser(&self, owner: Owner, duration: Duration) -> CoreResult<Value> {
        let mut interception = Interception::acquire(self, &owner, false)?;
        self.ensure_page_enabled(owner.backend, owner.tab).await?;
        let mut events = self.endpoint.subscribe_notifications();
        self.ensure_facade_targets(owner.backend, owner.tab).await?;
        let sessions: Vec<String> = self
            .state
            .facade_events
            .lock()
            .map_err(|_| tool_err("browser targets unavailable"))?
            .get(&(owner.backend, owner.tab))
            .map(|buffer| {
                buffer
                    .targets
                    .iter()
                    .filter(|(_, target)| target["active"] == true && target["type"] == "iframe")
                    .map(|(session, _)| session.clone())
                    .collect()
            })
            .unwrap_or_default();
        interception.sessions.extend(sessions.into_iter().map(Some));
        for session in &interception.sessions {
            self.execute_cdp_session(
                owner.backend,
                owner.tab,
                session.as_deref(),
                "Page.enable",
                json!({}),
            )
            .await?;
            self.execute_cdp_session(
                owner.backend,
                owner.tab,
                session.as_deref(),
                "Page.setInterceptFileChooserDialog",
                json!({"enabled":true}),
            )
            .await?;
        }
        let _ = interception.ready.send(true);
        let result = tokio::time::timeout(duration, async {
            loop {
                let event = next_event(&mut events, &owner).await?;
                if event.method == "Target.attachedToTarget"
                    && event.params["targetInfo"]["type"] == "iframe"
                {
                    if let Some(session) = event.params["sessionId"].as_str() {
                        let session = session.to_owned();
                        self.execute_cdp_session(
                            owner.backend,
                            owner.tab,
                            Some(&session),
                            "Page.enable",
                            json!({}),
                        )
                        .await?;
                        self.execute_cdp_session(
                            owner.backend,
                            owner.tab,
                            Some(&session),
                            "Page.setInterceptFileChooserDialog",
                            json!({"enabled":true}),
                        )
                        .await?;
                        if !interception.sessions.contains(&Some(session.clone())) {
                            interception.sessions.push(Some(session));
                        }
                    }
                    continue;
                }
                if event.method != "Page.fileChooserOpened" {
                    continue;
                }
                let frame = event.params["frameId"]
                    .as_str()
                    .ok_or_else(|| tool_err("file chooser frame is unavailable"))?
                    .to_owned();
                let node = event.params["backendNodeId"]
                    .as_u64()
                    .filter(|id| *id > 0)
                    .ok_or_else(|| tool_err("file chooser has no input element"))?;
                let multiple = match event.params["mode"].as_str() {
                    Some("selectMultiple") => true,
                    Some("selectSingle") => false,
                    _ => return Err(tool_err("unsupported file chooser mode")),
                };
                let tree = self
                    .execute_cdp_session(
                        owner.backend,
                        owner.tab,
                        event.session_id.as_deref(),
                        "Page.getFrameTree",
                        json!({}),
                    )
                    .await?;
                let loader = frame_loader(&tree["frameTree"], &frame)
                    .ok_or_else(|| tool_err("file chooser frame expired"))?
                    .to_owned();
                let id = new_handle("filechooser");
                let chooser = Chooser {
                    owner: owner.clone(),
                    created: Instant::now(),
                    frame,
                    session: event.session_id,
                    loader,
                    node,
                    multiple,
                };
                self.state
                    .facade_artifacts
                    .lock()
                    .map_err(|_| tool_err("artifact state unavailable"))?
                    .choosers
                    .insert(id.clone(), chooser);
                break Ok(json!({"id":id,"multiple":multiple}));
            }
        })
        .await
        .map_err(|_| tool_err("file chooser event timed out"))?;
        interception.reset().await?;
        result
    }

    async fn set_files(&self, owner: &Owner, args: &[Value], input: &Value) -> CoreResult<Value> {
        let id = args
            .first()
            .and_then(Value::as_str)
            .ok_or_else(|| tool_err("file chooser handle required"))?;
        let chooser = self
            .state
            .facade_artifacts
            .lock()
            .map_err(|_| tool_err("artifact state unavailable"))?
            .choosers
            .get(id)
            .filter(|item| item.owner == *owner && item.created.elapsed() < RETENTION)
            .cloned()
            .ok_or_else(|| {
                tool_err("file chooser handle expired or belongs to another run or tab")
            })?;
        let paths = authorized_files(
            args.get(1).ok_or_else(|| tool_err("file paths required"))?,
            input,
        )?;
        if !chooser.multiple && paths.len() > 1 {
            return Err(tool_err("this file chooser accepts one file"));
        }
        let tree = self
            .execute_cdp_session(
                owner.backend,
                owner.tab,
                chooser.session.as_deref(),
                "Page.getFrameTree",
                json!({}),
            )
            .await?;
        if frame_loader(&tree["frameTree"], &chooser.frame) != Some(chooser.loader.as_str()) {
            return Err(tool_err("file chooser page navigated; open a new chooser"));
        }
        self.execute_cdp_session(
            owner.backend,
            owner.tab,
            chooser.session.as_deref(),
            "DOM.setFileInputFiles",
            json!({"files":paths,"backendNodeId":chooser.node}),
        )
        .await?;
        self.state
            .facade_artifacts
            .lock()
            .map_err(|_| tool_err("artifact state unavailable"))?
            .choosers
            .remove(id);
        Ok(Value::Null)
    }
}

fn frame_loader<'a>(tree: &'a Value, id: &str) -> Option<&'a str> {
    if tree["frame"]["id"].as_str() == Some(id) {
        return tree["frame"]["loaderId"]
            .as_str()
            .filter(|value| !value.is_empty());
    }
    tree["childFrames"]
        .as_array()?
        .iter()
        .find_map(|child| frame_loader(child, id))
}

fn authorized_files(files: &Value, input: &Value) -> CoreResult<Vec<PathBuf>> {
    let paths = if let Some(path) = files.as_str() {
        vec![path]
    } else {
        files
            .as_array()
            .ok_or_else(|| tool_err("files must be a path or array of paths"))?
            .iter()
            .map(|path| {
                path.as_str()
                    .ok_or_else(|| tool_err("files must contain paths"))
            })
            .collect::<CoreResult<Vec<_>>>()?
    };
    if paths.len() > 256 {
        return Err(tool_err("too many files for one chooser"));
    }
    let roots = |key: &str| -> CoreResult<Vec<PathBuf>> {
        input
            .get(key)
            .and_then(Value::as_array)
            .ok_or_else(|| tool_err("file authorization is unavailable"))?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(PathBuf::from)
                    .filter(|path| path.is_absolute())
                    .ok_or_else(|| tool_err("invalid file authorization root"))
            })
            .collect()
    };
    let allowed = roots("_authorized_file_roots")?;
    let blocked = roots("_blocked_file_roots")?;
    paths
        .into_iter()
        .map(|path| {
            let original = Path::new(path);
            if !original.is_absolute() {
                return Err(tool_err("upload paths must be absolute"));
            }
            let path = original
                .canonicalize()
                .map_err(|_| tool_err("upload file is unavailable"))?;
            if blocked
                .iter()
                .any(|root| original.starts_with(root) || path.starts_with(root))
                || !allowed.iter().any(|root| path.starts_with(root))
            {
                return Err(tool_err("upload path is outside the authorized workspace"));
            }
            let file =
                std::fs::File::open(&path).map_err(|_| tool_err("upload file is not readable"))?;
            if !file
                .metadata()
                .map_err(|_| tool_err("upload metadata is unavailable"))?
                .is_file()
            {
                return Err(tool_err("upload path must be a regular file"));
            }
            Ok(path)
        })
        .collect()
}

#[cfg(test)]
#[path = "facade_artifacts_tests.rs"]
mod tests;
