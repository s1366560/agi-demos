use super::*;

use agistack_adapters_postgres::{
    CurrentUserRecord, ProjectDashboardStatsRecord, ProjectMemberRecord, ProjectMembersRecord,
    ProjectReadRecord, TenantRecord,
};

#[test]
fn html_escape_covers_text_and_attribute_metacharacters() {
    assert_eq!(
        escape_html("<tenant&role\"'>"),
        "&lt;tenant&amp;role&quot;&#39;&gt;"
    );
}

#[tokio::test]
async fn dev_login_accepts_non_empty_and_rejects_empty() {
    let svc = DevIdentityService::new("dev-user");
    let ok = svc.login("admin@memstack.ai", "pw", 0).await.unwrap();
    assert!(ok.access_token.starts_with("ms_sk_"));
    assert_eq!(ok.token_type, "bearer");
    assert!(!ok.must_change_password);
    assert_eq!(
        svc.login("", "pw", 0).await.unwrap_err().status,
        StatusCode::UNAUTHORIZED
    );
    // The login 401 carries WWW-Authenticate (Python parity).
    assert!(svc.login("u", "", 0).await.unwrap_err().www_authenticate);
}

#[tokio::test]
async fn dev_current_user_matches_authenticated_identity() {
    let svc = DevIdentityService::new("dev-user");
    let view = svc.current_user("dev-user").await.unwrap();
    assert_eq!(view.user_id, "dev-user");
    assert_eq!(view.email, "dev@example.test");
    assert_eq!(view.name, "Dev User");
    assert_eq!(view.roles, vec!["admin"]);
    assert!(view.is_active);
    assert_eq!(view.profile, json!({}));
    assert_eq!(
        svc.current_user("other").await.unwrap_err().status,
        StatusCode::NOT_FOUND
    );
}

#[tokio::test]
async fn dev_list_tenants_paginates_and_filters() {
    let svc = DevIdentityService::new("dev-user");
    let page = svc.list_tenants("dev-user", None, 1, 20).await.unwrap();
    assert_eq!(page.total, 1);
    assert_eq!(page.page, 1);
    assert_eq!(page.page_size, 20);
    assert_eq!(page.tenants.len(), 1);
    assert_eq!(page.tenants[0].slug, "dev");
    // Non-matching search -> empty, total 0.
    let none = svc
        .list_tenants("dev-user", Some("zzz"), 1, 20)
        .await
        .unwrap();
    assert_eq!(none.total, 0);
    assert!(none.tenants.is_empty());
    // Page 2 of a 1-item set is empty but echoes pagination.
    let p2 = svc.list_tenants("dev-user", None, 2, 20).await.unwrap();
    assert_eq!(p2.page, 2);
    assert!(p2.tenants.is_empty());
}

#[tokio::test]
async fn dev_get_tenant_by_id_or_slug_else_404() {
    let svc = DevIdentityService::new("dev-user");
    assert_eq!(
        svc.get_tenant("u", "dev-tenant").await.unwrap().id,
        "dev-tenant"
    );
    assert_eq!(svc.get_tenant("u", "dev").await.unwrap().slug, "dev");
    assert_eq!(
        svc.get_tenant("u", "nope").await.unwrap_err().status,
        StatusCode::NOT_FOUND
    );
}

#[tokio::test]
async fn dev_list_projects_filters_and_paginates() {
    let svc = DevIdentityService::new("dev-user");
    let page = svc
        .list_projects(
            "dev-user",
            ProjectListInput {
                tenant_id: Some("dev-tenant"),
                search: Some("Default"),
                visibility: "all",
                owner_id: None,
                page: 1,
                page_size: 20,
            },
        )
        .await
        .unwrap();
    assert_eq!(page.total, 1);
    assert_eq!(page.projects[0].id, "dev-project");
    assert_eq!(page.owner_ids, vec!["dev-user"]);

    let empty = svc
        .list_projects(
            "dev-user",
            ProjectListInput {
                tenant_id: Some("other"),
                search: None,
                visibility: "all",
                owner_id: None,
                page: 1,
                page_size: 20,
            },
        )
        .await
        .unwrap();
    assert_eq!(empty.total, 0);
    assert!(empty.projects.is_empty());
    assert!(empty.owner_ids.is_empty());

    let private = svc
        .list_projects(
            "dev-user",
            ProjectListInput {
                tenant_id: None,
                search: None,
                visibility: "private",
                owner_id: None,
                page: 2,
                page_size: 20,
            },
        )
        .await
        .unwrap();
    assert_eq!(private.total, 1);
    assert_eq!(private.page, 2);
    assert!(private.projects.is_empty());
}

