//! Export rendered content and observed assets into the trusted artifact root.
use crate::host::{tool_err, Backend, BridgeEndpoint, BrowserToolHost};
use agistack_core::ports::CoreResult;
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};
use std::{
    io::Write,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
    time::Instant,
};

const MAX_EXPORT: usize = 32 * 1024 * 1024;
static NEXT_EXPORT: AtomicU64 = AtomicU64::new(1);

fn directory(input: &Value) -> CoreResult<PathBuf> {
    let root = input["_artifact_root"]
        .as_str()
        .ok_or_else(|| tool_err("browser export authority is unavailable"))?;
    let root = PathBuf::from(root)
        .canonicalize()
        .map_err(|_| tool_err("browser export directory is unavailable"))?;
    if !root.is_dir() {
        return Err(tool_err("browser export root is not a directory"));
    }
    let name = format!(
        "export-{}-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos(),
        NEXT_EXPORT.fetch_add(1, Ordering::Relaxed)
    );
    let path = root.join(name);
    std::fs::create_dir(&path)
        .map_err(|_| tool_err("browser export directory cannot be created"))?;
    Ok(path)
}

fn write(path: &std::path::Path, bytes: &[u8]) -> CoreResult<()> {
    if bytes.len() > MAX_EXPORT {
        return Err(tool_err("browser export exceeds size limit"));
    }
    let mut options = std::fs::OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options
        .open(path)
        .map_err(|_| tool_err("browser export file cannot be created"))?;
    file.write_all(bytes)
        .map_err(|_| tool_err("browser export file cannot be written"))
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    pub(crate) async fn download_media(
        &self,
        backend: Backend,
        tab: u64,
        operation: &str,
        args: &[Value],
        input: &Value,
    ) -> CoreResult<Value> {
        let options = if operation == "playwright.locator" {
            args.get(2).and_then(|args| args.get(0))
        } else {
            args.first()
        };
        let timeout = options
            .and_then(|options| options.get("timeoutMs"))
            .and_then(Value::as_u64)
            .unwrap_or(120_000)
            .clamp(1, 120_000);
        tokio::time::timeout(std::time::Duration::from_millis(timeout), async {
            let source = if operation == "playwright.locator" {
                self.facade_frame_operation(backend, tab, operation, args)
                    .await?
            } else {
                self.facade_evaluate(
                    backend,
                    tab,
                    super::facade::dom_expression(operation, &json!(args))?,
                )
                .await?
            };
            let url = source["url"]
                .as_str()
                .ok_or_else(|| tool_err("media source is unavailable"))?;
            let (bytes, _) = self.resource_bytes(backend, tab, url).await?;
            let parsed = url::Url::parse(url).map_err(|_| tool_err("media URL is invalid"))?;
            let name = source["filename"]
                .as_str()
                .filter(|name| !name.is_empty())
                .or_else(|| parsed.path_segments()?.next_back())
                .filter(|name| {
                    !name.starts_with('.')
                        && name.len() <= 120
                        && name.bytes().all(|byte| {
                            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_')
                        })
                })
                .unwrap_or("media.bin");
            let path = directory(input)?.join(name);
            write(&path, &bytes)?;
            Ok(if operation == "playwright.locator" {
                json!(path)
            } else {
                Value::Null
            })
        })
        .await
        .map_err(|_| tool_err("media download timed out"))?
    }

    async fn resource_bytes(
        &self,
        backend: Backend,
        tab: u64,
        url: &str,
    ) -> CoreResult<(Vec<u8>, Option<String>)> {
        let parsed = url::Url::parse(url).map_err(|_| tool_err("asset URL is invalid"))?;
        if matches!(parsed.scheme(), "data" | "blob") {
            let literal =
                serde_json::to_string(url).map_err(|_| tool_err("media URL is invalid"))?;
            let result = self.facade_evaluate(backend,tab,format!("(async()=>{{const response=await fetch({literal});if(!response.ok)throw Error('media resource unavailable');const reader=response.body.getReader();let chunks=[],size=0;try{{while(true){{const chunk=await reader.read();if(chunk.done)break;size+=chunk.value.length;if(size>{MAX_EXPORT})throw Error('media exceeds size limit');chunks.push(chunk.value);}}}}finally{{await reader.cancel();}}let text='';for(const chunk of chunks)for(let i=0;i<chunk.length;i+=8192)text+=String.fromCharCode(...chunk.subarray(i,i+8192));return{{data:btoa(text),type:response.headers.get('content-type')}}}})()")).await?;
            let bytes = STANDARD
                .decode(
                    result["data"]
                        .as_str()
                        .ok_or_else(|| tool_err("media data unavailable"))?,
                )
                .map_err(|_| tool_err("media encoding invalid"))?;
            if bytes.len() > MAX_EXPORT {
                return Err(tool_err("media exceeds size limit"));
            }
            return Ok((bytes, result["type"].as_str().map(str::to_owned)));
        }
        if !matches!(parsed.scheme(), "http" | "https") {
            return Err(tool_err("asset resource must use HTTP or HTTPS"));
        }
        let (frame, _) = self.world_context(backend, tab).await?;
        if let Ok(resource) = self
            .execute_cdp(
                backend,
                tab,
                "Page.getResourceContent",
                json!({"frameId":frame,"url":url}),
            )
            .await
        {
            if let Some(content) = resource["content"].as_str() {
                let bytes = if resource["base64Encoded"] == true {
                    STANDARD
                        .decode(content)
                        .map_err(|_| tool_err("asset encoding is invalid"))?
                } else {
                    content.as_bytes().to_vec()
                };
                if bytes.len() > MAX_EXPORT {
                    return Err(tool_err("asset exceeds size limit"));
                }
                return Ok((bytes, None));
            }
        }
        let loaded = self.execute_cdp(backend,tab,"Network.loadNetworkResource",json!({"frameId":frame,"url":url,"options":{"disableCache":false,"includeCredentials":true}})).await?;
        let resource = &loaded["resource"];
        if resource["success"] != true {
            return Err(tool_err("browser could not load the observed resource"));
        }
        let handle = resource["stream"]
            .as_str()
            .ok_or_else(|| tool_err("browser returned no resource stream"))?;
        let content_type = resource["headers"]
            .as_object()
            .and_then(|headers| {
                headers
                    .iter()
                    .find(|(key, _)| key.eq_ignore_ascii_case("content-type"))
            })
            .and_then(|(_, value)| value.as_str())
            .map(str::to_owned);
        let mut bytes = Vec::new();
        let result = async {
            loop {
                let chunk = self
                    .execute_cdp(
                        backend,
                        tab,
                        "IO.read",
                        json!({"handle":handle,"size":65536}),
                    )
                    .await?;
                let data = chunk["data"]
                    .as_str()
                    .ok_or_else(|| tool_err("resource chunk is invalid"))?;
                if chunk["base64Encoded"] == true {
                    bytes.extend(
                        STANDARD
                            .decode(data)
                            .map_err(|_| tool_err("resource encoding is invalid"))?,
                    );
                } else {
                    bytes.extend_from_slice(data.as_bytes());
                }
                if bytes.len() > MAX_EXPORT {
                    return Err(tool_err("asset exceeds size limit"));
                }
                if chunk["eof"] == true {
                    break;
                }
            }
            Ok(())
        }
        .await;
        let _ = self
            .execute_cdp(backend, tab, "IO.close", json!({"handle":handle}))
            .await;
        result?;
        Ok((bytes, content_type))
    }

    pub(crate) async fn facade_content(
        &self,
        backend: Backend,
        tab: u64,
        operation: &str,
        args: &[Value],
        input: &Value,
    ) -> CoreResult<Value> {
        let folder = directory(input)?;
        if operation == "capability.pageAssets.bundle" {
            let started = Instant::now();
            let inventory = self.facade_evaluate(backend,tab,format!("(() => {{const x=globalThis.__memstackAssetInventory;if(!x||x.id!=={}||x.pageUrl!==location.href)throw Error('asset inventory expired');return x}})()",args.first().and_then(|arg|arg.get("inventoryId")).unwrap_or(&Value::Null))).await?;
            let selected = inventory["assets"]
                .as_array()
                .ok_or_else(|| tool_err("asset inventory is invalid"))?
                .iter()
                .filter(|asset| {
                    let options = args.first().unwrap_or(&Value::Null);
                    options
                        .get("assetIds")
                        .and_then(Value::as_array)
                        .is_none_or(|ids| ids.contains(&asset["id"]))
                        && options
                            .get("kinds")
                            .and_then(Value::as_array)
                            .is_none_or(|kinds| kinds.contains(&asset["kind"]))
                        && matches!(
                            asset["kind"].as_str(),
                            Some("font" | "image" | "stylesheet" | "video")
                        )
                })
                .cloned()
                .collect::<Vec<_>>();
            let mut assets = Vec::new();
            let mut failures = Vec::new();
            for (index, asset) in selected.iter().enumerate() {
                let result = self
                    .resource_bytes(
                        backend,
                        tab,
                        asset["url"]
                            .as_str()
                            .ok_or_else(|| tool_err("asset URL is invalid"))?,
                    )
                    .await;
                match result {
                    Ok((bytes,content_type)) => {
                        let name = format!("asset-{index:04}"); let path = folder.join(&name); write(&path,&bytes)?;
                        assets.push(json!({"contentType":content_type,"id":asset["id"],"kind":asset["kind"],"name":name,"path":path,"url":asset["url"]}));
                    },
                    Err(error) => failures.push(json!({"contentType":null,"id":asset["id"],"name":asset["name"],"reason":error.to_string(),"url":asset["url"]})),
                }
            }
            let manifest = folder.join("assets.json");
            let result = json!({"assets":assets,"directoryPath":folder,"failures":failures,"manifestPath":manifest,"summary":{"downloadedCount":assets.len(),"failedCount":failures.len(),"requestedCount":selected.len(),"elapsedMs":started.elapsed().as_millis()}});
            write(
                &manifest,
                &serde_json::to_vec_pretty(&result)
                    .map_err(|_| tool_err("asset metadata cannot be encoded"))?,
            )?;
            return Ok(result);
        }
        let (filename, bytes) = match operation {
            "content.export" => {
                let html = self
                    .facade_evaluate(
                        backend,
                        tab,
                        "'<!doctype html>\\n' + document.documentElement.outerHTML".into(),
                    )
                    .await?;
                (
                    "page.html".to_string(),
                    html.as_str()
                        .ok_or_else(|| tool_err("page content is unavailable"))?
                        .as_bytes()
                        .to_vec(),
                )
            }
            "content.exportGsuite" => {
                let page = self.current_url_for_input(input, tab as i64).await?;
                let format = args
                    .first()
                    .and_then(Value::as_str)
                    .ok_or_else(|| tool_err("export format is required"))?;
                let url = gsuite_export_url(&page, format)?;
                let (bytes, _) = self.resource_bytes(backend, tab, &url).await?;
                (format!("document.{format}"), bytes)
            }
            "content.exportYouTubeTranscript" => {
                let page = self.current_url_for_input(input, tab as i64).await?;
                let url = url::Url::parse(&page).map_err(|_| tool_err("invalid page URL"))?;
                if url.scheme() != "https"
                    || !matches!(url.host_str(), Some("youtube.com" | "www.youtube.com"))
                    || url.path() != "/watch"
                {
                    return Err(tool_err("transcripts require an HTTPS YouTube watch page"));
                }
                let result = self.execute_cdp(backend,tab,"Runtime.evaluate",json!({"expression":"JSON.stringify(globalThis.ytInitialPlayerResponse?.captions?.playerCaptionsTracklistRenderer?.captionTracks ?? [])","returnByValue":true})).await?;
                let tracks: Value =
                    serde_json::from_str(result["result"]["value"].as_str().unwrap_or("[]"))
                        .map_err(|_| tool_err("caption metadata is invalid"))?;
                let mut track = url::Url::parse(
                    tracks
                        .get(0)
                        .and_then(|track| track["baseUrl"].as_str())
                        .ok_or_else(|| tool_err("this page has no available transcript"))?,
                )
                .map_err(|_| tool_err("caption URL is invalid"))?;
                if track.scheme() != "https"
                    || !matches!(track.host_str(), Some("youtube.com" | "www.youtube.com"))
                {
                    return Err(tool_err("caption source is outside YouTube"));
                }
                track.query_pairs_mut().append_pair("fmt", "json3");
                let (bytes, _) = self.resource_bytes(backend, tab, track.as_str()).await?;
                let captions: Value = serde_json::from_slice(&bytes)
                    .map_err(|_| tool_err("caption content is invalid"))?;
                let lines = captions["events"]
                    .as_array()
                    .ok_or_else(|| tool_err("caption events are unavailable"))?
                    .iter()
                    .filter_map(|event| event["segs"].as_array())
                    .map(|segments| {
                        segments
                            .iter()
                            .filter_map(|segment| segment["utf8"].as_str())
                            .collect::<String>()
                    })
                    .collect::<Vec<_>>()
                    .join("\n");
                ("transcript.txt".into(), lines.into_bytes())
            }
            _ => return Err(tool_err("unsupported content export")),
        };
        let path = folder.join(filename);
        write(&path, &bytes)?;
        Ok(json!(path))
    }
}

