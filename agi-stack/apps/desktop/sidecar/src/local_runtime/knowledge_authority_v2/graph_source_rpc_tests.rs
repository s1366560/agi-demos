use super::*;

#[tokio::test]
async fn graph_source_rpc_returns_one_exact_audited_projection_to_a_viewer() {
    let f = Fixture::new("viewer").await;
    let (status, result) = query(
        &f,
        json!({"operation":"graph_source","source":f.source,"expected_audit_attempt":1}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{result}");
    assert_eq!(
        result["result"]["source"],
        serde_json::to_value(&f.source).unwrap()
    );
    assert_eq!(result["result"]["audit_attempt"], 1);
    assert_eq!(result["result"]["entities"][0]["name"], "Knowledge");
    assert_eq!(result["result"]["relationships"][0]["source_index"], 0);
    assert_eq!(result["result"]["relationships"][0]["target_index"], 0);
}

#[tokio::test]
async fn graph_source_rpc_rejects_stale_attempt_and_wrong_source() {
    let f = Fixture::new("viewer").await;
    for attempt in [0, 2] {
        let (status, result) = query(
            &f,
            json!({"operation":"graph_source","source":f.source,"expected_audit_attempt":attempt}),
        )
        .await;
        assert!(status.is_client_error(), "{result}");
        assert!(result.get("result").is_none());
    }
    let mut source = f.source.clone();
    source.tenant_id = "another-tenant".into();
    let (status, result) = query(
        &f,
        json!({"operation":"graph_source","source":source,"expected_audit_attempt":1}),
    )
    .await;
    assert!(status.is_client_error(), "{result}");
    assert!(result.get("result").is_none());
}
