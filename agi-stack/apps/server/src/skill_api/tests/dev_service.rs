use super::*;

#[tokio::test]
async fn dev_service_exports_filesystem_system_skill_packages() {
    let service = DevSkillService::new("tenant-1");

    let by_name = service
        .export_package("u1", Some("tenant-1"), "code-review")
        .await
        .unwrap();
    let by_id = service
        .export_package(
            "u1",
            Some("tenant-1"),
            "f012eae7-dcfd-541a-8547-7f938a832fd0",
        )
        .await
        .unwrap();

    assert_eq!(by_name.skill.name, "code-review");
    assert_eq!(by_name.skill.scope, "system");
    assert!(by_name.skill.is_system_skill);
    assert_eq!(by_name.version_number, None);
    assert_eq!(by_name.resource_files, json!({}));
    assert_eq!(by_id.skill.name, by_name.skill.name);
}

#[tokio::test]
async fn dev_service_imports_filesystem_system_skill_as_managed_skill() {
    // Arrange
    let service = DevSkillService::new("tenant-1");
    let payload = SystemSkillImportPayload {
        name: Some("code-review".to_string()),
        scope: "tenant".to_string(),
        ..Default::default()
    };

    // Act
    let imported = service
        .import_system_skill("u1", Some("tenant-1"), payload.clone())
        .await
        .unwrap();
    let repeated = service
        .import_system_skill("u1", Some("tenant-1"), payload)
        .await
        .unwrap_err();
    let versions = service
        .list_versions("u1", Some("tenant-1"), &imported.skill.id, 50, 0)
        .await
        .unwrap();

    // Assert
    assert_eq!(imported.action, "import");
    assert_eq!(imported.skill.name, "code-review");
    assert_eq!(imported.skill.scope, "tenant");
    assert!(!imported.skill.is_system_skill);
    assert_eq!(imported.skill.source, "database");
    assert_eq!(imported.skill.file_path, None);
    assert_eq!(imported.skill.current_version, 1);
    assert_eq!(versions.total, 1);
    assert_eq!(versions.versions[0].created_by, "import");
    assert_eq!(repeated.status, StatusCode::CONFLICT);
    assert_eq!(repeated.detail, "Skill already exists");

    let actual = serde_json::to_value(imported).unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_system_import_lifecycle.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn dev_service_applies_and_rejects_evolution_jobs() {
    // Arrange
    let service = DevSkillService::new("tenant-1");
    let created = service
        .create_skill(
            "u1",
            Some("tenant-1"),
            SkillCreatePayload {
                name: "code-review".to_string(),
                description: "Review code".to_string(),
                tools: vec!["read_file".to_string()],
                full_content: Some("# Code Review\n".to_string()),
                project_id: None,
                scope: "tenant".to_string(),
                metadata: None,
                license: None,
                compatibility: None,
                allowed_tools_raw: None,
                spec_version: None,
            },
        )
        .await
        .unwrap();
    let now = DateTime::<Utc>::from_timestamp(1_700_000_400, 0).unwrap();
    service.evolution_jobs.lock().unwrap().insert(
        "job-apply".to_string(),
        SkillEvolutionJobRecord {
            id: "job-apply".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: None,
            skill_name: "code-review".to_string(),
            action: "improve_skill".to_string(),
            status: "pending_review".to_string(),
            rationale: Some("Improve review checklist.".to_string()),
            candidate_content: Some("# Updated Code Review\n".to_string()),
            session_ids: vec!["sess-1".to_string()],
            skill_version_id: None,
            created_at: now,
            applied_at: None,
        },
    );
    service.evolution_jobs.lock().unwrap().insert(
        "job-reject".to_string(),
        SkillEvolutionJobRecord {
            id: "job-reject".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: None,
            skill_name: "code-review".to_string(),
            action: "improve_skill".to_string(),
            status: "pending_review".to_string(),
            rationale: None,
            candidate_content: Some("# Rejected\n".to_string()),
            session_ids: vec!["sess-2".to_string()],
            skill_version_id: None,
            created_at: now,
            applied_at: None,
        },
    );
    service.evolution_jobs.lock().unwrap().insert(
        "job-unsupported".to_string(),
        SkillEvolutionJobRecord {
            id: "job-unsupported".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: None,
            skill_name: "code-review".to_string(),
            action: "unsupported_action".to_string(),
            status: "pending_review".to_string(),
            rationale: None,
            candidate_content: Some("# Unsupported\n".to_string()),
            session_ids: vec!["sess-3".to_string()],
            skill_version_id: None,
            created_at: now,
            applied_at: None,
        },
    );

    // Act
    let applied = service
        .apply_evolution_job("u1", Some("tenant-1"), "job-apply")
        .await
        .unwrap();
    let rejected = service
        .reject_evolution_job("u1", Some("tenant-1"), "job-reject")
        .await
        .unwrap();
    let repeated_apply = service
        .apply_evolution_job("u1", Some("tenant-1"), "job-apply")
        .await
        .unwrap_err();
    let repeated_reject = service
        .reject_evolution_job("u1", Some("tenant-1"), "job-reject")
        .await
        .unwrap_err();
    let unsupported_apply = service
        .apply_evolution_job("u1", Some("tenant-1"), "job-unsupported")
        .await
        .unwrap_err();

    // Assert
    assert_eq!(applied.status, "applied");
    assert!(!applied.blocked_by_review);
    assert!(applied.skill_version_id.is_some());
    assert!(applied.applied_at.is_some());
    assert_eq!(rejected.status, "rejected");
    assert!(!rejected.blocked_by_review);
    assert_eq!(rejected.skill_version_id, None);
    assert_eq!(repeated_apply.status, StatusCode::BAD_REQUEST);
    assert_eq!(
        repeated_apply.detail,
        "Skill evolution job is not pending review"
    );
    assert_eq!(repeated_reject.status, StatusCode::BAD_REQUEST);
    assert_eq!(
        repeated_reject.detail,
        "Skill evolution job is not pending review"
    );
    assert_eq!(unsupported_apply.status, StatusCode::BAD_REQUEST);
    assert_eq!(
        unsupported_apply.detail,
        "Skill evolution job cannot be applied"
    );
    let content = service
        .get_content("u1", Some("tenant-1"), &created.id)
        .await
        .unwrap();
    assert_eq!(
        content.full_content.as_deref(),
        Some("# Updated Code Review\n")
    );
    let versions = service
        .list_versions("u1", Some("tenant-1"), &created.id, 50, 0)
        .await
        .unwrap();
    assert_eq!(versions.total, 1);
    assert_eq!(versions.versions[0].created_by, "evolution");
}

#[tokio::test]
async fn dev_service_content_update_creates_version_and_rollback() {
    let service = DevSkillService::new("tenant-1");
    let created = service
        .create_skill(
            "u1",
            Some("tenant-1"),
            SkillCreatePayload {
                name: "code-review".to_string(),
                description: "Review code".to_string(),
                tools: vec!["read_file".to_string()],
                full_content: Some("# Code Review\n".to_string()),
                project_id: None,
                scope: "tenant".to_string(),
                metadata: None,
                license: None,
                compatibility: None,
                allowed_tools_raw: None,
                spec_version: None,
            },
        )
        .await
        .unwrap();
    assert_eq!(created.current_version, 0);

    let updated = service
        .update_content(
            "u1",
            Some("tenant-1"),
            &created.id,
            SkillContentUpdatePayload {
                full_content: "---\nversion: 1.0.0\n---\n# New\n".to_string(),
            },
        )
        .await
        .unwrap();
    assert_eq!(updated.current_version, 1);
    assert_eq!(updated.version_label.as_deref(), Some("1.0.0"));
    let exported = service
        .export_package("u1", Some("tenant-1"), &created.id)
        .await
        .unwrap();
    assert_eq!(exported.version_number, Some(1));
    assert_eq!(
        Some(exported.skill_md_content.as_str()),
        updated.full_content.as_deref()
    );
    let versions = service
        .list_versions("u1", Some("tenant-1"), &created.id, 50, 0)
        .await
        .unwrap();
    assert_eq!(versions.total, 1);

    let rolled_back = service
        .rollback(
            "u1",
            Some("tenant-1"),
            &created.id,
            SkillRollbackPayload { version_number: 1 },
        )
        .await
        .unwrap();
    assert_eq!(rolled_back.current_version, 2);
    assert_eq!(rolled_back.full_content, updated.full_content);
}

#[tokio::test]
async fn dev_service_evolution_detail_returns_versions_and_skill_trigger() {
    // Arrange
    let service = DevSkillService::new("tenant-1");
    let created = service
        .create_skill(
            "u1",
            Some("tenant-1"),
            SkillCreatePayload {
                name: "code-review".to_string(),
                description: "Review code".to_string(),
                tools: vec!["read_file".to_string()],
                full_content: Some("# Code Review\n".to_string()),
                project_id: None,
                scope: "tenant".to_string(),
                metadata: None,
                license: None,
                compatibility: None,
                allowed_tools_raw: None,
                spec_version: None,
            },
        )
        .await
        .unwrap();
    service
        .update_content(
            "u1",
            Some("tenant-1"),
            &created.id,
            SkillContentUpdatePayload {
                full_content: "---\nversion: 1.0.0\n---\n# New\n".to_string(),
            },
        )
        .await
        .unwrap();

    // Act
    let detail = service
        .get_evolution_detail(
            "u1",
            SkillEvolutionDetailQuery {
                tenant_id: Some("tenant-1".to_string()),
                limit: Some(20),
            },
            &created.id,
        )
        .await
        .unwrap();

    // Assert
    assert_eq!(detail.skill_id, created.id);
    assert_eq!(detail.skill_name, "code-review");
    assert_eq!(detail.captured_session_count, 0);
    assert!(detail.jobs.is_empty());
    assert_eq!(detail.route.len(), 1);
    assert_eq!(detail.route[0].kind, "version");
    assert_eq!(detail.route[0].version_number, Some(1));
    assert_eq!(
        detail.trigger.manual_trigger,
        format!("/api/v1/skills/{}/evolution/run", created.id)
    );
}

#[tokio::test]
async fn dev_service_import_package_creates_version_and_honors_overwrite() {
    let service = DevSkillService::new("tenant-1");
    let resource_files =
        BTreeMap::from([("references/README.md".to_string(), "details".to_string())]);

    let imported = service
        .import_package(
            "u1",
            Some("tenant-1"),
            SkillImportPayload {
                skill_md_content: SAMPLE_IMPORT_SKILL_MD.to_string(),
                resource_files: resource_files.clone(),
                scope: "tenant".to_string(),
                project_id: None,
                overwrite: false,
                change_summary: None,
            },
        )
        .await
        .unwrap();

    assert_eq!(imported.action, "import");
    assert_eq!(imported.skill.name, "alpha-skill");
    assert_eq!(imported.skill.tools, vec!["Bash", "Read"]);
    assert_eq!(imported.skill.current_version, 1);
    assert_eq!(imported.version_number, Some(1));
    assert_eq!(imported.version_label.as_deref(), Some("1.2.3"));

    let duplicate = service
        .import_package(
            "u1",
            Some("tenant-1"),
            SkillImportPayload {
                skill_md_content: SAMPLE_IMPORT_SKILL_MD.to_string(),
                resource_files: resource_files.clone(),
                scope: "tenant".to_string(),
                project_id: None,
                overwrite: false,
                change_summary: None,
            },
        )
        .await;
    assert!(matches!(
        duplicate,
        Err(SkillApiError {
            status: StatusCode::CONFLICT,
            ..
        })
    ));

    let updated = service
        .import_package(
            "u1",
            Some("tenant-1"),
            SkillImportPayload {
                skill_md_content: SAMPLE_IMPORT_SKILL_MD.to_string(),
                resource_files,
                scope: "tenant".to_string(),
                project_id: None,
                overwrite: true,
                change_summary: Some("Re-import package".to_string()),
            },
        )
        .await
        .unwrap();
    assert_eq!(updated.action, "update");
    assert_eq!(updated.skill.current_version, 2);

    let versions = service
        .list_versions("u1", Some("tenant-1"), &updated.skill.id, 50, 0)
        .await
        .unwrap();
    assert_eq!(versions.total, 2);
    let exported = service
        .export_package("u1", Some("tenant-1"), &updated.skill.id)
        .await
        .unwrap();
    assert_eq!(exported.version_number, Some(2));
    assert_eq!(
        exported.resource_files,
        json!({"references/README.md":"details"})
    );
}

#[tokio::test]
async fn dev_service_evolution_config_roundtrips() {
    let service = DevSkillService::new("tenant-1");
    let updated = service
        .update_evolution_config(
            "u1",
            Some("tenant-1"),
            SkillEvolutionConfigUpdatePayload {
                enabled: Some(false),
                min_sessions_per_skill: Some(7),
                scoring_min_sessions_per_skill: Some(8),
                min_avg_score: Some(0.75),
                max_sessions_per_batch: Some(25),
                evolution_interval_minutes: Some(120),
                publish_mode: Some("direct".to_string()),
                auto_apply: Some(true),
            },
        )
        .await
        .unwrap();

    assert!(!updated.enabled);
    assert_eq!(updated.publish_mode, "direct");
    assert_eq!(updated.evolution_interval_minutes, 120);

    let fetched = service
        .get_evolution_config("u1", Some("tenant-1"))
        .await
        .unwrap();
    assert_eq!(fetched.publish_mode, "direct");
    assert_eq!(fetched.min_sessions_per_skill, 7);
}

#[tokio::test]
async fn dev_service_evolution_config_rejects_invalid_publish_mode() {
    let service = DevSkillService::new("tenant-1");
    let err = service
        .update_evolution_config(
            "u1",
            Some("tenant-1"),
            SkillEvolutionConfigUpdatePayload {
                publish_mode: Some("invalid".to_string()),
                ..Default::default()
            },
        )
        .await
        .expect_err("invalid publish mode should fail");

    assert_eq!(err.status, StatusCode::BAD_REQUEST);
    assert_eq!(err.detail, "Invalid skill evolution publish mode");
}

#[tokio::test]
async fn dev_service_evolution_run_admits_tenant_and_skill_once() {
    // Arrange
    let service = DevSkillService::new("tenant-1");
    let created = service
        .create_skill(
            "u1",
            Some("tenant-1"),
            SkillCreatePayload {
                name: "code-review".to_string(),
                description: "Review code".to_string(),
                tools: vec!["read_file".to_string()],
                full_content: Some("# Code Review\n".to_string()),
                project_id: None,
                scope: "tenant".to_string(),
                metadata: None,
                license: None,
                compatibility: None,
                allowed_tools_raw: None,
                spec_version: None,
            },
        )
        .await
        .unwrap();

    // Act
    let tenant_first = service
        .run_tenant_evolution("u1", Some("tenant-1"))
        .await
        .unwrap();
    let tenant_second = service
        .run_tenant_evolution("u1", Some("tenant-1"))
        .await
        .unwrap();
    let skill_first = service
        .run_skill_evolution("u1", Some("tenant-1"), &created.id)
        .await
        .unwrap();
    let skill_second = service
        .run_skill_evolution("u1", Some("tenant-1"), &created.id)
        .await
        .unwrap();

    // Assert
    assert_eq!(tenant_first.tenant_id, "tenant-1");
    assert!(tenant_first.result.scheduled);
    assert_eq!(tenant_first.result.reason, "manual");
    assert_eq!(tenant_first.result.status, "queued");
    assert!(!tenant_second.result.scheduled);
    assert_eq!(
        tenant_second.result.status,
        "already_scheduled_or_not_running"
    );
    assert_eq!(skill_first.skill_id, created.id);
    assert_eq!(skill_first.skill_name, "code-review");
    assert!(skill_first.result.scheduled);
    assert!(!skill_second.result.scheduled);
}

#[tokio::test]
async fn dev_service_evolution_run_rejects_system_skill() {
    // Arrange
    let service = DevSkillService::new("tenant-1");
    let mut system_skill = sample_skill_record();
    system_skill.id = "system-skill-1".to_string();
    system_skill.scope = "system".to_string();
    system_skill.is_system_skill = true;
    service
        .skills
        .lock()
        .unwrap()
        .insert(system_skill.id.clone(), system_skill);

    // Act
    let err = service
        .run_skill_evolution("u1", Some("tenant-1"), "system-skill-1")
        .await
        .expect_err("system skill evolution run should be rejected");

    // Assert
    assert_eq!(err.status, StatusCode::BAD_REQUEST);
    assert_eq!(
        err.detail,
        "Skill evolution is only available for managed skills"
    );
}
