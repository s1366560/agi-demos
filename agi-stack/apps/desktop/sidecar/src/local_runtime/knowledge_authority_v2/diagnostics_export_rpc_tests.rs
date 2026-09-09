use super::*;

fn export_audit_timeline(f: &Fixture) -> Vec<Value> {
    let conversation = format!(
        "knowledge-diagnostics-export:{}:{}",
        f.auth.workspace.tenant_id, f.auth.workspace.project_id
    );
    f.state
        .session_store
        .timeline(&conversation, 10)
        .unwrap()
}

#[tokio::test]
async fn diagnostics_export_reports_whitelisted_failures_success_and_sync_state() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::OK
    );
    let config = f
        .repo()
        .desired_index_config_durable(&f.operation.scope, &|| Ok(110))
        .unwrap()
        .unwrap();
    let lease = f
        .repo()
        .claim_index_durable(&config, "worker", 100, &|| Ok(110))
        .unwrap()
        .unwrap();
    f.repo()
        .fail_index_durable(&lease, IndexFailure::ProviderUnavailable, &|| Ok(111))
        .unwrap();
    let first = query(&f, json!({"operation":"diagnostics_export"})).await;
    assert_eq!(first.0, StatusCode::OK, "{:?}", first.1);
    let result = &first.1["result"];
    assert_eq!(result["diagnostics_export_version"], 1);
    assert!(result["generated_at_ms"].as_i64().unwrap() > 0);
    assert_eq!(
        result["application"]["module_ref"],
        "builtin://memstack/desktop-sidecar/knowledge-authority"
    );
    assert!(result["application"]["knowledge_schema_version"].as_u64().unwrap() >= 19);
    assert_eq!(result["scope"]["tenant_id"], f.auth.workspace.tenant_id);
    assert_eq!(result["scope"]["project_id"], f.auth.workspace.project_id);
    // Index failure stage with the exact task descriptor.
    let failed_index = &result["index"]["failed"][0];
    assert_eq!(failed_index["input"], json!(lease.input));
    assert_eq!(failed_index["failure"], "provider_unavailable");
    assert_eq!(result["index"]["coverage"]["failed_sources"], 1);
    assert_eq!(result["index"]["truncated"], false);
    assert!(result["processing"]["failed"].as_array().unwrap().is_empty());
    // The fixture's applied extraction is the last processing success.
    assert_eq!(result["processing"]["last_success_ms"], 101);
    assert_eq!(result["index"]["last_success_ms"], Value::Null);
    // Configuration provenance: model and revisions, never the credential.
    assert_eq!(
        result["index"]["configuration"]["model_id"],
        "configured-embedding-model"
    );
    assert_eq!(result["index"]["configuration"]["build_id"], "a");
    // Sync status: counts, cursors and receipt positions only.
    assert_eq!(result["sync"]["linked"], false);
    assert_eq!(result["sync"]["pending_changes"], 1);
    assert_eq!(result["sync"]["pull_cursor"], 0);
    assert_eq!(result["sync"]["last_receipt_sequence"], Value::Null);
    let mut memory = f
        .repo()
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.content = "replaced export content".into();
    f.repo()
        .update(&f.operation.scope, memory, 1)
        .await
        .unwrap();
    let pending = f
        .repo()
        .claim(&f.operation.scope, "worker", 110, 100)
        .await
        .unwrap()
        .unwrap();
    f.repo()
        .fail(
            &f.operation.scope,
            &pending,
            ProcessingFailure::ModelUnconfigured,
            111,
        )
        .await
        .unwrap();
    let export = query(&f, json!({"operation":"diagnostics_export"})).await;
    assert_eq!(export.0, StatusCode::OK, "{:?}", export.1);
    let result = &export.1["result"];
    // Processing failure stage with the exact task descriptor.
    let failed_processing = &result["processing"]["failed"][0];
    assert_eq!(failed_processing["source"], json!(pending.source));
    assert_eq!(failed_processing["failure"], "model_unconfigured");
    assert_eq!(result["processing"]["truncated"], false);
    // Coverage and pending counts.
    assert_eq!(result["processing"]["coverage"]["current_sources"], 1);
    assert_eq!(result["processing"]["coverage"]["failed_sources"], 1);
    assert_eq!(result["sync"]["pending_changes"], 2);
    // The superseded index failure is no longer current.
    assert!(result["index"]["failed"].as_array().unwrap().is_empty());
    // Whitelist guarantee: no content, no credentials, no digests of them.
    let serialized = export.1.to_string();
    for forbidden in [
        "generation-owned content",
        "replaced export content",
        "embedding-fixture-key",
        "credential_binding_digest",
        "input_text",
    ] {
        assert!(!serialized.contains(forbidden), "{forbidden}");
    }
    // Both sensitive reads are recorded as durable audits.
    let audits = export_audit_timeline(&f);
    assert_eq!(audits.len(), 2);
    let payload = &audits[1]["payload"];
    assert_eq!(payload["action"], "diagnostics_export");
    assert_eq!(payload["status"], "exported");
    assert_eq!(payload["actor_id"], f.auth.user.user_id);
    assert_eq!(payload["summary"]["failed_processing"], 1);
    assert_eq!(payload["summary"]["failed_index"], 0);
    assert_eq!(payload["summary"]["sync_included"], true);
    assert!(!audits[1].to_string().contains("replaced export content"));
}

