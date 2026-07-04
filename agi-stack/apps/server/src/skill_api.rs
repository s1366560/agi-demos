//! P5 skill-store and versioning foundation.
//!
//! This module mirrors the database-backed subset of Python's `/api/v1/skills`
//! router: tenant/project skill CRUD, content updates, version snapshots,
//! rollback/import/export, filesystem-backed system skill listing/package
//! export, zip import, and the skill-evolution strategy config/overview/detail
//! plus apply/reject review job actions. Evolution run admission is available
//! behind a server-only scheduler port; gateway ownership remains Python until
//! the scheduler/evolution-engine semantics are migrated.

use std::collections::{BTreeMap, HashMap};
use std::sync::Mutex;

use async_trait::async_trait;
use axum::{
    extract::{Multipart, Path, Query, State},
    http::StatusCode,
    Extension, Json,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde_json::{json, Map, Value};
use serde_yaml_ng::{Mapping as YamlMapping, Value as YamlValue};

use agistack_adapters_postgres::{
    PgSkillEvolutionRepository, PgSkillRepository, SkillEvolutionJobRecord, SkillProjectAccess,
    SkillRecord, SkillUpdateRecord, SkillVersionRecord,
};
use agistack_adapters_secrets::generate_uuid_v4;

use crate::auth::Identity;
use crate::AppState;

const SKILL_EVOLUTION_PLUGIN: &str = "skill_evolution";

mod dev_service;
mod dev_service_evolution;
mod dev_service_lifecycle;
mod evolution_config;
mod evolution_scheduler;
mod handlers;
mod pg_service;
mod pg_service_evolution;
mod pg_service_helpers;
mod routes;
mod service;
mod system_skills;
mod types;
mod views;
mod zip_import;

pub(crate) use dev_service::DevSkillService;
#[cfg(test)]
use evolution_config::SkillEvolutionPublishMode;
use evolution_config::{
    validate_evolution_detail_limit, validate_overview_limit, SkillEvolutionConfig,
};
use evolution_scheduler::{
    InMemorySkillEvolutionScheduler, SharedSkillEvolutionScheduler, SkillEvolutionScheduleResult,
};
pub(crate) use routes::router;
pub(crate) use service::{SharedSkills, SkillService};
use types::*;
use views::*;

pub(crate) struct PgSkillService {
    repo: PgSkillRepository,
    evolution_repo: Option<PgSkillEvolutionRepository>,
    evolution_scheduler: Option<SharedSkillEvolutionScheduler>,
}

impl PgSkillService {
    pub(crate) fn new(repo: PgSkillRepository) -> Self {
        Self {
            repo,
            evolution_repo: None,
            evolution_scheduler: None,
        }
    }

    pub(crate) fn with_evolution_repo(mut self, repo: PgSkillEvolutionRepository) -> Self {
        self.evolution_repo = Some(repo);
        self
    }
}

fn skill_evolution_plugin_unavailable() -> SkillApiError {
    SkillApiError::new(
        StatusCode::SERVICE_UNAVAILABLE,
        "Skill evolution plugin is not available",
    )
}

fn default_scope() -> String {
    "tenant".to_string()
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn present(value: Option<&str>) -> Option<&str> {
    value.map(str::trim).filter(|value| !value.is_empty())
}

fn tenant_skill_config_error(
    error: crate::tenant_skill_config_api::TenantSkillConfigApiError,
) -> SkillApiError {
    let (status, detail) = error.into_parts();
    SkillApiError::new(status, detail)
}

fn normalize_scope(raw: &str, project_id: Option<&str>) -> Result<String, SkillApiError> {
    let scope = normalize_scope_filter(raw)?;
    if scope == "system" {
        return Err(SkillApiError::bad_request(
            "Cannot create system-level skills via API",
        ));
    }
    if scope == "project" && present(project_id).is_none() {
        return Err(SkillApiError::bad_request(
            "project_id is required for project-scoped skills",
        ));
    }
    Ok(scope)
}

fn normalize_scope_filter(raw: &str) -> Result<String, SkillApiError> {
    match raw {
        "system" | "tenant" | "project" => Ok(raw.to_string()),
        _ => Err(SkillApiError::bad_request("Invalid skill scope")),
    }
}

fn normalize_status(raw: &str) -> Result<String, SkillApiError> {
    match raw {
        "active" | "disabled" | "deprecated" => Ok(raw.to_string()),
        _ => Err(SkillApiError::bad_request("Invalid skill status")),
    }
}

fn validate_skill_input(
    name: &str,
    description: &str,
    tools: &[String],
) -> Result<(), SkillApiError> {
    if !valid_skill_name(name) || description.is_empty() || description.len() > 1024 {
        return Err(SkillApiError::bad_request("Invalid skill request"));
    }
    if tools.is_empty() || tools.iter().any(|tool| tool.trim().is_empty()) {
        return Err(SkillApiError::bad_request("Invalid skill request"));
    }
    Ok(())
}

fn valid_skill_name(name: &str) -> bool {
    if name.is_empty() || name.len() > 64 {
        return false;
    }
    let mut last_dash = true;
    for ch in name.chars() {
        if ch == '-' {
            if last_dash {
                return false;
            }
            last_dash = true;
        } else if ch.is_ascii_lowercase() || ch.is_ascii_digit() {
            last_dash = false;
        } else {
            return false;
        }
    }
    !last_dash
}

fn validate_change_summary(summary: Option<&str>) -> Result<(), SkillApiError> {
    if summary.is_some_and(|summary| summary.chars().count() > 2_000) {
        return Err(SkillApiError::bad_request("Invalid skill request"));
    }
    Ok(())
}

fn import_change_summary(summary: Option<&str>, version_number: i32) -> Option<String> {
    Some(present(summary).map_or_else(|| format!("Version {version_number}"), ToString::to_string))
}

fn resource_files_map(value: Value) -> Result<BTreeMap<String, String>, SkillApiError> {
    let Value::Object(files) = value else {
        return Ok(BTreeMap::new());
    };

    let mut resource_files = BTreeMap::new();
    for (path, content) in files {
        let Value::String(content) = content else {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        };
        resource_files.insert(path, content);
    }
    Ok(resource_files)
}

fn evolution_job_scope(job: &SkillEvolutionJobRecord) -> &'static str {
    if job.project_id.is_some() {
        "project"
    } else {
        "tenant"
    }
}

fn evolution_change_summary(job: &SkillEvolutionJobRecord, action: &str) -> Option<String> {
    Some(
        job.rationale
            .as_deref()
            .filter(|rationale| !rationale.is_empty())
            .map_or_else(|| format!("Evolution {action}"), ToString::to_string),
    )
}

fn replace_frontmatter_description(content: &str, description: &str) -> String {
    let Some(rest) = content.strip_prefix("---\n") else {
        return if content.is_empty() {
            description.to_string()
        } else {
            content.to_string()
        };
    };
    let Some((frontmatter, body)) = rest.split_once("\n---") else {
        return if content.is_empty() {
            description.to_string()
        } else {
            content.to_string()
        };
    };
    let Ok(value) = serde_yaml_ng::from_str::<YamlValue>(frontmatter.trim()) else {
        return content.to_string();
    };
    let mut map = match value {
        YamlValue::Mapping(map) => map,
        YamlValue::Null => YamlMapping::new(),
        _ => return content.to_string(),
    };
    map.insert(
        YamlValue::String("description".to_string()),
        YamlValue::String(description.to_string()),
    );
    let value = YamlValue::Mapping(map);
    let Ok(yaml_text) = serde_yaml_ng::to_string(&value) else {
        return content.to_string();
    };
    format!("---\n{}\n---{}", yaml_text.trim(), body)
}

#[derive(Default)]
struct ParsedSkillPayload {
    name: Option<String>,
    description: Option<String>,
    tools: Option<Vec<String>>,
    metadata: Option<Value>,
    license: Option<String>,
    compatibility: Option<String>,
    allowed_tools_raw: Option<String>,
    spec_version: Option<String>,
    version_label: Option<String>,
}

impl ParsedSkillPayload {
    fn from_content(content: Option<&str>) -> Self {
        let Some(content) = content else {
            return Self::default();
        };
        let Some(frontmatter) = frontmatter(content) else {
            return Self::default();
        };
        let mut parsed = Self::default();
        let mut metadata = Map::new();
        for line in frontmatter.lines() {
            let Some((key, value)) = line.split_once(':') else {
                continue;
            };
            let key = key.trim();
            let value = value.trim().trim_matches('"').trim_matches('\'');
            if value.is_empty() {
                continue;
            }
            match key {
                "name" => parsed.name = Some(value.to_string()),
                "description" => parsed.description = Some(value.to_string()),
                "version" => parsed.version_label = Some(value.to_string()),
                "license" => {
                    parsed.license = Some(value.to_string());
                    metadata.insert(key.to_string(), Value::String(value.to_string()));
                }
                "compatibility" => {
                    parsed.compatibility = Some(value.to_string());
                    metadata.insert(key.to_string(), Value::String(value.to_string()));
                }
                "allowed_tools" | "allowed-tools" => {
                    parsed.allowed_tools_raw = Some(value.to_string());
                    if parsed.tools.is_none() {
                        let tools = parse_allowed_tools(value);
                        if !tools.is_empty() {
                            parsed.tools = Some(tools);
                        }
                    }
                    metadata.insert(
                        "allowed_tools".to_string(),
                        Value::String(value.to_string()),
                    );
                }
                "spec_version" | "spec-version" => {
                    parsed.spec_version = Some(value.to_string());
                    metadata.insert("spec_version".to_string(), Value::String(value.to_string()));
                }
                "tools" => {
                    let tools = parse_inline_list(value);
                    if !tools.is_empty() {
                        parsed.tools = Some(tools);
                    }
                }
                _ => {}
            }
        }
        if !metadata.is_empty() {
            parsed.metadata = Some(Value::Object(Map::from_iter([(
                "agentskills".to_string(),
                Value::Object(metadata),
            )])));
        }
        parsed
    }
}

struct ParsedImportPackage {
    name: String,
    description: String,
    tools: Vec<String>,
    metadata: Option<Value>,
    license: Option<String>,
    compatibility: Option<String>,
    allowed_tools_raw: Option<String>,
    spec_version: String,
    version_label: Option<String>,
}

impl ParsedImportPackage {
    fn from_payload(body: &SkillImportPayload) -> Result<Self, SkillApiError> {
        if body.skill_md_content.trim().is_empty() {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        }
        let parsed = ParsedSkillPayload::from_content(Some(&body.skill_md_content));
        let Some(name) = parsed.name else {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        };
        let Some(description) = parsed.description else {
            return Err(SkillApiError::bad_request("Invalid Agent Skill package"));
        };
        let tools = parsed.tools.unwrap_or_else(|| vec!["*".to_string()]);
        validate_skill_input(&name, &description, &tools)
            .map_err(|_| SkillApiError::bad_request("Invalid Agent Skill package"))?;
        let declared_spec_version = parsed.spec_version.clone();
        let spec_version = declared_spec_version
            .clone()
            .unwrap_or_else(|| "1.0".to_string());
        let metadata = merge_agentskills_metadata(
            parsed.metadata,
            parsed.license.as_deref(),
            parsed.compatibility.as_deref(),
            parsed.allowed_tools_raw.as_deref(),
            declared_spec_version.as_deref(),
        );
        Ok(Self {
            name,
            description,
            tools,
            metadata,
            license: parsed.license,
            compatibility: parsed.compatibility,
            allowed_tools_raw: parsed.allowed_tools_raw,
            spec_version,
            version_label: parsed.version_label,
        })
    }
}

fn frontmatter(content: &str) -> Option<&str> {
    let rest = content.strip_prefix("---\n")?;
    rest.split_once("\n---").map(|(frontmatter, _)| frontmatter)
}

fn parse_inline_list(value: &str) -> Vec<String> {
    let value = value.trim();
    let value = value
        .strip_prefix('[')
        .and_then(|inner| inner.strip_suffix(']'))
        .unwrap_or(value);
    value
        .split(',')
        .map(|item| item.trim().trim_matches('"').trim_matches('\''))
        .filter(|item| !item.is_empty())
        .map(ToString::to_string)
        .collect()
}

fn parse_allowed_tools(value: &str) -> Vec<String> {
    let raw_items = if value.contains(',') || value.trim_start().starts_with('[') {
        parse_inline_list(value)
    } else {
        value
            .split_whitespace()
            .map(|item| item.trim().trim_matches('"').trim_matches('\'').to_string())
            .collect()
    };
    raw_items
        .into_iter()
        .filter_map(|item| {
            let name = item
                .split_once('(')
                .map(|(name, _)| name)
                .unwrap_or(item.as_str())
                .trim();
            if name.is_empty() {
                None
            } else {
                Some(name.to_string())
            }
        })
        .collect()
}

fn merge_agentskills_metadata(
    metadata: Option<Value>,
    license: Option<&str>,
    compatibility: Option<&str>,
    allowed_tools_raw: Option<&str>,
    spec_version: Option<&str>,
) -> Option<Value> {
    let mut root = match metadata {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    let mut agentskills = match root.remove("agentskills") {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    for (key, value) in [
        ("license", license),
        ("compatibility", compatibility),
        ("allowed_tools", allowed_tools_raw),
        ("spec_version", spec_version),
    ] {
        if let Some(value) = value.filter(|value| !value.is_empty()) {
            agentskills.insert(key.to_string(), Value::String(value.to_string()));
        }
    }
    if !agentskills.is_empty() {
        root.insert("agentskills".to_string(), Value::Object(agentskills));
    }
    if root.is_empty() {
        None
    } else {
        Some(Value::Object(root))
    }
}

fn skill_matches_search(record: &SkillRecord, needle: &str) -> bool {
    if needle.is_empty() {
        return true;
    }
    let metadata = record
        .metadata_json
        .as_ref()
        .map(Value::to_string)
        .unwrap_or_default();
    [
        record.name.as_str(),
        record.description.as_str(),
        record.version_label.as_deref().unwrap_or_default(),
        metadata.as_str(),
    ]
    .iter()
    .any(|part| part.to_ascii_lowercase().contains(needle))
}

fn skill_package_view(skill: SkillRecord, version: Option<SkillVersionRecord>) -> SkillPackageView {
    let skill_view = SkillView::from(skill.clone());
    let (skill_md_content, resource_files, version_number, version_label) = match version {
        Some(version) => (
            version.skill_md_content,
            version.resource_files,
            Some(version.version_number),
            version.version_label,
        ),
        None => (
            skill
                .full_content
                .clone()
                .unwrap_or_else(|| build_skill_md_from_record(&skill)),
            skill.resource_files.clone(),
            None,
            skill.version_label.clone(),
        ),
    };
    SkillPackageView {
        format: "agentskills.io/skill-package".to_string(),
        skill: skill_view,
        skill_md_content,
        resource_files,
        version_number,
        version_label,
    }
}

fn build_skill_md_from_record(record: &SkillRecord) -> String {
    let mut frontmatter = YamlMapping::new();
    insert_yaml_string(&mut frontmatter, "name", &record.name);
    insert_yaml_string(&mut frontmatter, "description", &record.description);
    if let Some(value) = record.license.as_deref().filter(|value| !value.is_empty()) {
        insert_yaml_string(&mut frontmatter, "license", value);
    }
    if let Some(value) = record
        .compatibility
        .as_deref()
        .filter(|value| !value.is_empty())
    {
        insert_yaml_string(&mut frontmatter, "compatibility", value);
    }
    if let Some(value) = record
        .allowed_tools_raw
        .as_deref()
        .filter(|value| !value.is_empty())
    {
        insert_yaml_string(&mut frontmatter, "allowed-tools", value);
    } else if !record.tools.is_empty() {
        insert_yaml_string(&mut frontmatter, "allowed-tools", &record.tools.join(" "));
    }
    if let Some(metadata) = export_metadata_value(record) {
        frontmatter.insert(YamlValue::String("metadata".to_string()), metadata);
    }
    let body = format!("# {}\n\n{}", record.name, record.description);
    let yaml_text =
        serde_yaml_ng::to_string(&frontmatter).unwrap_or_else(|_| fallback_frontmatter(record));
    format!("---\n{}\n---\n\n{}\n", yaml_text.trim_end(), body.trim())
}

fn insert_yaml_string(map: &mut YamlMapping, key: &str, value: &str) {
    map.insert(
        YamlValue::String(key.to_string()),
        YamlValue::String(value.to_string()),
    );
}

fn export_metadata_value(record: &SkillRecord) -> Option<YamlValue> {
    let mut metadata = match record.metadata_json.clone() {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    if let Some(version_label) = record
        .version_label
        .as_deref()
        .filter(|version_label| !version_label.is_empty())
    {
        metadata
            .entry("version".to_string())
            .or_insert_with(|| Value::String(version_label.to_string()));
    }
    if metadata.is_empty() {
        return None;
    }
    serde_yaml_ng::to_value(Value::Object(metadata)).ok()
}

fn fallback_frontmatter(record: &SkillRecord) -> String {
    format!("name: {}\ndescription: {}", record.name, record.description)
}

#[cfg(test)]
mod tests;