#[tokio::test]
async fn dev_get_project_matches_python_error_order() {
    let svc = DevIdentityService::new("dev-user");
    assert_eq!(
        svc.get_project("dev-user", "dev-project", None)
            .await
            .unwrap()
            .tenant_id,
        "dev-tenant"
    );
    assert_eq!(
        svc.get_project("dev-user", "missing", None)
            .await
            .unwrap_err()
            .status,
        StatusCode::FORBIDDEN
    );
    assert_eq!(
        svc.get_project("dev-user", "dev-project", Some("other"))
            .await
            .unwrap_err()
            .status,
        StatusCode::NOT_FOUND
    );
}

#[tokio::test]
async fn dev_create_and_update_project_match_python_permissions() {
    let svc = DevIdentityService::new("dev-user");
    let created = svc
        .create_project(
            "dev-user",
            ProjectCreateInput {
                tenant_id: "dev-tenant".to_string(),
                name: "New Project".to_string(),
                description: Some("created".to_string()),
                memory_rules: Some(json!({"max_episodes": 2000})),
                graph_config: Some(json!({"max_nodes": 5000})),
                graph_store_id: Some("__env_neo4j__".to_string()),
                retrieval_store_id: Some("__env_memstack_pgvector__".to_string()),
                is_public: true,
                agent_conversation_mode: "multi_agent_shared".to_string(),
            },
        )
        .await
        .unwrap();
    assert_eq!(created.id, "dev-created-project");
    assert_eq!(created.name, "New Project");
    assert_eq!(created.memory_rules["retention_days"], 30);
    assert_eq!(created.memory_rules["max_episodes"], 2000);
    assert!(created.graph_store_id.is_none());
    assert_eq!(created.agent_conversation_mode, "multi_agent_shared");

    let denied = svc
        .create_project(
            "other-user",
            ProjectCreateInput {
                tenant_id: "dev-tenant".to_string(),
                name: "Denied".to_string(),
                description: None,
                memory_rules: None,
                graph_config: None,
                graph_store_id: None,
                retrieval_store_id: None,
                is_public: false,
                agent_conversation_mode: "single_agent".to_string(),
            },
        )
        .await
        .unwrap_err();
    assert_eq!(denied.status, StatusCode::FORBIDDEN);

    let updated = svc
        .update_project(
            "dev-user",
            "dev-project",
            ProjectUpdatePatch {
                name: Some("Updated Project".to_string()),
                description: Some(None),
                memory_rules: Some(json!({"refresh_interval": 12})),
                graph_config: None,
                graph_store_id: Some(None),
                retrieval_store_id: Some(None),
                sandbox_config: Some(json!({"sandbox_type": "local"})),
                is_public: Some(true),
                agent_conversation_mode: Some("multi_agent_isolated".to_string()),
            },
        )
        .await
        .unwrap();
    assert_eq!(updated.name, "Updated Project");
    assert!(updated.description.is_none());
    assert_eq!(updated.memory_rules["max_episodes"], 1000);
    assert_eq!(updated.memory_rules["refresh_interval"], 12);
    assert_eq!(updated.sandbox_config["sandbox_type"], "local");
    assert_eq!(updated.agent_conversation_mode, "multi_agent_isolated");
}

#[test]
fn pagination_is_clamped() {
    assert_eq!(clamp_pagination(0, 0), (1, 1));
    assert_eq!(clamp_pagination(-5, 500), (1, 100));
    assert_eq!(clamp_pagination(3, 50), (3, 50));
}

#[test]
fn tenant_view_serializes_python_shape() {
    let view = TenantView {
        id: "t1".into(),
        name: "Acme".into(),
        slug: "acme".into(),
        description: None,
        owner_id: "u1".into(),
        plan: "free".into(),
        max_projects: 10,
        max_users: 5,
        max_storage: 1_073_741_824,
        created_at: "2023-11-14T22:13:20Z".into(),
        updated_at: None,
    };
    let v = serde_json::to_value(&view).unwrap();
    assert_eq!(v["id"], "t1");
    assert_eq!(v["slug"], "acme");
    assert_eq!(v["description"], serde_json::Value::Null);
    assert_eq!(v["max_storage"], 1_073_741_824i64);
    assert_eq!(v["updated_at"], serde_json::Value::Null);
    assert_eq!(v["created_at"], "2023-11-14T22:13:20Z");
}

