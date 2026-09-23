//! Codex packages remain distinct from the signed V2 protocol.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    path::{Component, Path, PathBuf},
};

pub(super) const MAX_BYTES: u64 = 64 * 1024 * 1024;
pub(super) type Result<T> = std::result::Result<T, String>;

#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct Descriptor {
    pub id: String,
    pub name: String,
    pub description: String,
    pub version: String,
    pub publisher: String,
    pub source_id: String,
    pub format: String,
    pub category: String,
    pub capabilities: Vec<String>,
    pub targets: Vec<String>,
    pub permissions: Vec<String>,
    pub compatible: bool,
    pub reasons: Vec<String>,
    pub readme: Option<String>,
    pub changelog: Option<String>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
pub(super) struct Package {
    pub descriptor: Descriptor,
    pub root: PathBuf,
    pub skills: BTreeMap<String, String>,
    pub servers: BTreeMap<String, Value>,
    pub hooks: BTreeMap<String, Vec<Hook>>,
    pub required: BTreeMap<String, Vec<String>>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(from = "StoredHook")]
pub(super) struct Hook {
    pub command: String,
    pub timeout_seconds: u64,
}
#[derive(Deserialize)]
#[serde(untagged)]
enum StoredHook {
    Command(String),
    Detailed {
        command: String,
        timeout_seconds: u64,
    },
}
impl From<StoredHook> for Hook {
    fn from(value: StoredHook) -> Self {
        match value {
            StoredHook::Command(command) => Self {
                command,
                timeout_seconds: 30,
            },
            StoredHook::Detailed {
                command,
                timeout_seconds,
            } => Self {
                command,
                timeout_seconds: timeout_seconds.clamp(1, 30),
            },
        }
    }
}

