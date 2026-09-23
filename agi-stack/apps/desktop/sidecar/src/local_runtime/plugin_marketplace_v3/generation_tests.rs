use super::tests::{example, fixture, request};
use super::*;
use agistack_core::ports::ToolHost;
use axum::http::Method;

#[tokio::test]
async fn publication_journal_recovers_committed_switch_and_interrupted_job() {
    let (state, auth, directory) = fixture();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Journal","kind":"local","location":example(),"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let (_,installed)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"base"})).await;
    assert_eq!(installed["status"], "enabled", "{installed}");
    let root = auth_root(&state, &auth).unwrap();
    let mut data = load(&root).unwrap();
    let old = data.installations[0].clone();
    let mut replacement = old.clone();
    replacement.id = uuid::Uuid::new_v4().to_string();
    replacement.server_ids.clear();
    replacement.skill_ids.clear();
    replacement.status = "downloaded".into();
    replacement.version = "2.0.0".into();
    replacement.package.descriptor.version = "2.0.0".into();
    resources::register(&state, &auth, &mut replacement).unwrap();
    resources::set_enabled(&state, &auth, &mut replacement, true).unwrap();
    resources::verify(&state, &auth, &replacement)
        .await
        .unwrap();
    let scope = super::super::mcp_supervisor::McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    assert_eq!(
        state.mcp_supervisor.list_servers(&scope).unwrap().len(),
        1,
        "verified candidate stays hidden"
    );
    replacement.id = old.id.clone();
    data.transition = Some(Transition {
        installation_id: old.id.clone(),
        replacement: replacement.clone(),
    });
    data.jobs.insert("interrupted-job".into(),serde_json::from_value(json!({"id":"interrupted-job","operation":"update","status":"running","stage":"activating","request_hash":"test","created_at":"now","updated_at":"now","error":null,"result":null})).unwrap());
    save(&root, &data).unwrap();
    resources::publish(&state, &auth, &replacement, Some(&old)).unwrap();
    // Simulate the crash window after SQLite publication but before final JSON metadata save.
    recover(&state).unwrap();
    let restored = load(&root).unwrap();
    assert!(restored.transition.is_none());
    assert_eq!(restored.installations[0].version, "2.0.0");
    assert_eq!(restored.installations[0].server_ids, replacement.server_ids);
    let (_, job) = request(
        state.clone(),
        &auth,
        Method::GET,
        "/api/v1/plugin-marketplace/v3/jobs/interrupted-job",
        json!({}),
    )
    .await;
    assert_eq!(job["stage"], "interrupted");
    assert_eq!(job["status"], "failed");
    request(
        state.clone(),
        &auth,
        Method::POST,
        &format!(
            "/api/v1/plugin-marketplace/v3/installations/{}/uninstall",
            old.id
        ),
        json!({"idempotency_key":"cleanup"}),
    )
    .await;
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn updates_publish_new_catalog_while_existing_run_keeps_its_old_generation() {
    let (state, auth, directory) = fixture();
    let source_root = directory.join("source");
    package::snapshot(&example().join("plugins/marketplace-demo"), &source_root).unwrap();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Versions","kind":"local","location":source_root,"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let (_,installation)=request(state.clone(),&auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"install-v1"})).await;
    assert_eq!(installation["status"], "enabled", "{installation}");
    let scope = super::super::mcp_supervisor::McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let old_id = state.mcp_supervisor.list_servers(&scope).unwrap()[0]
        .id
        .clone();
    let old_host = super::super::mcp_agent_tool_host::McpAgentToolHost::new(
        state.mcp_supervisor.clone(),
        scope.clone(),
        "old-run".into(),
        None,
    )
    .unwrap();
    let old_tool = old_host.list_tools()[0].clone();
    let old_snapshot = load(&auth_root(&state, &auth).unwrap())
        .unwrap()
        .installations[0]
        .package
        .root
        .clone();
    let path = source_root.join(".codex-plugin/plugin.json");
    let mut manifest = package::bounded_json(&path).unwrap();
    manifest["version"] = json!("2.0.0");
    std::fs::write(path, manifest.to_string()).unwrap();
    let script = source_root.join("scripts/demo_mcp.py");
    let content = std::fs::read_to_string(&script).unwrap().replace(
        "str(params.get(\"arguments\", {}).get(\"text\", \"\"))",
        "\"v2:\" + str(params.get(\"arguments\", {}).get(\"text\", \"\"))",
    );
    std::fs::write(script, content).unwrap();
    let (_, next) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let id = installation["id"].as_str().unwrap();
    let (status,updated)=request(state.clone(),&auth,Method::POST,&format!("/api/v1/plugin-marketplace/v3/installations/{id}/update"),json!({"preflight_id":next["id"],"approved_permissions":next["permissions"],"idempotency_key":"update-v2"})).await;
    assert_eq!(status, StatusCode::OK, "{updated}");
    assert_eq!(updated["version"], "2.0.0");
    let visible = state.mcp_supervisor.list_servers(&scope).unwrap();
    assert_eq!(visible.len(), 1);
    assert_ne!(visible[0].id, old_id);
    assert!(
        state
            .mcp_supervisor
            .server(&scope, &old_id)
            .unwrap()
            .is_some(),
        "old run retains old resources"
    );
    assert!(
        state
            .mcp_supervisor
            .call_tool(
                &scope,
                &old_id,
                "echo",
                json!({"text":"new direct caller"}),
                "direct-old"
            )
            .await
            .is_err(),
        "fresh callers cannot invoke retired generation"
    );
    let result: Value = serde_json::from_str(
        &old_host
            .call(&old_tool, "{\"text\":\"old\"}")
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(result["content"][0]["text"], "old");
    let current = super::super::mcp_agent_tool_host::McpAgentToolHost::new(
        state.mcp_supervisor.clone(),
        scope.clone(),
        "new-run".into(),
        None,
    )
    .unwrap();
    let result: Value = serde_json::from_str(
        &current
            .call(&current.list_tools()[0], "{\"text\":\"new\"}")
            .await
            .unwrap(),
    )
    .unwrap();
    assert_eq!(result["content"][0]["text"], "v2:new");
    assert!(old_snapshot.exists(), "old MCP run owns its snapshot lease");
    drop(old_host);
    assert!(
        !old_snapshot.exists(),
        "retired snapshot collected after final run lease"
    );
    assert!(
        state
            .mcp_supervisor
            .server(&scope, &old_id)
            .unwrap()
            .is_none(),
        "last old lease retires resources"
    );
    drop(current);
    let job_id = updated["job_id"].as_str().unwrap();
    let (_, job) = request(
        state.clone(),
        &auth,
        Method::GET,
        &format!("/api/v1/plugin-marketplace/v3/jobs/{job_id}"),
        json!({}),
    )
    .await;
    assert_eq!(job["status"], "succeeded");
    assert_eq!(job["result"]["version"], "2.0.0");
    request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
        json!({"idempotency_key":"cleanup"}),
    )
    .await;
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn job_stages_are_queryable_and_disconnected_waiter_does_not_cancel_installation() {
    let (state, auth, directory) = fixture();
    let source_root = directory.join("source");
    package::snapshot(&example().join("plugins/marketplace-demo"), &source_root).unwrap();
    let script = source_root.join("scripts/demo_mcp.py");
    let content = std::fs::read_to_string(&script)
        .unwrap()
        .replace("import json", "import json\nimport time")
        .replace(
            "if method == \"tools/list\":",
            "if method == \"tools/list\":\n        time.sleep(1)",
        );
    std::fs::write(script, content).unwrap();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Slow","kind":"local","location":source_root,"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let cloned_state = state.clone();
    let cloned_auth = auth.clone();
    let waiter = tokio::spawn(async move {
        request(cloned_state,&cloned_auth,Method::POST,"/api/v1/plugin-marketplace/v3/installations",json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"slow-install"})).await
    });
    let mut observed = None;
    for _ in 0..100 {
        let (_, jobs) = request(
            state.clone(),
            &auth,
            Method::GET,
            "/api/v1/plugin-marketplace/v3/jobs",
            json!({}),
        )
        .await;
        if let Some(job) = jobs["items"].as_array().and_then(|items| items.first()) {
            if job["stage"] == "verifying" {
                observed = Some(job["id"].as_str().unwrap().to_owned());
                break;
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    let id = observed.expect("visible durable verifying stage");
    waiter.abort();
    let _ = waiter.await;
    let mut finished = None;
    for _ in 0..200 {
        let (_, job) = request(
            state.clone(),
            &auth,
            Method::GET,
            &format!("/api/v1/plugin-marketplace/v3/jobs/{id}"),
            json!({}),
        )
        .await;
        if job["status"] == "succeeded" {
            finished = Some(job);
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    let job = finished.expect("detached installation finishes");
    let installation_id = job["result"]["id"].as_str().unwrap();
    request(
        state.clone(),
        &auth,
        Method::POST,
        &format!("/api/v1/plugin-marketplace/v3/installations/{installation_id}/uninstall"),
        json!({"idempotency_key":"cleanup"}),
    )
    .await;
    std::fs::remove_dir_all(directory).unwrap();
}

#[tokio::test]
async fn slow_hook_keeps_snapshot_across_update_and_uninstall_until_completion() {
    for action in ["update", "uninstall"] {
        let (state, auth, directory) = fixture();
        let source_path = directory.join("source");
        package::snapshot(&example().join("plugins/marketplace-demo"), &source_path).unwrap();
        let started = directory.join("hook-started");
        let release = directory.join("hook-release");
        let observed = directory.join("hook-observed");
        std::fs::write(source_path.join("scripts/slow_hook.py"), "import pathlib,sys,time\nroot=pathlib.Path(__file__).resolve().parent.parent\npathlib.Path(sys.argv[1]).touch()\nwhile not pathlib.Path(sys.argv[2]).exists(): time.sleep(.01)\npathlib.Path(sys.argv[3]).write_text((root/'version-marker').read_text())\n").unwrap();
        std::fs::write(source_path.join("version-marker"), "old-version").unwrap();
        let command = format!(
            "python3 ${{PLUGIN_ROOT}}/scripts/slow_hook.py '{}' '{}' '{}'",
            started.display(),
            release.display(),
            observed.display()
        );
        std::fs::write(
            source_path.join("hooks/hooks.json"),
            json!({"hooks":[{"event":"session_start","command":command,"timeout_seconds":30}]})
                .to_string(),
        )
        .unwrap();
        let (_, source) = request(
            state.clone(),
            &auth,
            Method::POST,
            "/api/v1/plugin-marketplace/v3/sources",
            json!({"name":"Slow hook","kind":"local","location":source_path,"trusted":true}),
        )
        .await;
        let (_, preview) = request(
            state.clone(),
            &auth,
            Method::POST,
            "/api/v1/plugin-marketplace/v3/preflight",
            json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
        )
        .await;
        let (_, installed) = request(state.clone(), &auth, Method::POST, "/api/v1/plugin-marketplace/v3/installations", json!({"preflight_id":preview["id"],"approved_permissions":preview["permissions"],"idempotency_key":"install"})).await;
        assert_eq!(installed["status"], "enabled", "{installed}");
        let id = installed["id"].as_str().unwrap();
        let old_snapshot = load(&auth_root(&state, &auth).unwrap())
            .unwrap()
            .installations[0]
            .package
            .root
            .clone();
        let captured = hooks::Hooks::capture(
            &state,
            &auth.workspace.tenant_id,
            &auth.workspace.project_id,
        )
        .unwrap();
        let running = tokio::spawn(async move { captured.run("session_start").await });
        tokio::time::timeout(std::time::Duration::from_secs(5), async {
            while !started.exists() {
                tokio::time::sleep(std::time::Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap();
        let body = if action == "update" {
            let manifest_path = source_path.join(".codex-plugin/plugin.json");
            let mut manifest = package::bounded_json(&manifest_path).unwrap();
            manifest["version"] = json!("2.0.0");
            std::fs::write(manifest_path, manifest.to_string()).unwrap();
            std::fs::write(source_path.join("version-marker"), "new-version").unwrap();
            let (_, next) = request(
                state.clone(),
                &auth,
                Method::POST,
                "/api/v1/plugin-marketplace/v3/preflight",
                json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
            )
            .await;
            json!({"preflight_id":next["id"],"approved_permissions":next["permissions"],"idempotency_key":"update"})
        } else {
            json!({"idempotency_key":"uninstall"})
        };
        let (status, changed) = request(
            state.clone(),
            &auth,
            Method::POST,
            &format!("/api/v1/plugin-marketplace/v3/installations/{id}/{action}"),
            body,
        )
        .await;
        assert_eq!(status, StatusCode::OK, "{changed}");
        assert!(
            old_snapshot.exists(),
            "active slow hook must retain its original snapshot"
        );
        std::fs::write(&release, b"continue").unwrap();
        tokio::time::timeout(std::time::Duration::from_secs(5), running)
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        assert_eq!(std::fs::read_to_string(&observed).unwrap(), "old-version");
        assert!(
            !old_snapshot.exists(),
            "final hook lease reclaims its retired snapshot"
        );
        if action == "update" {
            request(
                state.clone(),
                &auth,
                Method::POST,
                &format!("/api/v1/plugin-marketplace/v3/installations/{id}/uninstall"),
                json!({"idempotency_key":"cleanup"}),
            )
            .await;
        }
        let _ = std::fs::remove_dir_all(directory);
    }
}

#[tokio::test]
async fn slow_app_resource_read_survives_uninstall_until_final_catalog_lease_releases() {
    let (state, auth, directory) = fixture();
    let source_root = directory.join("slow-app-source");
    package::snapshot(&example().join("plugins/marketplace-demo"), &source_root).unwrap();
    let script = source_root.join("scripts/demo_mcp.py");
    let content = std::fs::read_to_string(&script).unwrap().replace(
        "        return {\"contents\": [{**RESOURCE, \"text\": HTML}]}",
        "        import pathlib, time\n        root = pathlib.Path(__file__).parent\n        if (root / 'block-resource').exists():\n            (root / 'resource-entered').write_text('entered')\n            deadline = time.monotonic() + 8\n            while not (root / 'release-resource').exists():\n                if time.monotonic() > deadline:\n                    raise ValueError('test resource release timed out')\n                time.sleep(0.01)\n            return {\"contents\": [{**RESOURCE, \"text\": (root / 'owned-app.html').read_text()}]}\n        return {\"contents\": [{**RESOURCE, \"text\": HTML}]}",
    );
    assert!(content.contains("resource-entered"));
    std::fs::write(&script, content).unwrap();
    std::fs::write(
        source_root.join("scripts/owned-app.html"),
        "<main>leased old app</main>",
    )
    .unwrap();
    let (_, source) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/sources",
        json!({"name":"Slow App","kind":"local","location":source_root,"trusted":true}),
    )
    .await;
    let (_, preflight) = request(
        state.clone(),
        &auth,
        Method::POST,
        "/api/v1/plugin-marketplace/v3/preflight",
        json!({"source_id":source["id"],"plugin_id":"marketplace-demo"}),
    )
    .await;
    let (_, installed) = request(state.clone(), &auth, Method::POST,
        "/api/v1/plugin-marketplace/v3/installations",
        json!({"preflight_id":preflight["id"],"approved_permissions":preflight["permissions"],"idempotency_key":"slow-app-install"})).await;
    assert_eq!(installed["status"], "enabled", "{installed}");
    let snapshot = load(&auth_root(&state, &auth).unwrap())
        .unwrap()
        .installations[0]
        .package
        .root
        .clone();
    let scope = super::super::mcp_supervisor::McpScope {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
    };
    let (servers, lease) = state.mcp_supervisor.acquire_catalog(&scope).unwrap();
    let server_id = servers[0].id.clone();
    std::fs::write(snapshot.join("scripts/block-resource"), "block").unwrap();
    let reader = state.mcp_supervisor.clone();
    let read_scope = scope.clone();
    let read_id = server_id.clone();
    let read = tokio::spawn(async move {
        let contents = reader
            .read_resource_pinned(&lease, &read_scope, &read_id, "ui://demo/example.html")
            .await;
        (contents, lease)
    });
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        while !snapshot.join("scripts/resource-entered").exists() {
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("real resources/read reached the blocking point");
    let (status, removed) = request(
        state.clone(),
        &auth,
        Method::POST,
        &format!(
            "/api/v1/plugin-marketplace/v3/installations/{}/uninstall",
            installed["id"].as_str().unwrap()
        ),
        json!({"idempotency_key":"slow-app-uninstall"}),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{removed}");
    assert_eq!(removed["status"], "uninstalled");
    assert!(
        !read.is_finished(),
        "uninstall overlapped the actual resource request"
    );
    assert!(snapshot.join("scripts/owned-app.html").is_file());
    assert!(state
        .mcp_supervisor
        .server(&scope, &server_id)
        .unwrap()
        .is_some());
    assert!(state.mcp_supervisor.list_apps(&scope).unwrap().is_empty());
    assert!(state
        .mcp_supervisor
        .list_servers(&scope)
        .unwrap()
        .is_empty());
    std::fs::write(snapshot.join("scripts/release-resource"), "release").unwrap();
    let (contents, final_lease) = tokio::time::timeout(std::time::Duration::from_secs(5), read)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(contents.unwrap()[0]["text"], "<main>leased old app</main>");
    assert!(
        snapshot.exists(),
        "completed read still holds its catalog lease"
    );
    drop(final_lease);
    assert!(!snapshot.exists(), "last lease releases the retired files");
    assert!(state
        .mcp_supervisor
        .server(&scope, &server_id)
        .unwrap()
        .is_none());
    std::fs::remove_dir_all(directory).unwrap();
}