#[test]
fn login_outcome_is_flat_token_shape() {
    let out = LoginOutcome {
        access_token: "ms_sk_abc".into(),
        token_type: "bearer".into(),
        must_change_password: true,
    };
    let v = serde_json::to_value(&out).unwrap();
    // Exactly the three Python `Token` fields, no timestamp.
    assert_eq!(v.as_object().unwrap().len(), 3);
    assert_eq!(v["access_token"], "ms_sk_abc");
    assert_eq!(v["token_type"], "bearer");
    assert_eq!(v["must_change_password"], true);
}

#[test]
fn project_defaults_expand_python_shapes() {
    let mut raw = Map::new();
    raw.insert("max_episodes".to_string(), json!(2000));
    let merged = with_defaults(default_memory_rules(), Value::Object(raw));
    assert_eq!(merged["max_episodes"], 2000);
    assert_eq!(merged["retention_days"], 30);

    let sandbox = sandbox_config(
        "local",
        json!({"local_config": {"workspace_path": "/tmp/w"}}),
    );
    assert_eq!(sandbox["sandbox_type"], "local");
    assert_eq!(sandbox["local_config"]["workspace_path"], "/tmp/w");
}

// ---- F3 parity gate: assert the wire shapes against contract-derived
// goldens (plan.md §14.2 F3). The goldens live in `apps/server/tests/golden/`
// and encode the Python schema contract; `agistack_parity::compare` checks
// key-set + type + scalar-format parity so a strangler flip is safe.

fn sample_tenant_record() -> TenantRecord {
    TenantRecord {
        id: "44444444-4444-4444-8444-444444444444".into(),
        name: "Acme".into(),
        slug: "acme".into(),
        description: None,
        owner_id: "33333333-3333-4333-8333-333333333333".into(),
        plan: "free".into(),
        max_projects: 10,
        max_users: 25,
        max_storage: 10_737_418_240,
        // 2023-11-14T22:13:20Z — deterministic so `created_at` is byte-stable.
        created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
        updated_at: None,
    }
}

fn sample_project_record() -> ProjectReadRecord {
    ProjectReadRecord {
        id: "55555555-5555-4555-8555-555555555555".into(),
        tenant_id: "44444444-4444-4444-8444-444444444444".into(),
        name: "Default project".into(),
        description: None,
        owner_id: "33333333-3333-4333-8333-333333333333".into(),
        member_ids: vec!["33333333-3333-4333-8333-333333333333".into()],
        memory_rules: json!({}),
        graph_config: json!({}),
        graph_store_id: None,
        retrieval_store_id: None,
        sandbox_type: "cloud".into(),
        sandbox_config: json!({}),
        is_public: false,
        agent_conversation_mode: "single_agent".into(),
        created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
        updated_at: None,
        stats: agistack_adapters_postgres::ProjectStatsRecord {
            memory_count: 0,
            storage_used: 0,
            member_count: 1,
            last_active: None,
        },
    }
}

fn sample_invitation_record() -> InvitationRecord {
    InvitationRecord {
        id: "66666666-6666-4666-8666-666666666666".into(),
        tenant_id: "44444444-4444-4444-8444-444444444444".into(),
        email: "invitee@example.test".into(),
        role: "member".into(),
        token: "token-hidden-from-response".into(),
        status: "pending".into(),
        invited_by: "33333333-3333-4333-8333-333333333333".into(),
        accepted_by: None,
        expires_at: chrono::DateTime::from_timestamp(1_700_604_800, 0).unwrap(),
        created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
        deleted_at: None,
    }
}

fn sample_current_user_record() -> CurrentUserRecord {
    CurrentUserRecord {
        id: "33333333-3333-4333-8333-333333333333".into(),
        email: "admin@memstack.ai".into(),
        full_name: Some("Admin User".into()),
        roles: vec!["admin".into(), "user".into()],
        is_active: true,
        created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
        profile: json!({
            "department": "Platform",
            "language": "zh-CN"
        }),
        preferred_language: Some("zh-CN".into()),
    }
}