pub(super) fn text(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}
pub(super) fn bounded_json(path: &Path) -> Result<Value> {
    let meta = std::fs::symlink_metadata(path).map_err(|e| e.to_string())?;
    if !meta.is_file() || meta.len() > 1024 * 1024 {
        return Err("manifest must be a regular file under 1 MiB".into());
    }
    serde_json::from_slice(&std::fs::read(path).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}
pub(super) fn child(root: &Path, relative: &str) -> Result<PathBuf> {
    let path = Path::new(relative);
    if path.is_absolute()
        || path.components().any(|c| {
            matches!(
                c,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err("plugin paths must remain within the package".into());
    }
    let mut current = root.to_path_buf();
    for component in path.components() {
        current.push(component);
        if std::fs::symlink_metadata(&current)
            .map_err(|e| e.to_string())?
            .file_type()
            .is_symlink()
        {
            return Err("plugin symbolic links are not supported".into());
        }
    }
    Ok(current)
}
fn config(root: &Path, manifest: &Value, key: &str, default: &str) -> Result<Value> {
    match manifest.get(key) {
        Some(Value::String(path)) => bounded_json(&child(root, path)?),
        Some(value @ Value::Object(_)) => Ok(value.clone()),
        Some(_) => Err(format!("{key} must be an object or relative file path")),
        None if root.join(default).exists() => bounded_json(&child(root, default)?),
        None => Ok(json!({})),
    }
}
pub(super) fn parse(root: &Path, source_id: &str) -> Result<Package> {
    if std::fs::symlink_metadata(root)
        .map_err(|e| e.to_string())?
        .file_type()
        .is_symlink()
    {
        return Err("plugin root must not be a symbolic link".into());
    }
    let manifest = bounded_json(&child(root, ".codex-plugin/plugin.json")?)?;
    let name = text(&manifest, "name");
    let version = text(&manifest, "version");
    if name.is_empty() || name.len() > 128 || version.is_empty() || version.len() > 128 {
        return Err("plugin name and version are required (maximum 128 characters)".into());
    }
    let id = manifest
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or(&name)
        .to_owned();
    let mut reasons = Vec::new();
    let mut skills = BTreeMap::new();
    let skill_paths: Vec<String> = match manifest.get("skills") {
        Some(Value::String(path)) => vec![path.clone()],
        Some(Value::Array(paths)) => paths
            .iter()
            .map(|p| {
                p.as_str()
                    .map(str::to_owned)
                    .ok_or("invalid skill path".into())
            })
            .collect::<Result<_>>()?,
        None if root.join("skills").exists() => vec!["skills".into()],
        None => vec![],
        _ => return Err("skills must contain relative directory paths".into()),
    };
    for path in skill_paths {
        let dir = child(root, &path)?;
        let candidates = if dir.join("SKILL.md").is_file() {
            vec![dir]
        } else {
            std::fs::read_dir(dir)
                .map_err(|e| e.to_string())?
                .map(|entry| entry.map(|e| e.path()).map_err(|e| e.to_string()))
                .collect::<Result<Vec<_>>>()?
        };
        for directory in candidates {
            if !directory.join("SKILL.md").exists() {
                continue;
            }
            let relative = directory
                .strip_prefix(root)
                .map_err(|e| e.to_string())?
                .join("SKILL.md");
            let file = child(root, &relative.to_string_lossy())?;
            if std::fs::metadata(&file).map_err(|e| e.to_string())?.len() > 1024 * 1024 {
                return Err("skill exceeds 1 MiB".into());
            }
            let body = std::fs::read_to_string(file).map_err(|e| e.to_string())?;
            let key = directory
                .file_name()
                .and_then(|n| n.to_str())
                .ok_or("invalid skill name")?
                .to_owned();
            skills.insert(key, body);
        }
    }
    let mcp = config(root, &manifest, "mcpServers", ".mcp.json")?;
    let servers: BTreeMap<String, Value> = mcp
        .get("mcpServers")
        .unwrap_or(&mcp)
        .as_object()
        .map(|m| m.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
        .unwrap_or_default();
    let mut required = BTreeMap::new();
    for (name, server) in &servers {
        if super::oauth::declared(server).is_some_and(|value| !value.is_object()) {
            reasons.push(format!("oauth_configuration_must_be_object:{name}"));
        }
        if super::oauth::declared(server).is_some() && !super::oauth::supported_transport(server) {
            reasons.push(format!("oauth_requires_streamable_http:{name}"));
        }
        if server.get("command").and_then(Value::as_str).is_none()
            && server.get("url").and_then(Value::as_str).is_none()
        {
            reasons.push(format!("MCP server {name} needs command or URL"));
        }
        let mut keys = Vec::new();
        for field in ["env", "headers"] {
            if let Some(bindings) = server.get(field).and_then(Value::as_object) {
                for (key, value) in bindings {
                    let raw = value
                        .as_str()
                        .ok_or("MCP credential values must be strings")?;
                    if raw.starts_with("${") && raw.ends_with('}') {
                        keys.push(format!("{field}:{key}"));
                    } else {
                        reasons.push(format!(
                            "MCP {name} {field} must use credential placeholders"
                        ));
                    }
                }
            }
        }
        if !keys.is_empty() {
            required.insert(name.clone(), keys);
        }
    }
    let mut hooks_config = config(root, &manifest, "hooks", "hooks/hooks.json")?;
    if let Some(entries) = hooks_config.get("hooks").and_then(Value::as_array) {
        let mut normalized = serde_json::Map::new();
        for entry in entries {
            let event = text(entry, "event");
            let mut definition = entry.clone();
            definition["type"] = json!("command");
            normalized
                .entry(event)
                .or_insert_with(|| json!([]))
                .as_array_mut()
                .ok_or("invalid hook list")?
                .push(definition);
        }
        hooks_config = json!({"hooks": normalized});
    }
    let mut hooks = BTreeMap::new();
    if let Some(events) = hooks_config
        .get("hooks")
        .unwrap_or(&hooks_config)
        .as_object()
    {
        for (event, definitions) in events {
            if !["session_start", "before_request", "after_tool_execute"].contains(&event.as_str())
            {
                reasons.push(format!("unsupported hook event: {event}"));
                continue;
            }
            let definitions = definitions.as_array().ok_or("hook event requires a list")?;
            let mut commands = Vec::new();
            for definition in definitions {
                let entries = definition
                    .get("hooks")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_else(|| vec![definition.clone()]);
                for entry in entries {
                    if text(&entry, "type") != "command" || text(&entry, "command").is_empty() {
                        reasons.push("only command hooks are supported".into());
                    } else {
                        let timeout_seconds = entry
                            .get("timeout_seconds")
                            .and_then(Value::as_u64)
                            .unwrap_or(30);
                        if !(1..=30).contains(&timeout_seconds) {
                            reasons.push("hook timeout must be between 1 and 30 seconds".into());
                        }
                        commands.push(Hook {
                            command: text(&entry, "command"),
                            timeout_seconds: timeout_seconds.clamp(1, 30),
                        });
                    }
                }
            }
            hooks.insert(event.clone(), commands);
        }
    }
    let apps = config(root, &manifest, "apps", ".app.json")?;
    let apps = apps.get("apps").unwrap_or(&apps);
    let has_apps = apps.as_object().is_some_and(|o| !o.is_empty());
    if let Some(apps) = apps.as_object() {
        for (name, app) in apps {
            if !servers.contains_key(&text(app, "mcp_server")) {
                reasons.push(format!("App {name} needs a declared MCP server; proprietary connector IDs are unsupported"));
            }
        }
    }
    let mut capabilities = Vec::new();
    let mut permissions = Vec::new();
    if !skills.is_empty() {
        capabilities.push("skills".into());
        permissions.push("skills:read".into());
    }
    if !servers.is_empty() {
        capabilities.push("mcp".into());
        if servers
            .values()
            .any(|server| server.get("command").is_some())
        {
            permissions.push("process:execute".into());
        }
        if servers.values().any(|server| server.get("url").is_some()) {
            permissions.push("network:connect".into());
        }
    }
    if !hooks.is_empty() {
        capabilities.push("hooks".into());
        permissions.push("process:execute".into());
    }
    if has_apps {
        capabilities.push("apps".into());
        permissions.push("apps:connect".into());
    }
    if let Some(declared) = manifest.get("permissions").and_then(Value::as_array) {
        for permission in declared {
            permissions.push(
                permission
                    .as_str()
                    .ok_or("permissions must be strings")?
                    .to_owned(),
            );
        }
    }
    permissions.sort();
    permissions.dedup();
    let targets: Vec<String> = manifest
        .get("targets")
        .and_then(Value::as_array)
        .map(|a| {
            a.iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_else(|| vec!["desktop".into(), "web".into()]);
    if !targets.iter().any(|t| t == "desktop") {
        reasons.push("plugin does not target desktop".into());
    }
    let publisher = manifest
        .get("author")
        .and_then(|v| v.as_str().or_else(|| v.get("name").and_then(Value::as_str)))
        .unwrap_or_default()
        .to_owned();
    let read = |name: &str| -> Result<Option<String>> {
        if !root.join(name).exists() {
            return Ok(None);
        }
        let path = child(root, name)?;
        if std::fs::metadata(&path).map_err(|e| e.to_string())?.len() > 1024 * 1024 {
            return Err("documentation exceeds 1 MiB".into());
        }
        Ok(Some(
            std::fs::read_to_string(path).map_err(|e| e.to_string())?,
        ))
    };
    Ok(Package {
        descriptor: Descriptor {
            id,
            name: manifest
                .get("interface")
                .and_then(|i| i.get("displayName"))
                .and_then(Value::as_str)
                .unwrap_or(&name)
                .to_owned(),
            description: text(&manifest, "description"),
            version,
            publisher,
            source_id: source_id.into(),
            format: "codex".into(),
            category: manifest
                .get("interface")
                .map(|i| text(i, "category"))
                .unwrap_or_else(|| text(&manifest, "category")),
            capabilities,
            targets,
            permissions,
            compatible: reasons.is_empty(),
            reasons,
            readme: read("README.md")?,
            changelog: read("CHANGELOG.md")?,
        },
        root: root.to_owned(),
        skills,
        servers,
        hooks,
        required,
    })
}

pub(super) fn files(root: &Path) -> Result<Vec<PathBuf>> {
    fn visit(root: &Path, dir: &Path, output: &mut Vec<PathBuf>, bytes: &mut u64) -> Result<()> {
        for entry in std::fs::read_dir(dir).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            if entry.file_name() == ".git" {
                continue;
            }
            let meta = entry.path().symlink_metadata().map_err(|e| e.to_string())?;
            if meta.file_type().is_symlink() {
                return Err("plugin symbolic links are not supported".into());
            }
            if meta.is_dir() {
                visit(root, &entry.path(), output, bytes)?;
            } else if meta.is_file() {
                *bytes = bytes
                    .checked_add(meta.len())
                    .ok_or("package size overflow")?;
                if *bytes > MAX_BYTES || output.len() >= 4096 {
                    return Err("plugin exceeds 64 MiB or 4096 files".into());
                }
                output.push(
                    entry
                        .path()
                        .strip_prefix(root)
                        .map_err(|e| e.to_string())?
                        .to_owned(),
                );
            } else {
                return Err("plugin contains a special file".into());
            }
        }
        Ok(())
    }
    let mut output = Vec::new();
    visit(root, root, &mut output, &mut 0)?;
    output.sort();
    Ok(output)
}
pub(super) fn digest(root: &Path) -> Result<String> {
    let mut digest = Sha256::new();
    for path in files(root)? {
        let name = path.to_string_lossy();
        digest.update((name.len() as u64).to_be_bytes());
        digest.update(name.as_bytes());
        let bytes = std::fs::read(root.join(path)).map_err(|e| e.to_string())?;
        digest.update((bytes.len() as u64).to_be_bytes());
        digest.update(bytes);
    }
    Ok(format!("{:x}", digest.finalize()))
}
pub(super) fn snapshot(root: &Path, target: &Path) -> Result<()> {
    for path in files(root)? {
        let output = target.join(&path);
        std::fs::create_dir_all(output.parent().ok_or("invalid snapshot path")?)
            .map_err(|e| e.to_string())?;
        std::fs::copy(root.join(path), output).map_err(|e| e.to_string())?;
    }
    Ok(())
}
