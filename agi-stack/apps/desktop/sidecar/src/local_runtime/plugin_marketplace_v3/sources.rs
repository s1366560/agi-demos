use super::package::{self, Package, Result};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    path::{Path, PathBuf},
    time::Duration,
};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct Source {
    pub id: String,
    pub name: String,
    pub kind: String,
    pub location: String,
    pub trusted: bool,
}

/// A request owns its download scratch directory; snapshots live outside this tree.
pub(super) struct Scratch(pub PathBuf);
impl Scratch {
    pub(super) fn new(parent: &Path) -> Result<Self> {
        let path = parent.join(uuid::Uuid::new_v4().to_string());
        std::fs::create_dir_all(&path).map_err(|e| e.to_string())?;
        Ok(Self(path))
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn https(raw: &str) -> Result<url::Url> {
    let url = url::Url::parse(raw).map_err(|_| "source URL is invalid")?;
    let host = url.host_str().ok_or("source URL needs a hostname")?;
    if url.scheme() != "https"
        || !url.username().is_empty()
        || url.password().is_some()
        || host == "localhost"
        || host.ends_with(".localhost")
        || host.parse::<std::net::IpAddr>().is_ok()
    {
        return Err(
            "remote sources require HTTPS with a public hostname and no credentials".into(),
        );
    }
    Ok(url)
}
pub(super) fn validate(source: &Source) -> Result<()> {
    if source.name.trim().is_empty() || source.name.len() > 128 {
        return Err("source name is required".into());
    }
    match source.kind.as_str() {
        "local" => {
            if !Path::new(&source.location).is_absolute() || !Path::new(&source.location).is_dir() {
                return Err("local source must be an absolute directory".into());
            }
        }
        "https" | "git" => {
            https(&source.location)?;
        }
        _ => return Err("unsupported source kind".into()),
    }
    Ok(())
}
pub(super) async fn resolved(raw: &str) -> Result<(url::Url, Vec<std::net::SocketAddr>)> {
    let url = https(raw)?;
    let host = url.host_str().ok_or("invalid host")?;
    let addresses = tokio::time::timeout(
        Duration::from_secs(10),
        tokio::net::lookup_host((host, url.port_or_known_default().unwrap_or(443))),
    )
    .await
    .map_err(|_| "source DNS lookup timed out")?
    .map_err(|_| "source DNS lookup failed")?
    .collect::<Vec<_>>();
    if addresses.is_empty()
        || addresses.iter().any(|a| match a.ip() {
            std::net::IpAddr::V4(ip) => {
                ip.is_private()
                    || ip.is_loopback()
                    || ip.is_link_local()
                    || ip.is_unspecified()
                    || ip.is_multicast()
            }
            std::net::IpAddr::V6(ip) => {
                ip.is_loopback()
                    || ip.is_unspecified()
                    || ip.is_unique_local()
                    || ip.is_unicast_link_local()
                    || ip.is_multicast()
                    || ip.to_ipv4_mapped().is_some()
            }
        })
    {
        return Err("source resolves to a non-public address".into());
    }
    Ok((url, addresses))
}
async fn download(raw: &str, max: usize) -> Result<Vec<u8>> {
    let (url, addresses) = resolved(raw).await?;
    let host = url.host_str().ok_or("invalid host")?;
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(Duration::from_secs(30))
        .resolve_to_addrs(host, &addresses)
        .build()
        .map_err(|e| e.to_string())?;
    let response = client
        .get(url)
        .send()
        .await
        .map_err(|_| "source download failed")?
        .error_for_status()
        .map_err(|_| "source returned an error")?;
    if response.status().is_redirection() {
        return Err("source redirects are not accepted".into());
    }
    let mut stream = response.bytes_stream();
    let mut data = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| "source download interrupted")?;
        if data.len().saturating_add(chunk.len()) > max {
            return Err("download exceeds size limit".into());
        }
        data.extend_from_slice(&chunk);
    }
    Ok(data)
}
fn git_command(directory: &Path) -> tokio::process::Command {
    let mut command = tokio::process::Command::new("git");
    command
        .current_dir(directory)
        .env_clear()
        .env("PATH", std::env::var_os("PATH").unwrap_or_default())
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_TERMINAL_PROMPT", "0")
        .args([
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.file.allow=never",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "http.followRedirects=false",
            "-c",
            "http.proxy=",
        ])
        .stderr(std::process::Stdio::null())
        .kill_on_drop(true);
    command
}
async fn git_output(command: &mut tokio::process::Command, maximum: u64) -> Result<Vec<u8>> {
    use tokio::io::AsyncReadExt;
    command.stdout(std::process::Stdio::piped());
    let mut child = command.spawn().map_err(|_| "Git unavailable")?;
    let operation = async {
        let mut bytes = Vec::new();
        child
            .stdout
            .take()
            .ok_or("Git stdout unavailable")?
            .take(maximum + 1)
            .read_to_end(&mut bytes)
            .await
            .map_err(|_| "Git output failed")?;
        if bytes.len() as u64 > maximum {
            return Err("Git output exceeds size limit".into());
        }
        if !child.wait().await.map_err(|_| "Git failed")?.success() {
            return Err("Git source operation failed".into());
        }
        Ok(bytes)
    };
    tokio::time::timeout(Duration::from_secs(60), operation)
        .await
        .map_err(|_| "Git source operation timed out")?
}
async fn git_package(source: &Source, cache: &Path) -> Result<PathBuf> {
    if !source.trusted {
        return Err("trust the Git source before fetching it".into());
    }
    let (url, addresses) = resolved(&source.location).await?;
    let checkout = cache.join(format!("git-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir_all(&checkout).map_err(|e| e.to_string())?;
    let result = async {
        git_output(
            git_command(&checkout).args(["init", "--bare", "--quiet"]),
            1024,
        )
        .await?;
        let resolve = format!(
            "http.curloptResolve={}:{}:{}",
            url.host_str().ok_or("invalid host")?,
            url.port_or_known_default().unwrap_or(443),
            addresses[0].ip()
        );
        git_output(
            git_command(&checkout).arg("-c").arg(resolve).args([
                "fetch",
                "--quiet",
                "--depth=1",
                "--no-tags",
                "--",
                &source.location,
                "HEAD",
            ]),
            1024,
        )
        .await?;
        let revision = git_output(
            git_command(&checkout).args(["rev-parse", "--verify", "FETCH_HEAD^{commit}"]),
            128,
        )
        .await?;
        let revision = String::from_utf8(revision)
            .map_err(|_| "invalid Git commit")?
            .trim()
            .to_owned();
        if revision.len() != 40 || !revision.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("invalid Git commit".into());
        }
        let archive = git_output(
            git_command(&checkout).args(["archive", "--format=zip", &revision]),
            package::MAX_BYTES,
        )
        .await?;
        let root = cache.join(uuid::Uuid::new_v4().to_string());
        extract(&archive, &root)?;
        std::fs::write(root.join(".marketplace-source-commit"), revision)
            .map_err(|e| e.to_string())?;
        Ok(root)
    }
    .await;
    let _ = std::fs::remove_dir_all(&checkout);
    result
}
pub(super) async fn packages(source: &Source, cache: &Path) -> Result<Vec<Package>> {
    validate(source)?;
    let root = match source.kind.as_str() {
        "local" => PathBuf::from(&source.location),
        "git" => git_package(source, cache).await?,
        "https" => return remote_packages(source, cache).await,
        _ => return Err("unsupported source kind".into()),
    };
    local_packages(source, &root)
}
fn local_packages(source: &Source, root: &Path) -> Result<Vec<Package>> {
    if root.join(".codex-plugin/plugin.json").is_file() {
        return Ok(vec![package::parse(root, &source.id)?]);
    }
    let (catalog, relative_root) = if root.join("catalog.json").is_file() {
        (
            package::bounded_json(&package::child(root, "catalog.json")?)?,
            root,
        )
    } else {
        (
            package::bounded_json(&package::child(root, ".agents/plugins/marketplace.json")?)?,
            root,
        )
    };
    let entries = catalog
        .get("plugins")
        .and_then(Value::as_array)
        .ok_or("catalog requires plugins array")?;
    if entries.len() > 256 {
        return Err("catalog exceeds 256 plugins".into());
    }
    entries
        .iter()
        .map(|entry| {
            let path = entry
                .get("path")
                .or_else(|| entry.get("source"))
                .and_then(|v| v.as_str().or_else(|| v.get("path").and_then(Value::as_str)))
                .ok_or("catalog plugin requires relative path")?;
            package::parse(&package::child(relative_root, path)?, &source.id)
        })
        .collect()
}
async fn remote_packages(source: &Source, cache: &Path) -> Result<Vec<Package>> {
    let data = download(&source.location, 1024 * 1024).await?;
    let catalog: Value = serde_json::from_slice(&data).map_err(|_| "invalid catalog JSON")?;
    let entries = catalog
        .get("plugins")
        .and_then(Value::as_array)
        .ok_or("catalog requires plugins array")?;
    if entries.len() > 64 {
        return Err("remote catalog exceeds 64 plugins".into());
    }
    let mut output = Vec::new();
    for entry in entries {
        let digest = package::text(entry, "sha256");
        if !digest.is_empty()
            && (digest.len() != 64 || !digest.bytes().all(|b| b.is_ascii_hexdigit()))
        {
            return Err("remote package requires SHA256 digest".into());
        }
        let archive_url = entry
            .get("archive_url")
            .and_then(Value::as_str)
            .or_else(|| {
                entry
                    .get("source")
                    .and_then(|s| s.get("url"))
                    .and_then(Value::as_str)
            })
            .ok_or("remote entry requires archive URL")?;
        let archive = download(archive_url, package::MAX_BYTES as usize).await?;
        if !digest.is_empty()
            && format!("{:x}", Sha256::digest(&archive)) != digest.to_ascii_lowercase()
        {
            return Err("remote archive digest mismatch".into());
        }
        let root = cache.join(uuid::Uuid::new_v4().to_string());
        extract(&archive, &root)?;
        output.push(package::parse(&root, &source.id)?);
    }
    Ok(output)
}
fn extract(bytes: &[u8], root: &Path) -> Result<()> {
    let mut zip =
        zip::ZipArchive::new(std::io::Cursor::new(bytes)).map_err(|_| "invalid plugin ZIP")?;
    if zip.len() > 4096 {
        return Err("archive exceeds 4096 entries".into());
    }
    let mut total = 0_u64;
    for index in 0..zip.len() {
        let mut entry = zip.by_index(index).map_err(|_| "invalid ZIP entry")?;
        if entry
            .unix_mode()
            .is_some_and(|mode| mode & 0o170000 == 0o120000)
        {
            return Err("archive symlinks are not supported".into());
        }
        total = total
            .checked_add(entry.size())
            .ok_or("archive size overflow")?;
        if total > package::MAX_BYTES {
            return Err("expanded archive exceeds 64 MiB".into());
        }
        let relative = entry
            .enclosed_name()
            .ok_or("archive path escapes package")?;
        let target = root.join(relative);
        if entry.is_dir() {
            std::fs::create_dir_all(target).map_err(|e| e.to_string())?;
        } else {
            std::fs::create_dir_all(target.parent().ok_or("invalid archive path")?)
                .map_err(|e| e.to_string())?;
            let mut output = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(target)
                .map_err(|e| e.to_string())?;
            std::io::copy(&mut entry, &mut output).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}
