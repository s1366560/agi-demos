use super::*;

pub(super) async fn roundtrip_topology_blackboard(
    pool: &PgPool,
    repo: &PgWorkspaceRepository,
    created_at: DateTime<Utc>,
) {
    let node = repo
        .create_node(TopologyNodeRecord {
            id: "node_p6_task".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            node_type: "task".to_string(),
            ref_id: Some("task_p6_repo".to_string()),
            title: "Task".to_string(),
            position_x: 0.0,
            position_y: 0.0,
            hex_q: Some(0),
            hex_r: Some(0),
            status: "active".to_string(),
            tags_json: vec!["p6".to_string()],
            data_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    let node2 = repo
        .create_node(TopologyNodeRecord {
            id: "node_p6_note".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            node_type: "note".to_string(),
            ref_id: None,
            title: "Note".to_string(),
            position_x: 1.0,
            position_y: 0.0,
            hex_q: Some(1),
            hex_r: Some(0),
            status: "active".to_string(),
            tags_json: vec![],
            data_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    let coords = repo
        .edge_endpoints_in_workspace("ws_p6_repo", &node.id, &node2.id)
        .await
        .unwrap()
        .expect("edge endpoints");
    assert_eq!(coords, (Some(0), Some(0), Some(1), Some(0)));
    let edge = repo
        .create_edge(TopologyEdgeRecord {
            id: "edge_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            source_node_id: node.id,
            target_node_id: node2.id,
            label: Some("relates".to_string()),
            source_hex_q: coords.0,
            source_hex_r: coords.1,
            target_hex_q: coords.2,
            target_hex_r: coords.3,
            direction: None,
            auto_created: false,
            data_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    assert_eq!(edge.source_hex_q, Some(0));

    let post = repo
        .create_post(BlackboardPostRecord {
            id: "post_p6_repo".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            author_id: "u_p6_owner".to_string(),
            title: "Status".to_string(),
            content: "Foundation ready".to_string(),
            status: "open".to_string(),
            is_pinned: true,
            metadata_json: json!({"lane": "p6"}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    let reply = repo
        .create_reply(BlackboardReplyRecord {
            id: "reply_p6_repo".to_string(),
            post_id: post.id.clone(),
            workspace_id: "ws_p6_repo".to_string(),
            author_id: "u_p6_viewer".to_string(),
            content: "ack".to_string(),
            metadata_json: json!({}),
            created_at,
            updated_at: None,
        })
        .await
        .unwrap();
    assert_eq!(reply.post_id, post.id);
    let dir = repo
        .create_file(BlackboardFileRecord {
            id: "file_p6_dir".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            parent_path: "/".to_string(),
            name: "docs".to_string(),
            is_directory: true,
            file_size: 0,
            content_type: String::new(),
            storage_key: String::new(),
            uploader_type: "user".to_string(),
            uploader_id: "u_p6_owner".to_string(),
            uploader_name: "Owner".to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at,
        })
        .await
        .unwrap();
    assert!(dir.is_directory);
    let file = repo
        .create_file(BlackboardFileRecord {
            id: "file_p6_doc".to_string(),
            workspace_id: "ws_p6_repo".to_string(),
            parent_path: "/docs/".to_string(),
            name: "status.txt".to_string(),
            is_directory: false,
            file_size: 11,
            content_type: "text/plain".to_string(),
            storage_key: "file_p6_doc/status.txt".to_string(),
            uploader_type: "user".to_string(),
            uploader_id: "u_p6_owner".to_string(),
            uploader_name: "Owner".to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at,
        })
        .await
        .unwrap();
    assert_eq!(file.parent_path, "/docs/");
    let files = repo.list_files("ws_p6_repo", "/docs/").await.unwrap();
    assert_eq!(
        files.iter().map(|f| f.name.as_str()).collect::<Vec<_>>(),
        vec!["status.txt"]
    );
    repo.bulk_update_file_parent_path("ws_p6_repo", "/docs/", "/notes/")
        .await
        .unwrap();
    let moved = repo
        .get_file("ws_p6_repo", "file_p6_doc")
        .await
        .unwrap()
        .expect("file");
    assert_eq!(moved.parent_path, "/notes/");
    repo.enqueue_blackboard_outbox(BlackboardOutboxRecord {
        id: "outbox_p6_repo".to_string(),
        workspace_id: "ws_p6_repo".to_string(),
        tenant_id: "t_p6_repo".to_string(),
        project_id: "p_p6_repo".to_string(),
        event_type: "blackboard_post_created".to_string(),
        payload_json: json!({"post_id": "post_p6_repo"}),
        metadata_json: json!({"tenant_id": "t_p6_repo"}),
        correlation_id: None,
    })
    .await
    .unwrap();
    let outbox_count = sqlx::query_as::<_, (i64,)>(
        "SELECT count(*) FROM workspace_blackboard_outbox WHERE id = 'outbox_p6_repo' \
         AND status = 'pending'",
    )
    .fetch_one(pool)
    .await
    .unwrap()
    .0;
    assert_eq!(outbox_count, 1);
}
