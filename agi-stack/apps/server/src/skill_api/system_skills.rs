use std::path::{Path, PathBuf};

use chrono::{DateTime, Utc};
use serde_json::{json, Map, Value};
use uuid::Uuid;

use super::{
    frontmatter, iso8601, normalize_status, parse_allowed_tools, parse_inline_list,
    validate_skill_input, SkillApiError, SkillListView, SkillView,
};

pub(super) async fn list_filesystem_system_skills(
    tenant_id: &str,
    status: Option<&str>,
) -> Result<SkillListView, SkillApiError> {
    let status = status.map(normalize_status).transpose()?;
    if status.as_deref().is_some_and(|status| status != "active") {
        return Ok(SkillListView {
            skills: Vec::new(),
            total: 0,
        });
    }

    let Some(root) = find_system_skills_dir().await? else {
        return Ok(SkillListView {
            skills: Vec::new(),
            total: 0,
        });
    };

    let skill_files = collect_system_skill_files(&root).await?;
    let now = Utc::now();
    let mut skills = Vec::new();
    for path in skill_files {
        let content = match tokio::fs::read_to_string(&path).await {
            Ok(content) => content,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => continue,
        };
        if let Ok(skill) = system_skill_view_from_content(tenant_id, &path, &content, now).await {
            skills.push(skill);
        }
    }
    skills.sort_by(|a, b| a.name.cmp(&b.name).then_with(|| a.id.cmp(&b.id)));
    let total = skills.len();
    Ok(SkillListView { skills, total })
}

async fn find_system_skills_dir() -> Result<Option<PathBuf>, SkillApiError> {
    for candidate in candidate_system_skill_dirs()? {
        match tokio::fs::metadata(&candidate).await {
            Ok(metadata) if metadata.is_dir() => return Ok(Some(candidate)),
            Ok(_) => continue,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => continue,
        }
    }
    Ok(None)
}

fn candidate_system_skill_dirs() -> Result<Vec<PathBuf>, SkillApiError> {
    let cwd = std::env::current_dir().map_err(SkillApiError::internal)?;
    Ok(vec![
        cwd.join("src/builtin/skills"),
        cwd.join("../src/builtin/skills"),
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../src/builtin/skills"),
    ])
}

async fn collect_system_skill_files(root: &Path) -> Result<Vec<PathBuf>, SkillApiError> {
    let mut files = Vec::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(dir) = pending.pop() {
        let direct_skill = dir.join("SKILL.md");
        if path_is_file(&direct_skill).await {
            files.push(direct_skill);
        }

        let mut entries = match tokio::fs::read_dir(&dir).await {
            Ok(entries) => entries,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => continue,
            Err(_) => continue,
        };
        while let Some(entry) = entries
            .next_entry()
            .await
            .map_err(SkillApiError::internal)?
        {
            let file_type = match entry.file_type().await {
                Ok(file_type) => file_type,
                Err(_) => continue,
            };
            if !file_type.is_dir() {
                continue;
            }
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.starts_with('.') && name != ".memstack" && name != ".claude" {
                continue;
            }
            let child_dir = entry.path();
            let child_skill = child_dir.join("SKILL.md");
            if path_is_file(&child_skill).await {
                files.push(child_skill);
            } else {
                pending.push(child_dir);
            }
        }
    }
    files.sort();
    files.dedup();
    Ok(files)
}

async fn path_is_file(path: &Path) -> bool {
    matches!(tokio::fs::metadata(path).await, Ok(metadata) if metadata.is_file())
}

