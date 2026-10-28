//! The host owns short locked-use leases; JavaScript cannot mint or renew them.
use super::super::platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2;
use super::*;
use std::time::Duration;

#[cfg(test)]
#[path = "locked_use_execution_tests.rs"]
mod execution_tests;

#[cfg(test)]
#[path = "locked_use_projection_tests.rs"]
mod projection_tests;

#[derive(Default)]
pub(super) struct Leases {
    active: Mutex<BTreeMap<String, (String, Arc<AtomicBool>)>>,
    // Latest host-issued display origin per session; never execution authority.
    display_issued: Mutex<BTreeMap<String, (String, String)>>,
    status: Mutex<Option<Value>>,
}
impl Leases {
    pub(super) fn status(&self) -> Option<Value> {
        let mut status = self.status.lock().ok()?.clone()?;
        // Device setup is shared, but another conversation's run identity is not.
        if let Some(status) = status.as_object_mut() {
            for key in ["session_id", "run_id", "generation", "revoked_binding"] {
                status.remove(key);
            }
        }
        Some(status)
    }
    pub(super) fn session_status(&self, session_id: &str, run_id: &str) -> Option<Value> {
        let active = self.active.lock().ok()?;
        let display_issued = self.display_issued.lock().ok()?;
        let status = self.status.lock().ok()?;
        let status = status.as_ref()?;
        (active_binding_matches(status, session_id, run_id, active.get(session_id))
            || terminal_binding_matches(status, session_id, run_id, display_issued.get(session_id)))
        .then(|| status.clone())
    }
    /// Model-visible status keeps only this caller's validated display identities.
    pub(super) fn caller_status(&self, session_id: &str, run_id: &str, value: &Value) -> Value {
        let mut filtered = value.clone();
        let Some(output) = filtered.as_object_mut() else {
            return Value::Null;
        };
        for key in ["session_id", "run_id", "generation", "revoked_binding"] {
            output.remove(key);
        }
        let Ok(active) = self.active.lock() else {
            return filtered;
        };
        let Ok(display_issued) = self.display_issued.lock() else {
            return filtered;
        };
        if active_binding_matches(value, session_id, run_id, active.get(session_id)) {
            for key in ["session_id", "run_id", "generation"] {
                output.insert(key.into(), value[key].clone());
            }
        } else if terminal_binding_matches(
            value,
            session_id,
            run_id,
            display_issued.get(session_id),
        ) {
            output.insert("revoked_binding".into(), value["revoked_binding"].clone());
        }
        filtered
    }
    fn record_issued(
        &self,
        session_id: &str,
        run_id: &str,
        generation: &str,
        stopped: &AtomicBool,
    ) {
        let mut display_issued = self
            .display_issued
            .lock()
            .expect("locked-use display origins");
        // Session closure sets stopped before forgetting under this same mutex.
        if !stopped.load(Ordering::SeqCst) {
            display_issued.insert(session_id.into(), (run_id.into(), generation.into()));
        }
    }
    pub(super) fn forget_display(&self, session_id: &str) {
        self.display_issued
            .lock()
            .expect("locked-use display origins")
            .remove(session_id);
    }
    fn record_status(&self, value: &Value) {
        let Ok(mut status) = self.status.lock() else {
            return;
        };
        // Lease replies omit setup fields. Runtime fields are a fresh snapshot:
        // a missing binding, phase or failure must never inherit an older run.
        let mut current = json!({});
        if let Some(previous) = status.as_ref() {
            for key in [
                "installed",
                "supported_os",
                "accessibility",
                "input_monitoring",
            ] {
                if let Some(value) = previous.get(key) {
                    current[key] = value.clone();
                }
            }
        }
        for key in [
            "installed",
            "supported_os",
            "accessibility",
            "input_monitoring",
            "state",
            "enabled",
            "phase",
            "reason",
            "requires_manual_unlock",
            "failure",
            "session_id",
            "run_id",
            "generation",
            "revoked_binding",
        ] {
            if let Some(value) = value.get(key) {
                current[key] = value.clone();
            }
        }
        *status = Some(current);
    }
    fn remove(&self, session: &str) -> Option<String> {
        self.active
            .lock()
            .expect("locked-use leases")
            .remove(session)
            .map(|(generation, live)| {
                live.store(false, Ordering::SeqCst);
                generation
            })
    }
}

fn active_binding_matches(
    value: &Value,
    session_id: &str,
    run_id: &str,
    active: Option<&(String, Arc<AtomicBool>)>,
) -> bool {
    active.is_some_and(|(generation, live)| {
        !generation.is_empty()
            && live.load(Ordering::SeqCst)
            && value["enabled"].as_bool() == Some(true)
            && value["state"].as_str() == Some("active")
            && value.get("revoked_binding").is_none()
            && value["session_id"].as_str() == Some(session_id)
            && value["run_id"].as_str() == Some(run_id)
            && value["generation"].as_str() == Some(generation.as_str())
    })
}