#[tokio::test]
async fn diagnostics_export_never_leaks_planted_credentials_or_memory_content() {
    let f = Fixture::new().await;
    let mut memory = f
        .repo()
        .get(&f.operation.scope, &f.source.memory_id)
        .await
        .unwrap()
        .unwrap();
    memory.title = "ms_sk_plantedtitle0000".into();
    memory.content =
        "confidential notes with sk-live-planted-credential and password=hunter2".into();
    f.repo()
        .update(&f.operation.scope, memory, 1)
        .await
        .unwrap();
    let pending = f
        .repo()
        .claim(&f.operation.scope, "worker", 110, 100)
        .await
        .unwrap()
        .unwrap();
    f.repo()
        .fail(
            &f.operation.scope,
            &pending,
            ProcessingFailure::ProcessingFailed,
            111,
        )
        .await
        .unwrap();
    let export = query(&f, json!({"operation":"diagnostics_export"})).await;
    assert_eq!(export.0, StatusCode::OK, "{:?}", export.1);
    let serialized = export.1.to_string();
    for planted in [
        "ms_sk_plantedtitle0000",
        "sk-live-planted-credential",
        "hunter2",
        "confidential notes",
    ] {
        assert!(!serialized.contains(planted), "{planted}");
    }
    assert_eq!(export.1["result"]["processing"]["failed"].as_array().unwrap().len(), 1);
}

#[tokio::test]
async fn diagnostics_export_is_capability_gated_and_records_failed_audit() {
    let f = Fixture::new().await;
    let restrict = |actions: &[&str]| {
        f.operation
            .authority
            .inner
            .lock()
            .unwrap()
            .validation_actions =
            Some(actions.iter().map(|action| (*action).to_owned()).collect());
    };
    restrict(&["failed_processing"]);
    let denied = query(&f, json!({"operation":"diagnostics_export"})).await;
    assert_eq!(denied.0, StatusCode::FORBIDDEN);
    assert!(export_audit_timeline(&f).is_empty());
    restrict(&["diagnostics_export"]);
    let allowed = query(&f, json!({"operation":"diagnostics_export"})).await;
    assert_eq!(allowed.0, StatusCode::OK, "{:?}", allowed.1);
    assert_eq!(export_audit_timeline(&f).len(), 1);
    // Session revocation rejects the export like every other diagnostics read.
    let f = Fixture::new().await;
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_user_sessions SET status='revoked'")
        .unwrap();
    let revoked = query(&f, json!({"operation":"diagnostics_export"})).await;
    assert!(!revoked.0.is_success());
    assert!(export_audit_timeline(&f).is_empty());
}

#[tokio::test]
async fn diagnostics_export_reports_completed_index_success_after_indexing() {
    let f = Fixture::new().await;
    let endpoint = Endpoint::new().await;
    let route = f.provider(&endpoint).await;
    assert_eq!(
        command(&f, configure(&route, "a", None)).await.0,
        StatusCode::OK
    );
    let indexed = command(
        &f,
        json!({"operation":"index_one","build_id":"a","config_revision":1}),
    )
    .await;
    assert_eq!(indexed.0, StatusCode::OK);
    assert_eq!(indexed.1["result"]["receipt"]["status"], "indexed");
    let export = query(&f, json!({"operation":"diagnostics_export"})).await;
    assert_eq!(export.0, StatusCode::OK, "{:?}", export.1);
    let result = &export.1["result"];
    assert!(result["index"]["last_success_ms"].as_i64().unwrap() > 0);
    assert!(result["index"]["failed"].as_array().unwrap().is_empty());
    assert_eq!(result["index"]["coverage"]["completed_sources"], 1);
}
