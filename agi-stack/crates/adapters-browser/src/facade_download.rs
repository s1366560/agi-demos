//! Completion tracking for a single browser download.
use super::{
    broadcast, cdp, completed_file, json, next_event, oneshot, tool_err, watch, BridgeEndpoint,
    BridgeNotification, CoreResult, Download, DownloadResult, Duration, Instant, Interception,
    Owner, PathBuf, Value,
};

pub(super) async fn download_task<E: BridgeEndpoint>(
    mut interception: Interception<E>,
    owner: Owner,
    id: String,
    directory: PathBuf,
    mut events: broadcast::Receiver<BridgeNotification>,
    started: oneshot::Sender<CoreResult<Value>>,
    duration: Duration,
) {
    let mut started = Some(started);
    let (status, receiver) = watch::channel(DownloadResult::Pending);
    let result = tokio::time::timeout(duration, async {
        cdp(
            interception.endpoint.as_ref(),
            owner.backend,
            owner.tab,
            "Page.setDownloadBehavior",
            json!({"behavior":"allow","downloadPath":directory}),
        )
        .await?;
        let _ = interception.ready.send(true);
        let mut download: Option<(String, String)> = None;
        loop {
            let event = next_event(&mut events, &owner).await?;
            if event.method == "Page.downloadWillBegin" {
                if download.is_some() {
                    return Err(tool_err("multiple downloads started during one event wait"));
                }
                let guid = event.params["guid"]
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| tool_err("download identity is unavailable"))?
                    .to_owned();
                let suggested = event.params["suggestedFilename"]
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| tool_err("download filename is unavailable"))?
                    .to_owned();
                download = Some((guid, suggested));
                interception
                    .state
                    .facade_artifacts
                    .lock()
                    .map_err(|_| tool_err("artifact state unavailable"))?
                    .downloads
                    .insert(
                        id.clone(),
                        Download {
                            owner: owner.clone(),
                            created: Instant::now(),
                            result: receiver.clone(),
                        },
                    );
                if let Some(sender) = started.take() {
                    let _ = sender.send(Ok(json!({"id":id})));
                }
            } else if event.method == "Page.downloadProgress" {
                let Some((guid, suggested)) = &download else {
                    continue;
                };
                if event.params["guid"].as_str() != Some(guid) {
                    continue;
                }
                match event.params["state"].as_str() {
                    Some("completed") => break completed_file(&directory, suggested),
                    Some("canceled") => return Err(tool_err("browser download was canceled")),
                    _ => {}
                }
            }
        }
    })
    .await
    .unwrap_or_else(|_| Err(tool_err("browser download timed out")));
    let reset = interception.reset().await;
    let result = match reset {
        Ok(()) => result,
        Err(error) => Err(error),
    };
    if let Some(sender) = started.take() {
        let _ = sender.send(Err(tool_err(result.err().map_or_else(
            || "download completed without a start event".into(),
            |error| error.to_string(),
        ))));
    } else {
        let _ = status.send(match result {
            Ok(path) => DownloadResult::Ready(path),
            Err(error) => DownloadResult::Failed(error.to_string()),
        });
    }
}