fn terminal_binding_matches(
    value: &Value,
    session_id: &str,
    run_id: &str,
    issued: Option<&(String, String)>,
) -> bool {
    if value["enabled"].as_bool() != Some(false)
        || ["session_id", "run_id", "generation"]
            .iter()
            .any(|key| value.get(key).is_some())
    {
        return false;
    }
    let Some((issued_run, generation)) = issued else {
        return false;
    };
    let Some(revoked) = value.get("revoked_binding") else {
        return false;
    };
    if issued_run != run_id
        || generation.is_empty()
        || revoked["session_id"].as_str() != Some(session_id)
        || revoked["run_id"].as_str() != Some(run_id)
        || revoked["generation"].as_str() != Some(generation.as_str())
    {
        return false;
    }
    let manual_unlock = match value["state"].as_str() {
        Some("available") => false,
        Some("suppressed" | "failed") => true,
        _ => return false,
    };
    value["requires_manual_unlock"].as_bool() == Some(manual_unlock)
        && (value["phase"].as_str() == Some("relocking")
            || (value["phase"].as_str() == Some("idle") && manual_unlock))
}

pub(super) async fn probe(state: &LocalRuntimeState) -> Result<Value, String> {
    let status = state
        .computer_use
        .client()?
        .request("locked_use_probe", json!({}))
        .await
        .map_err(|_| "cua_locked_use_status_unavailable")?;
    state.computer_use.locked_use.record_status(&status);
    Ok(status)
}

/// Administrator setup is only exposed in device management, never as a model tool.
pub(super) async fn manage(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    install: bool,
    revision: u64,
) -> Result<(), String> {
    let _gate = state
        .computer_use
        .management
        .try_lock()
        .map_err(|_| "cua_device_busy")?;
    let instance = store::instance(&*state.session_store.connection()?, owner)?;
    if instance.revision != revision {
        return Err("cua_revision_conflict".into());
    }
    state.computer_use.stop_owner(state, owner, "revoked").await;
    let context = super::api::settings_context(owner, instance.input_mode);
    let client = state.computer_use.client()?;
    let result = client
        .request_in_session(
            &context,
            if install {
                "locked_use_install"
            } else {
                "locked_use_uninstall"
            },
            json!({}),
        )
        .await;
    let _ = client.stop_session(&context.session_id).await;
    let _ = client.end_session(&context.session_id).await;
    result.map_err(|error| match error {
        agistack_adapters_cua::CuaError::Request { ref kind, .. }
            if kind == "administrator_authorization_cancelled" =>
        {
            "cua_locked_use_administrator_authorization_cancelled".to_owned()
        }
        error => format!("cua_locked_use_setup_failed: {error}"),
    })?;
    let status = probe(state).await?;
    if status["installed"] != install {
        return Err("cua_locked_use_setup_unverified".into());
    }
    if !install {
        let db = state.session_store.connection()?;
        let current = store::instance(&db, owner)?;
        if current.locked_use {
            store::update(
                &db,
                owner,
                current.revision,
                "configure",
                Some(("locked_use", false)),
            )?;
        }
    }
    state.computer_use.shutdown_if_idle().await;
    Ok(())
}

