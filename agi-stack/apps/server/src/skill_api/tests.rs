use super::*;
use std::io::{Cursor, Write};

use axum::Router;
use zip::write::SimpleFileOptions;

const SAMPLE_IMPORT_SKILL_MD: &str = r#"---
name: alpha-skill
description: Searches, installs, and exports agent skills.
allowed-tools: Bash(git:*) Read
metadata:
  version: "1.2.3"
  author: test-suite
---

# Alpha Skill

Use when managing Agent Skills packages.
"#;

fn zip_package(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut writer = zip::ZipWriter::new(Cursor::new(Vec::new()));
    let options = SimpleFileOptions::default().compression_method(zip::CompressionMethod::Deflated);
    for (path, content) in entries {
        writer.start_file(*path, options).unwrap();
        writer.write_all(content).unwrap();
    }
    writer.finish().unwrap().into_inner()
}

fn sample_skill_record() -> SkillRecord {
    let at = DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap();
    SkillRecord {
        id: "11111111-1111-4111-8111-111111111111".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: None,
        name: "code-review".to_string(),
        description: "Review code changes".to_string(),
        tools: vec!["read_file".to_string(), "grep".to_string()],
        status: "active".to_string(),
        metadata_json: Some(json!({"agentskills":{"license":"MIT"}})),
        created_at: at,
        updated_at: Some(at),
        scope: "tenant".to_string(),
        is_system_skill: false,
        full_content: Some("# Code Review\n".to_string()),
        resource_files: json!({}),
        license: Some("MIT".to_string()),
        compatibility: None,
        allowed_tools_raw: Some("read_file,grep".to_string()),
        spec_version: "1.0".to_string(),
        current_version: 2,
        version_label: Some("1.2.0".to_string()),
    }
}

fn sample_version_record() -> SkillVersionRecord {
    let at = DateTime::<Utc>::from_timestamp(1_700_000_100, 0).unwrap();
    SkillVersionRecord {
        id: "22222222-2222-4222-8222-222222222222".to_string(),
        skill_id: "11111111-1111-4111-8111-111111111111".to_string(),
        version_number: 2,
        version_label: Some("1.2.0".to_string()),
        skill_md_content: "# Code Review\n".to_string(),
        resource_files: json!({"rules.md":"Focus on regressions."}),
        change_summary: Some("Manual content update".to_string()),
        created_by: "agent".to_string(),
        created_at: at,
    }
}

fn sample_evolution_job_record() -> SkillEvolutionJobRecord {
    SkillEvolutionJobRecord {
        id: "job-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: None,
        skill_name: "code-review".to_string(),
        action: "update".to_string(),
        status: "pending_review".to_string(),
        rationale: Some("Improve review checklist.".to_string()),
        candidate_content: Some("Updated skill content".to_string()),
        session_ids: vec!["sess-1".to_string(), "sess-2".to_string()],
        skill_version_id: None,
        created_at: DateTime::<Utc>::from_timestamp(1_700_000_400, 0).unwrap(),
        applied_at: None,
    }
}

fn sample_imported_skill_record() -> SkillRecord {
    let mut record = sample_skill_record();
    record.name = "alpha-skill".to_string();
    record.description = "Searches, installs, and exports agent skills.".to_string();
    record.tools = vec!["Bash".to_string(), "Read".to_string()];
    record.full_content = Some(SAMPLE_IMPORT_SKILL_MD.to_string());
    record.resource_files = json!({"references/README.md":"details"});
    record.metadata_json = Some(json!({"agentskills":{"allowed_tools":"Bash(git:*) Read"}}));
    record.license = None;
    record.compatibility = None;
    record.allowed_tools_raw = Some("Bash(git:*) Read".to_string());
    record.current_version = 1;
    record.version_label = Some("1.2.3".to_string());
    record
}

mod dev_service;
mod goldens;
mod zip_import;

#[test]
fn router_builds() {
    let _router: Router<AppState> = router();
}