fn gsuite_export_url(page: &str, format: &str) -> CoreResult<String> {
    let url = url::Url::parse(page).map_err(|_| tool_err("invalid Google Workspace URL"))?;
    if url.scheme() != "https" || url.host_str() != Some("docs.google.com") {
        return Err(tool_err("export requires a Google Workspace document"));
    }
    let parts = url
        .path_segments()
        .ok_or_else(|| tool_err("invalid document path"))?
        .collect::<Vec<_>>();
    if parts.len() < 3
        || parts[1] != "d"
        || parts[2].is_empty()
        || !parts[2]
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
    {
        return Err(tool_err("invalid document identity"));
    }
    let kind = parts[0];
    let id = parts[2];
    let allowed = match kind {
        "document" => ["pdf", "md", "docx"].contains(&format),
        "spreadsheets" => ["pdf", "xlsx", "csv"].contains(&format),
        "presentation" => ["pdf", "pptx"].contains(&format),
        _ => false,
    };
    if !allowed {
        return Err(tool_err("format is unavailable for this document type"));
    }
    Ok(if kind == "presentation" {
        format!("https://docs.google.com/presentation/d/{id}/export/{format}")
    } else {
        format!("https://docs.google.com/{kind}/d/{id}/export?format={format}")
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn document_exports_are_bound_to_structured_current_document() {
        assert_eq!(
            gsuite_export_url("https://docs.google.com/spreadsheets/d/abc_1/edit", "xlsx").unwrap(),
            "https://docs.google.com/spreadsheets/d/abc_1/export?format=xlsx"
        );
        assert!(gsuite_export_url("https://attacker.example/document/d/id/edit", "docx").is_err());
        assert!(gsuite_export_url("https://docs.google.com/document/d/id/edit", "xlsx").is_err());
    }
}