pub(super) async fn call(
    state: &Arc<LocalRuntimeState>,
    session: &Arc<Session>,
    native: &NativeIdentity,
    factory: &Arc<ActivePlatformPluginGenerationLeaseV2>,
    client: &Arc<CuaClient>,
    input: &Value,
) -> CoreResult<ToolResult> {
    let enabled = input["enabled"]
        .as_bool()
        .ok_or_else(|| CoreError::Tool("cua_locked_use_enabled_required".into()))?;
    if !enabled {
        let generation = state
            .computer_use
            .locked_use
            .remove(&session.context.session_id);
        let mut params = json!({"run_id":session.context.run_id});
        if let Some(generation) = generation {
            params["generation"] = json!(generation);
        }
        let result = client
            .request_in_session(&session.context, "locked_use_disable", params)
            .await
            .map_err(|error| CoreError::Tool(error.to_string()))?;
        state.computer_use.locked_use.record_status(&result);
        return Ok(ToolResult::text(
            state
                .computer_use
                .locked_use
                .caller_status(
                    &session.context.session_id,
                    &session.context.run_id,
                    &result,
                )
                .to_string(),
        ));
    }
    let cell = crate::local_runtime::execution_authority::current_cell_lifetime();
    let run = if session.cloud.is_none() {
        Some(
            state
                .session_store
                .run(&session.context.run_id)
                .map_err(CoreError::Storage)?
                .ok_or_else(|| CoreError::Tool("cua_locked_use_run_missing".into()))?,
        )
    } else {
        None
    };
    if !current(state, session, native, factory, run.as_ref(), cell.as_ref()) {
        return Err(CoreError::Tool("cua_locked_use_run_inactive".into()));
    }
    let generation = Uuid::new_v4().to_string();
    let live = Arc::new(AtomicBool::new(true));
    {
        let mut leases = state
            .computer_use
            .locked_use
            .active
            .lock()
            .expect("locked-use leases");
        // Use the same active -> display lock order as snapshot projection.
        // Every new attempt replaces old display attribution, including rejection.
        state.computer_use.locked_use.record_issued(
            &session.context.session_id,
            &session.context.run_id,
            &generation,
            &session.stopped,
        );
        if leases.contains_key(&session.context.session_id) {
            return Err(CoreError::Tool("cua_locked_use_already_active".into()));
        }
        leases.insert(
            session.context.session_id.clone(),
            (generation.clone(), live.clone()),
        );
    }
    let params = json!({"run_id":session.context.run_id,"generation":generation,"ttl_ms":5000});
    let result = client
        .request_in_session(&session.context, "locked_use_enable", params.clone())
        .await;
    let result = match result {
        Ok(result) if result["enabled"] == true => result,
        Ok(result) => {
            state.computer_use.locked_use.record_status(&result);
            state
                .computer_use
                .locked_use
                .remove(&session.context.session_id);
            return Err(CoreError::Tool("cua_locked_use_not_enabled".into()));
        }
        Err(error) => {
            state
                .computer_use
                .locked_use
                .remove(&session.context.session_id);
            return Err(CoreError::Tool(error.to_string()));
        }
    };
    state.computer_use.locked_use.record_status(&result);
    let output = state.computer_use.locked_use.caller_status(
        &session.context.session_id,
        &session.context.run_id,
        &result,
    );
    let weak = Arc::downgrade(state);
    let session = session.clone();
    let native = native.clone();
    let factory = factory.clone();
    let local_identity = match &native {
        NativeIdentity::Local(identity) => Some(identity.clone()),
        NativeIdentity::Cloud(_) => None,
    };
    let client = client.clone();
    let renew = async move {
        loop {
            tokio::time::sleep(Duration::from_secs(1)).await;
            let Some(state) = weak.upgrade() else {
                break;
            };
            if !live.load(Ordering::SeqCst)
                || !current(
                    &state,
                    &session,
                    &native,
                    &factory,
                    run.as_ref(),
                    cell.as_ref(),
                )
            {
                break;
            }
            let renewal = tokio::time::timeout(
                Duration::from_millis(900),
                client.request_in_session(&session.context, "locked_use_renew", params.clone()),
            )
            .await;
            if let Ok(Ok(status)) = &renewal {
                state.computer_use.locked_use.record_status(status);
            }
            if !matches!(renewal, Ok(Ok(ref result)) if result["enabled"] == true && result["generation"] == generation)
            {
                break;
            }
        }
        live.store(false, Ordering::SeqCst);
        let disabled = tokio::time::timeout(
            Duration::from_secs(2),
            client.request_in_session(&session.context, "locked_use_disable", params),
        )
        .await;
        if let Some(state) = weak.upgrade() {
            if let Ok(Ok(status)) = disabled {
                state.computer_use.locked_use.record_status(&status);
            }
            let mut leases = state
                .computer_use
                .locked_use
                .active
                .lock()
                .expect("locked-use leases");
            if leases
                .get(&session.context.session_id)
                .is_some_and(|(current, _)| current == &generation)
            {
                leases.remove(&session.context.session_id);
            }
        }
    };
    tokio::spawn(async move {
        // Spawned tasks do not inherit the caller's task-local run authority.
        if let Some(identity) = local_identity {
            identity.scope(renew).await;
        } else {
            renew.await;
        }
    });
    Ok(ToolResult::text(output.to_string()))
}

fn current(
    state: &LocalRuntimeState,
    session: &Session,
    native: &NativeIdentity,
    factory: &ActivePlatformPluginGenerationLeaseV2,
    expected: Option<&DesktopRun>,
    cell: Option<&Arc<AtomicBool>>,
) -> bool {
    if session.stopped.load(Ordering::SeqCst)
        || session.paused.load(Ordering::SeqCst)
        || !native.current(state)
        || cell.is_some_and(|live| !live.load(Ordering::SeqCst))
        || !cloud::factory_lease(state, &session.owner)
            .is_ok_and(|current| current.descriptor() == factory.descriptor())
    {
        return false;
    }
    {
        let Ok(db) = state.session_store.connection() else {
            return false;
        };
        if !store::instance(&db, &session.owner).is_ok_and(|instance| {
            instance.installed
                && instance.enabled
                && instance.locked_use
                && instance.revision == session.revision
        }) {
            return false;
        }
    }
    if let Some(expected) = expected {
        if !state.session_store.run(&expected.id).is_ok_and(|run| {
            run.is_some_and(|run| {
                run.revision == expected.revision
                    && run.status == super::super::authority_store::DesktopRunStatus::Running
                    && run.environment == expected.environment
                    && run.permission_profile == expected.permission_profile
            })
        }) {
            return false;
        }
        if state.control_for_run(expected).is_some_and(|control| {
            control.directive.load(Ordering::Acquire) != super::super::LocalRunControl::CONTINUE
        }) {
            return false;
        }
    }
    true
}