pub(super) async fn system_skill_view_from_content(
    tenant_id: &str,
    file_path: &Path,
    content: &str,
    now: DateTime<Utc>,
) -> Result<SkillView, SkillApiError> {
    let frontmatter = frontmatter(content)
        .ok_or_else(|| SkillApiError::bad_request("Invalid SKILL.md frontmatter"))?;
    let fields = parse_yaml_frontmatter(frontmatter)?;
    let name = required_string_field(&fields, "name")?;
    let description = optional_string_field(&fields, "description")
        .or_else(|| optional_string_field(&fields, "desc"))
        .or_else(|| optional_string_field(&fields, "summary"))
        .unwrap_or_default();
    let allowed_tools_raw = optional_string_field(&fields, "allowed-tools")
        .or_else(|| optional_string_field(&fields, "allowed_tools"));
    let tools = allowed_tools_raw
        .as_deref()
        .map(parse_allowed_tools)
        .filter(|tools| !tools.is_empty())
        .or_else(|| list_field(&fields, "tools").filter(|tools| !tools.is_empty()))
        .or_else(|| list_field(&fields, "allowed-tools").filter(|tools| !tools.is_empty()))
        .or_else(|| list_field(&fields, "allowed_tools").filter(|tools| !tools.is_empty()))
        .unwrap_or_else(|| vec!["*".to_string()]);
    validate_skill_input(&name, &description, &tools)?;

    let agent_modes = agent_modes_from_frontmatter(&fields);
    let metadata = system_skill_metadata(&fields);
    let canonical_path = match tokio::fs::canonicalize(file_path).await {
        Ok(path) => path,
        Err(_) => file_path.to_path_buf(),
    };
    let license = optional_string_field(&fields, "license");
    let compatibility = optional_string_field(&fields, "compatibility");
    let spec_version = optional_string_field(&fields, "spec_version")
        .or_else(|| optional_string_field(&fields, "spec-version"))
        .unwrap_or_else(|| "1.0".to_string());

    Ok(SkillView {
        id: system_skill_id(&name),
        tenant_id: tenant_id.to_string(),
        project_id: None,
        name,
        description,
        tools,
        full_content: None,
        status: "active".to_string(),
        scope: "system".to_string(),
        is_system_skill: true,
        source: "filesystem".to_string(),
        file_path: Some(canonical_path.to_string_lossy().to_string()),
        created_at: iso8601(now),
        updated_at: iso8601(now),
        metadata: Some(metadata),
        resource_files: json!({}),
        agent_modes,
        license,
        compatibility,
        allowed_tools_raw,
        spec_version,
        current_version: 0,
        version_label: None,
    })
}

fn parse_yaml_frontmatter(frontmatter: &str) -> Result<Map<String, Value>, SkillApiError> {
    match serde_yaml_ng::from_str::<Value>(frontmatter) {
        Ok(Value::Object(fields)) => Ok(fields),
        Ok(_) => Err(SkillApiError::bad_request("Invalid SKILL.md frontmatter")),
        Err(err) => Err(SkillApiError::bad_request(format!(
            "Invalid SKILL.md frontmatter: {err}"
        ))),
    }
}

fn required_string_field(fields: &Map<String, Value>, key: &str) -> Result<String, SkillApiError> {
    optional_string_field(fields, key)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| SkillApiError::bad_request("Invalid SKILL.md frontmatter"))
}

fn optional_string_field(fields: &Map<String, Value>, key: &str) -> Option<String> {
    fields.get(key).and_then(string_from_value)
}

fn string_from_value(value: &Value) -> Option<String> {
    match value {
        Value::String(value) => Some(value.trim().to_string()),
        Value::Number(value) => Some(value.to_string()),
        Value::Bool(value) => Some(value.to_string()),
        _ => None,
    }
    .filter(|value| !value.is_empty())
}

fn list_field(fields: &Map<String, Value>, key: &str) -> Option<Vec<String>> {
    fields.get(key).map(list_from_value)
}

fn list_from_value(value: &Value) -> Vec<String> {
    match value {
        Value::Array(items) => items.iter().filter_map(string_from_value).collect(),
        Value::String(value) => parse_inline_list(value),
        Value::Number(_) | Value::Bool(_) => string_from_value(value).into_iter().collect(),
        _ => Vec::new(),
    }
}

fn bool_field(fields: &Map<String, Value>, key: &str, default: bool) -> bool {
    match fields.get(key) {
        Some(Value::Bool(value)) => *value,
        Some(Value::String(value)) => {
            matches!(value.to_ascii_lowercase().as_str(), "true" | "yes" | "1")
        }
        Some(Value::Number(value)) => value.as_i64().map(|value| value != 0).unwrap_or(default),
        _ => default,
    }
}

fn agent_modes_from_frontmatter(fields: &Map<String, Value>) -> Vec<String> {
    fields
        .get("agent")
        .map(list_from_value)
        .filter(|modes| !modes.is_empty())
        .unwrap_or_else(|| vec!["*".to_string()])
}

fn system_skill_metadata(fields: &Map<String, Value>) -> Value {
    let mut metadata = Map::new();
    metadata.insert(
        "source_type".to_string(),
        Value::String("system".to_string()),
    );
    metadata.insert(
        "context".to_string(),
        Value::String(
            optional_string_field(fields, "context").unwrap_or_else(|| "shared".to_string()),
        ),
    );
    metadata.insert(
        "user_invocable".to_string(),
        Value::Bool(bool_field(fields, "user-invocable", true)),
    );
    if let Some(Value::Object(extra)) = fields.get("metadata") {
        metadata.extend(extra.clone());
    }
    if let Some(Value::Array(servers)) = fields.get("mcp-servers") {
        metadata.insert("mcp_servers".to_string(), Value::Array(servers.clone()));
    }
    Value::Object(metadata)
}

fn system_skill_id(name: &str) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("agistack://system-skill/{name}").as_bytes(),
    )
    .to_string()
}
