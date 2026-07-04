use super::*;
use std::collections::HashSet;
use std::path::Path as FsPath;

#[test]
fn skill_response_matches_golden() {
    let actual = serde_json::to_value(SkillView::from(sample_skill_record())).unwrap();
    let golden: Value =
        serde_json::from_str(include_str!("../../../tests/golden/skill_response.json")).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn skill_list_matches_golden() {
    let actual = serde_json::to_value(SkillListView {
        skills: vec![SkillView::from(sample_skill_record())],
        total: 1,
    })
    .unwrap();
    let golden: Value =
        serde_json::from_str(include_str!("../../../tests/golden/skill_list.json")).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn system_skill_list_matches_golden() {
    let at = DateTime::<Utc>::from_timestamp(1_700_000_000, 0).unwrap();
    let skills = vec![
        system_skills::system_skill_view_from_content(
            "tenant-1",
            FsPath::new("/repo/src/builtin/skills/code-review/SKILL.md"),
            include_str!("../../../../../../src/builtin/skills/code-review/SKILL.md"),
            at,
        )
        .await
        .unwrap(),
        system_skills::system_skill_view_from_content(
            "tenant-1",
            FsPath::new("/repo/src/builtin/skills/memory-capture-extraction/SKILL.md"),
            include_str!("../../../../../../src/builtin/skills/memory-capture-extraction/SKILL.md"),
            at,
        )
        .await
        .unwrap(),
        system_skills::system_skill_view_from_content(
            "tenant-1",
            FsPath::new("/repo/src/builtin/skills/memory-flush-extraction/SKILL.md"),
            include_str!("../../../../../../src/builtin/skills/memory-flush-extraction/SKILL.md"),
            at,
        )
        .await
        .unwrap(),
    ];
    let actual = serde_json::to_value(SkillListView { skills, total: 3 }).unwrap();
    let golden: Value =
        serde_json::from_str(include_str!("../../../tests/golden/skill_system_list.json")).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn filesystem_system_skill_list_filters_non_active_statuses() {
    let view = system_skills::list_filesystem_system_skills("tenant-1", Some("disabled"))
        .await
        .unwrap();
    assert!(view.skills.is_empty());
    assert_eq!(view.total, 0);
}

#[test]
fn disabled_system_skill_filter_updates_total() {
    let mut view = SkillListView {
        skills: vec![
            SkillView::from(sample_skill_record()),
            SkillView {
                name: "memory-capture-extraction".to_string(),
                ..SkillView::from(sample_skill_record())
            },
        ],
        total: 2,
    };
    let disabled_names = HashSet::from(["memory-capture-extraction".to_string()]);
    filter_disabled_system_skills(&mut view, &disabled_names);
    assert_eq!(view.total, 1);
    assert_eq!(view.skills[0].name, "code-review");
}

#[test]
fn skill_content_matches_golden() {
    let actual = serde_json::to_value(SkillContentView {
        skill_id: "11111111-1111-4111-8111-111111111111".to_string(),
        name: "code-review".to_string(),
        full_content: Some("# Code Review\n".to_string()),
        scope: "tenant".to_string(),
        is_system_skill: false,
    })
    .unwrap();
    let golden: Value =
        serde_json::from_str(include_str!("../../../tests/golden/skill_content.json")).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn skill_version_shapes_match_goldens() {
    let actual = serde_json::to_value(SkillVersionView::from(sample_version_record())).unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_version_response.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);

    let actual =
        serde_json::to_value(SkillVersionDetailView::from(sample_version_record())).unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_version_detail.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn skill_package_export_matches_golden() {
    let actual = serde_json::to_value(skill_package_view(
        sample_skill_record(),
        Some(sample_version_record()),
    ))
    .unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_package_export.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn system_skill_package_export_matches_golden() {
    let package = system_skills::export_filesystem_system_skill("tenant-1", "code-review")
        .await
        .unwrap()
        .unwrap();
    let actual = serde_json::to_value(package).unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_system_package_export.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn skill_import_lifecycle_matches_golden() {
    let actual = serde_json::to_value(SkillLifecycleView {
        action: "import".to_string(),
        skill: SkillView::from(sample_imported_skill_record()),
        version_number: Some(1),
        version_label: Some("1.2.3".to_string()),
    })
    .unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_import_lifecycle.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn skill_evolution_config_shapes_match_goldens() {
    let default_actual =
        serde_json::to_value(SkillEvolutionConfigView::from(SkillEvolutionConfig {
            enabled: true,
            min_sessions_per_skill: 5,
            scoring_min_sessions_per_skill: 5,
            min_avg_score: 0.6,
            max_sessions_per_batch: 50,
            evolution_interval_minutes: 60,
            publish_mode: SkillEvolutionPublishMode::Review,
            auto_apply: false,
        }))
        .unwrap();
    let default_golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_evolution_config.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&default_golden, &default_actual);

    let updated_actual =
        serde_json::to_value(SkillEvolutionConfigView::from(SkillEvolutionConfig {
            enabled: false,
            min_sessions_per_skill: 7,
            scoring_min_sessions_per_skill: 8,
            min_avg_score: 0.75,
            max_sessions_per_batch: 25,
            evolution_interval_minutes: 120,
            publish_mode: SkillEvolutionPublishMode::Direct,
            auto_apply: true,
        }))
        .unwrap();
    let updated_golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_evolution_config_updated.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&updated_golden, &updated_actual);
}

#[test]
fn skill_evolution_overview_matches_golden() {
    let config = SkillEvolutionConfig {
        enabled: true,
        min_sessions_per_skill: 2,
        scoring_min_sessions_per_skill: 2,
        min_avg_score: 0.7,
        max_sessions_per_batch: 10,
        evolution_interval_minutes: 30,
        publish_mode: SkillEvolutionPublishMode::Review,
        auto_apply: false,
    };
    let stats = SkillEvolutionOverviewStatsRecord {
        total_sessions: 3,
        skill_sessions: 2,
        no_skill_sessions: 1,
        unprocessed_sessions: 1,
        processed_sessions: 1,
        scored_sessions: 1,
        successful_sessions: 1,
        avg_score: Some(0.8),
        total_jobs: 2,
        pending_jobs: 1,
        applied_jobs: 1,
        skipped_jobs: 0,
        rejected_jobs: 0,
    };
    let skill_summaries = vec![SkillEvolutionSkillSummaryRecord {
        skill_id: Some("11111111-1111-4111-8111-111111111111".to_string()),
        project_id: None,
        skill_name: "code-review".to_string(),
        session_count: 2,
        success_count: 1,
        unprocessed_count: 1,
        scored_count: 1,
        avg_score: Some(0.8),
        latest_session_at: Some(DateTime::<Utc>::from_timestamp(1_700_000_300, 0).unwrap()),
        job_count: 2,
        pending_job_count: 1,
        latest_job_at: Some(DateTime::<Utc>::from_timestamp(1_700_000_400, 0).unwrap()),
    }];
    let recent_sessions = vec![SkillEvolutionSessionRecord {
        id: "sess-1".to_string(),
        skill_name: "code-review".to_string(),
        conversation_id: "conv-1".to_string(),
        project_id: None,
        user_query: "Review this patch".to_string(),
        summary: Some("Reviewed ownership and error handling.".to_string()),
        judge_scores: Some(json!({"quality": 0.8})),
        overall_score: Some(0.8),
        success: true,
        execution_time_ms: 1200,
        tool_call_count: 3,
        processed: true,
        created_at: DateTime::<Utc>::from_timestamp(1_700_000_300, 0).unwrap(),
    }];
    let recent_jobs = vec![SkillEvolutionJobRecord {
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
    }];

    let actual = serde_json::to_value(evolution_overview_from_records(
        config,
        stats,
        skill_summaries,
        recent_sessions,
        recent_jobs,
    ))
    .unwrap();
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_evolution_overview.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn skill_evolution_detail_matches_golden() {
    // Arrange
    let config = SkillEvolutionConfig {
        enabled: true,
        min_sessions_per_skill: 2,
        scoring_min_sessions_per_skill: 2,
        min_avg_score: 0.7,
        max_sessions_per_batch: 10,
        evolution_interval_minutes: 30,
        publish_mode: SkillEvolutionPublishMode::Review,
        auto_apply: false,
    };

    // Act
    let actual = serde_json::to_value(evolution_detail_from_records(
        &sample_skill_record(),
        config,
        vec![sample_version_record()],
        vec![sample_evolution_job_record()],
        2,
    ))
    .unwrap();

    // Assert
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_evolution_detail.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn skill_evolution_applied_job_matches_golden() {
    // Arrange
    let mut record = sample_evolution_job_record();
    record.action = "improve_skill".to_string();
    record.status = "applied".to_string();
    record.skill_version_id = Some("22222222-2222-4222-8222-222222222222".to_string());
    record.applied_at = Some(DateTime::<Utc>::from_timestamp(1_700_000_500, 0).unwrap());

    // Act
    let actual = serde_json::to_value(SkillEvolutionJobView::from(record)).unwrap();

    // Assert
    let golden: Value = serde_json::from_str(include_str!(
        "../../../tests/golden/skill_evolution_job_applied.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn replace_frontmatter_description_updates_only_description() {
    // Arrange
    let content = "---\nname: code-review\ndescription: Old description\n---\n# Body\n";

    // Act
    let actual = replace_frontmatter_description(content, "New description");

    // Assert
    assert!(actual.contains("name: code-review"));
    assert!(actual.contains("description: New description"));
    assert!(actual.ends_with("\n# Body\n"));
}