#[cfg(test)]
mod tests {
    use super::super::management_lifecycle_tests::Helper;
    use super::*;

    #[tokio::test]
    async fn component_setup_reports_installer_failure_separately_from_cancellation() {
        for (kind, expected) in [
            (
                "administrator_authorization_cancelled",
                "cua_locked_use_administrator_authorization_cancelled",
            ),
            (
                "locked_use_setup_failed",
                "cua_locked_use_setup_failed: cua_request_failed(locked_use_setup_failed): installer path rejected",
            ),
        ] {
            let helper = Helper::new(false);
            std::fs::write(
                helper.root.join("locked_use_error"),
                json!({"kind":kind,"message":"installer path rejected"}).to_string(),
            )
            .unwrap();
            let state = crate::local_runtime::tests::test_state("cua-lock-install-error");
            state
                .computer_use
                .client
                .set(helper.client.clone())
                .ok()
                .unwrap();
            let owner = super::super::tests::owner(&state);
            let operation = serde_json::from_value::<api::ManagementRequest>(
                json!({"action":"locked_use_install","expected_revision":0}),
            )
            .unwrap();
            assert_eq!(
                api::operation(&state, &owner, operation).await.unwrap_err(),
                expected
            );
            let requests = helper.requests();
            assert!(requests.iter().any(|call| call["method"] == "stop_session"));
            assert!(requests.iter().any(|call| call["method"] == "end_session"));
            assert!(!helper.root.join("locked_use_installed").exists());
            helper.client.shutdown().await;
            std::fs::remove_dir_all(&helper.root).unwrap();
        }
    }

    #[tokio::test]
    async fn component_setup_and_configuration_never_mint_an_execution_lease() {
        let helper = Helper::new(false);
        let state = crate::local_runtime::tests::test_state("cua-lock-component");
        state
            .computer_use
            .client
            .set(helper.client.clone())
            .ok()
            .unwrap();
        let owner = super::super::tests::owner(&state);
        let operation =
            |value: Value| serde_json::from_value::<api::ManagementRequest>(value).unwrap();
        assert!(api::operation(&state,&owner,operation(json!({"action":"configure","capability":"locked_use","enabled":true,"expected_revision":0}))).await.is_err());
        let installed = api::operation(
            &state,
            &owner,
            operation(json!({"action":"locked_use_install","expected_revision":0})),
        )
        .await
        .unwrap();
        assert_eq!(installed["locked_use"]["installed"], true);
        assert_eq!(installed["instance"]["locked_use"], false);
        let enabled = api::operation(&state,&owner,operation(json!({"action":"configure","capability":"locked_use","enabled":true,"expected_revision":0}))).await.unwrap();
        assert_eq!(enabled["instance"]["locked_use"], true);
        assert_eq!(enabled["locked_use"]["enabled"], false);
        let before = helper.requests().len();
        assert!(
            api::operation(
                &state,
                &owner,
                operation(json!({"action":"locked_use_uninstall","expected_revision":0}))
            )
            .await
            .is_err()
        );
        assert_eq!(helper.requests().len(), before);
        let removed = api::operation(
            &state,
            &owner,
            operation(json!({"action":"locked_use_uninstall","expected_revision":1})),
        )
        .await
        .unwrap();
        assert_eq!(removed["locked_use"]["installed"], false);
        assert_eq!(removed["instance"]["locked_use"], false);
        assert!(!helper.requests().iter().any(|call| matches!(
            call["method"].as_str(),
            Some("locked_use_enable" | "locked_use_renew")
        )));
        helper.client.shutdown().await;
        std::fs::remove_dir_all(&helper.root).unwrap();
    }

    #[test]
    fn public_component_status_does_not_expose_another_tasks_identity() {
        let leases = Leases::default();
        leases.record_status(&json!({"installed":true,"state":"active","session_id":"private","run_id":"private","generation":"private"}));
        leases.record_status(&json!({"enabled":true,"phase":"guarded"}));
        let status = leases.status().unwrap();
        assert_eq!(status["installed"], true);
        assert_eq!(status["phase"], "guarded");
        assert!(!status.to_string().contains("private"));
    }
}