#[test]
fn current_user_view_matches_golden() {
    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../tests/golden/current_user_response.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(CurrentUserView::from(sample_current_user_record())).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn current_user_profile_null_normalizes_to_object() {
    let mut record = sample_current_user_record();
    record.profile = Value::Null;
    let view = CurrentUserView::from(record);
    assert_eq!(view.profile, json!({}));
}

#[test]
fn tenant_view_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/tenant_view.json")).unwrap();
    let actual = serde_json::to_value(TenantView::from(sample_tenant_record())).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn tenant_page_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/tenant_page.json")).unwrap();
    let page = TenantPage {
        tenants: vec![TenantView::from(sample_tenant_record())],
        total: 1,
        page: 1,
        page_size: 20,
    };
    let actual = serde_json::to_value(&page).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn tenant_member_added_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/tenant_member_added.json")).unwrap();
    let view = TenantMemberMutationView {
        message: "Member added successfully".into(),
        user_id: "44444444-4444-4444-8444-444444444444".into(),
        role: "member".into(),
    };
    let actual = serde_json::to_value(&view).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn tenant_member_updated_matches_golden() {
    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../tests/golden/tenant_member_updated.json"
    ))
    .unwrap();
    let view = TenantMemberMutationView {
        message: "Member role updated successfully".into(),
        user_id: "44444444-4444-4444-8444-444444444444".into(),
        role: "viewer".into(),
    };
    let actual = serde_json::to_value(&view).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn tenant_member_role_and_permission_rules_match_python() {
    assert_eq!(default_tenant_member_role(None), "member");
    assert_eq!(default_tenant_member_role(Some("")), "member");
    assert_eq!(default_tenant_member_role(Some(" ")), " ");
    assert!(is_valid_tenant_member_role("editor"));
    assert!(!is_valid_tenant_member_role(" "));
    assert_eq!(tenant_member_add_permissions("viewer")["write"], false);
    assert_eq!(tenant_member_add_permissions("editor")["write"], true);
    assert_eq!(tenant_member_update_permissions("viewer")["write"], false);
    assert_eq!(tenant_member_update_permissions("owner")["write"], true);
}

#[test]
fn project_view_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/project_view.json")).unwrap();
    let actual = serde_json::to_value(ProjectView::from(sample_project_record())).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn project_page_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/project_page.json")).unwrap();
    let page = ProjectPage {
        projects: vec![ProjectView::from(sample_project_record())],
        total: 1,
        page: 1,
        page_size: 20,
        owner_ids: vec!["33333333-3333-4333-8333-333333333333".into()],
    };
    let actual = serde_json::to_value(&page).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn project_stats_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/project_stats.json")).unwrap();
    let stats = ProjectStatsView::dashboard(
        ProjectDashboardStatsRecord {
            memory_count: 2,
            conversation_count: 3,
            storage_used: 42,
            member_count: 4,
            recent_activity: vec![ProjectActivityRecord {
                id: "mem-1".into(),
                user: "Ada Lovelace".into(),
                target: "Portable core".into(),
                created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
            }],
        },
        1_700_000_600_000,
    );
    let actual = serde_json::to_value(&stats).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn project_members_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/project_members.json")).unwrap();
    let members = ProjectMembersView::from(ProjectMembersRecord {
        members: vec![ProjectMemberRecord {
            user_id: "33333333-3333-4333-8333-333333333333".into(),
            email: "ada@example.test".into(),
            name: Some("Ada Lovelace".into()),
            role: "owner".into(),
            permissions: json!({
                "admin": true,
                "read": true,
                "write": true,
                "delete": true
            }),
            created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
        }],
        total: 1,
    });
    let actual = serde_json::to_value(&members).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn project_member_added_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/project_member_added.json")).unwrap();
    let view = ProjectMemberMutationView {
        message: "Member added successfully".into(),
        user_id: "44444444-4444-4444-8444-444444444444".into(),
        role: "member".into(),
    };
    let actual = serde_json::to_value(&view).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn project_member_updated_matches_golden() {
    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../tests/golden/project_member_updated.json"
    ))
    .unwrap();
    let view = ProjectMemberMutationView {
        message: "Member role updated successfully".into(),
        user_id: "44444444-4444-4444-8444-444444444444".into(),
        role: "viewer".into(),
    };
    let actual = serde_json::to_value(&view).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn project_member_role_and_permission_rules_match_python() {
    assert_eq!(default_project_member_role(None), "member");
    assert_eq!(default_project_member_role(Some("")), "member");
    assert_eq!(default_project_member_role(Some(" ")), " ");
    assert!(is_valid_project_member_role("editor"));
    assert!(!is_valid_project_member_role(" "));
    assert_eq!(project_member_add_permissions("editor")["write"], true);
    assert_eq!(project_member_update_permissions("editor")["write"], false);
}

