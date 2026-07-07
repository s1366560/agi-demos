use super::*;

pub(super) async fn roundtrip_workspace_access(
    repo: &PgWorkspaceRepository,
    created_at: DateTime<Utc>,
) {
    assert!(repo
        .user_can_access_project(
            "u_p6_owner",
            "t_p6_repo",
            "p_p6_repo",
            WorkspaceProjectAccess::Admin,
        )
        .await
        .unwrap());
    assert!(repo
        .user_can_access_project(
            "u_p6_viewer",
            "t_p6_repo",
            "p_p6_repo",
            WorkspaceProjectAccess::Read,
        )
        .await
        .unwrap());
    assert!(!repo
        .user_can_access_project(
            "u_p6_viewer",
            "t_p6_repo",
            "p_p6_repo",
            WorkspaceProjectAccess::Write,
        )
        .await
        .unwrap());

    let workspace = repo
        .create_workspace(
            WorkspaceRecord {
                id: "ws_p6_repo".to_string(),
                tenant_id: "t_p6_repo".to_string(),
                project_id: "p_p6_repo".to_string(),
                name: "P6 workspace".to_string(),
                description: Some("shared tables".to_string()),
                created_by: "u_p6_owner".to_string(),
                is_archived: false,
                metadata_json: json!({"workspace_use_case": "programming"}),
                office_status: "inactive".to_string(),
                hex_layout_config_json: json!({}),
                default_blocking_categories_json: vec!["blocked".to_string()],
                created_at,
                updated_at: None,
            },
            "wm_p6_owner".to_string(),
        )
        .await
        .unwrap();
    assert_eq!(workspace.id, "ws_p6_repo");
    assert_eq!(
        repo.workspace_scope("ws_p6_repo").await.unwrap(),
        Some(("t_p6_repo".to_string(), "p_p6_repo".to_string()))
    );
    assert!(repo
        .workspace_in_scope("ws_p6_repo", "t_p6_repo", "p_p6_repo")
        .await
        .unwrap());
    assert!(!repo
        .workspace_in_scope("ws_p6_repo", "wrong_tenant", "p_p6_repo")
        .await
        .unwrap());
    assert!(!repo
        .workspace_in_scope("ws_p6_repo", "t_p6_repo", "wrong_project")
        .await
        .unwrap());
    assert!(repo
        .user_can_access_workspace("u_p6_owner", "ws_p6_repo", WorkspaceAccess::Write)
        .await
        .unwrap());
    assert!(repo
        .user_can_access_workspace("u_p6_owner", "ws_p6_repo", WorkspaceAccess::Read)
        .await
        .unwrap());
    assert!(!repo
        .user_can_access_workspace("u_p6_viewer", "ws_p6_repo", WorkspaceAccess::Read)
        .await
        .unwrap());
    let listed = repo
        .list_workspaces_for_user("t_p6_repo", "p_p6_repo", "u_p6_owner", 10, 0)
        .await
        .unwrap();
    assert!(listed.iter().any(|item| item.id == "ws_p6_repo"));
}