#[test]
fn invitation_response_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/invitation_response.json")).unwrap();
    let actual = serde_json::to_value(InvitationView::from(sample_invitation_record())).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn invitation_list_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/invitation_list.json")).unwrap();
    let list = InvitationListView {
        items: vec![InvitationView::from(sample_invitation_record())],
        total: 1,
        limit: 50,
        offset: 0,
    };
    let actual = serde_json::to_value(&list).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn invitation_verify_matches_golden_and_invalid_shape() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/invitation_verify.json")).unwrap();
    let actual =
        serde_json::to_value(InvitationVerifyView::valid(sample_invitation_record())).unwrap();
    agistack_parity::assert_parity(&golden, &actual);

    let invalid = serde_json::to_value(InvitationVerifyView::invalid()).unwrap();
    assert_eq!(invalid["valid"], false);
    assert_eq!(invalid["email"], serde_json::Value::Null);
    assert_eq!(invalid["expires_at"], serde_json::Value::Null);
}

#[test]
fn device_code_response_matches_golden() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/device_code_response.json")).unwrap();
    let response = DeviceCodeView {
        device_code: agistack_adapters_secrets::generate_urlsafe_token(32),
        user_code: "ABCDEFGH".to_string(),
        verification_uri: "/device".to_string(),
        verification_uri_complete: "/device?user_code=ABCDEFGH".to_string(),
        expires_in: DEVICE_CODE_TTL_SECS,
        interval: DEVICE_CODE_INTERVAL_SECS,
    };
    let actual = serde_json::to_value(&response).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn device_approve_response_matches_golden() {
    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../tests/golden/device_approve_response.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(DeviceApproveView {
        status: "approved".into(),
    })
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn device_token_response_matches_golden() {
    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../tests/golden/device_token_response.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(DeviceTokenView {
        access_token: agistack_adapters_secrets::generate_api_key(),
        token_type: "bearer".into(),
    })
    .unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[tokio::test]
async fn dev_device_code_flow_matches_python_states() {
    let svc = DevIdentityService::new("dev-user");
    let code = svc.create_device_code().await.unwrap();
    assert_eq!(code.verification_uri, "/device");
    assert_eq!(
        code.verification_uri_complete,
        format!("/device?user_code={}", code.user_code)
    );
    assert_eq!(code.expires_in, DEVICE_CODE_TTL_SECS);
    assert_eq!(code.interval, DEVICE_CODE_INTERVAL_SECS);
    assert!(agistack_parity::is_urlsafe_token_32(&code.device_code));
    assert!(agistack_parity::is_device_user_code(&code.user_code));

    let pending = svc.poll_device_token(&code.device_code).await.unwrap_err();
    assert_eq!(pending.status, StatusCode::PRECONDITION_REQUIRED);
    assert_eq!(
        pending.detail_value.unwrap(),
        json!({"error": "authorization_pending", "interval": DEVICE_CODE_INTERVAL_SECS})
    );

    let approved = svc
        .approve_device_code(
            "dev-user",
            &format!(" {} ", code.user_code.to_lowercase()),
            0,
        )
        .await
        .unwrap();
    assert_eq!(approved.status, "approved");
    let token = svc.poll_device_token(&code.device_code).await.unwrap();
    assert!(token.access_token.starts_with("ms_sk_"));
    assert_eq!(token.token_type, "bearer");

    let consumed = svc.poll_device_token(&code.device_code).await.unwrap_err();
    assert_eq!(consumed.status, StatusCode::GONE);
    assert_eq!(consumed.detail, "expired_token");
}

#[test]
fn login_token_matches_golden_with_real_minted_key() {
    // A freshly minted `ms_sk_` key must satisfy the golden's `<ms_sk>`
    // matcher — proving the format the strangled login emits is contract-valid.
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("../../tests/golden/login_token.json")).unwrap();
    let out = LoginOutcome {
        access_token: agistack_adapters_secrets::generate_api_key(),
        token_type: "bearer".into(),
        must_change_password: false,
    };
    let actual = serde_json::to_value(&out).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}
