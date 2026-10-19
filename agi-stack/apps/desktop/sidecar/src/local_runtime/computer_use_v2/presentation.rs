//! Identity-bound native status and decorative artifacts, separate from model media.
use super::*;

pub(super) fn update(session: &Session, phase: &str, extra: Option<&Value>) {
    if let Ok(mut value) = session.presentation.lock() {
        if session.stopped.load(Ordering::SeqCst) && phase != "stopped" {
            return;
        }
        if session.paused.load(Ordering::SeqCst) && !matches!(phase, "paused" | "stopped") {
            return;
        }
        value["phase"] = json!(phase);
        if !matches!(phase, "focus_required" | "error") {
            value["error_code"] = Value::Null;
        }
        if phase != "paused" {
            value["resume_blocked_reason"] = Value::Null;
        }
        value["can_resume"] = json!(false);
        value["updated_at"] = json!(chrono::Utc::now().to_rfc3339());
        if let Some(extra) = extra {
            for field in [
                "target",
                "app_icon",
                "preview",
                "error_code",
                "can_resume",
                "resume_blocked_reason",
            ] {
                if let Some(field_value) = extra.get(field) {
                    value[field] = field_value.clone();
                }
            }
        }
    }
}

pub(super) fn resolved(session: &Session, result: &Value) {
    let mut target = json!({"app_id":result.get("app_id").unwrap_or(&result["app"]),"display_name":result["display_name"],
        "process_id":result["process_id"],"identity_digest":result["identity_digest"]});
    let changed = session
        .presentation
        .lock()
        .map(|p| {
            let previous = &p["target"];
            let changed = ["app_id", "process_id", "identity_digest"]
                .iter()
                .any(|field| previous[field] != target[field]);
            if !changed {
                for field in ["window_id", "window_title"] {
                    if let Some(value) = previous.get(field) {
                        target[field] = value.clone();
                    }
                }
            }
            changed
        })
        .unwrap_or(true);
    let mut extra = json!({"target":target,"app_icon":result.get("app_icon")});
    if changed {
        extra["preview"] = Value::Null;
    }
    update(session, "idle", Some(&extra));
}

pub(super) fn observed(session: &Session, output: &Value) {
    let mut extra = output.clone();
    if let Some(image) = output
        .get("screenshot")
        .filter(|image| image.get("artifact_id").is_some())
    {
        let mut preview = image.clone();
        for field in ["snapshot_id", "window_id"] {
            preview[field] = output[field].clone();
        }
        preview["observed_at"] = json!(chrono::Utc::now().to_rfc3339());
        extra["preview"] = preview;
    } else {
        extra["preview"] = Value::Null;
    }
    update(session, "idle", Some(&extra));
}

fn awaiting_permission(state: &LocalRuntimeState, session: &Session) -> bool {
    let grants = state
        .session_store
        .connection()
        .and_then(|db| store::grants(&db, &session.owner));
    grants.is_ok_and(|grants| {
        state
            .computer_use
            .pending_for(&session.owner)
            .iter()
            .any(|pending| {
                pending.session_id == session.context.session_id
                    && consent::needs_approval(pending, &grants)
            })
    })
}

pub(super) fn listen(state: &Arc<LocalRuntimeState>, client: &Arc<CuaClient>) {
    if state
        .computer_use
        .status_listener
        .swap(true, Ordering::SeqCst)
    {
        return;
    }
    let mut receiver = client.subscribe_native_status();
    let weak = Arc::downgrade(state);
    tokio::spawn(async move {
        let mut tick = tokio::time::interval(tokio::time::Duration::from_secs(1));
        loop {
            let received = tokio::select! {
                event=receiver.recv()=>event,
                _=tick.tick()=> {
                    let Some(state)=weak.upgrade() else {return;};
                    let sessions=state.computer_use.sessions.lock().map(|sessions|sessions.values().filter(|session|session.paused.load(Ordering::SeqCst)).cloned().collect::<Vec<_>>()).unwrap_or_default();
                    for session in sessions {
                        let allowed=resume_allowed(&state,&session);
                        let changed=session.presentation.lock().map(|p|p["can_resume"]!=allowed.is_ok()||p["resume_blocked_reason"]!=json!(allowed.err())).unwrap_or(false);
                        if changed {refresh_resume(&state,&session).await;}
                    }
                    continue;
                }
            };
            let event = match received {
                Ok(event) => event,
                Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                    // Losing a native user-stop receipt must fail closed.
                    if let Some(state) = weak.upgrade() {
                        state.computer_use.shutdown(&state).await;
                    }
                    continue;
                }
                Err(_) => return,
            };
            let Some(state) = weak.upgrade() else {
                return;
            };
            let session = state
                .computer_use
                .sessions
                .lock()
                .ok()
                .and_then(|sessions| sessions.get(&event.context.session_id).cloned());
            let Some(session) = session.filter(|session| session.context == event.context) else {
                continue;
            };
            if !event.recordings.is_empty() {
                if recordings::ingest(
                    &state,
                    &session.owner,
                    &session.context,
                    &json!({"recordings":event.recordings}),
                )
                .await
                .is_err()
                {
                    tracing::warn!(
                        code = "cua_recording_status_deferred",
                        "Native recording status could not be persisted"
                    );
                }
            }
            if event.user_action.as_deref() == Some("audio_stop") {
                // Stopping audio does not resume a paused desktop or stop its run.
                continue;
            }
            if !event.user_initiated
                && event.phase == "stopped"
                && session.cloud.is_some()
                && !session.stopped.load(Ordering::SeqCst)
                && session.resources.released()
                && awaiting_permission(&state, &session)
            {
                // An expired invocation releases native resources, not the
                // pending consent. Only a fresh claim may rebuild the session.
                update(&session, "awaiting_permission", None);
                continue;
            }
            if event.user_initiated && event.user_action.as_deref() == Some("resume") {
                // Keep receiving native Stop while the cloud authority request waits.
                tokio::spawn(async move {
                    let outcome =
                        pause_resume(&state, &session.owner, &session.context.session_id, true)
                            .await;
                    if outcome.is_err() {
                        refresh_resume(&state, &session).await;
                    }
                });
                continue;
            }
            if event.user_initiated && event.phase == "paused" {
                session.user_control.pause();
            }
            if event.user_initiated {
                session
                    .paused
                    .store(event.phase == "paused", Ordering::SeqCst);
            }
            update(&session, &event.phase, Some(&event.presentation()));
            if event.user_initiated && event.phase == "paused" {
                refresh_resume(&state, &session).await;
            }
            if event.user_initiated && event.phase == "stopped" {
                let _ = state
                    .computer_use
                    .user_stop(&state, &session.owner, Some(&session.context.session_id))
                    .await;
            }
        }
    });
}

pub(super) async fn pause_resume(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
    id: &str,
    resume: bool,
) -> Result<(), String> {
    let session = state
        .computer_use
        .sessions
        .lock()
        .map_err(|_| "cua_session_unavailable")?
        .get(id)
        .filter(|session| session.owner == *owner && !session.stopped.load(Ordering::SeqCst))
        .cloned()
        .ok_or("cua_session_not_found")?;
    if resume && !session.paused.load(Ordering::SeqCst) {
        return Err("cua_session_not_paused".into());
    }
    let pause_revision = session.user_control.pause_revision();
    let _dispatch = if resume {
        Some(session.dispatch.try_lock().map_err(|_| "cua_device_busy")?)
    } else {
        None
    };
    if resume {
        resume_allowed(state, &session).map_err(str::to_owned)?;
        if session.cloud.is_some() {
            cloud::authorize_resume(state, &session).await?;
        }
    }
    if !resume {
        session.user_control.pause();
        session.paused.store(true, Ordering::SeqCst);
        update(&session, "paused", None);
    }
    let resources = session.resources.gate.lock().await;
    if session.stopped.load(Ordering::SeqCst) {
        return Err("cua_session_stopped".into());
    }
    if resume {
        resume_allowed(state, &session).map_err(str::to_owned)?;
        if session.cloud.is_some() && !session.resources.current() {
            return Err("cua_cloud_lease_expired".into());
        }
    }
    let result = state
        .computer_use
        .client()?
        .request_in_session(
            &session.context,
            if resume {
                "resume_session"
            } else {
                "pause_session"
            },
            json!({}),
        )
        .await;
    result.map_err(|_| "cua_native_pause_unavailable")?;
    if !resume {
        recordings::refresh_session(state, &session).await;
    }
    if resume {
        if session.stopped.load(Ordering::SeqCst) {
            return Err("cua_session_stopped".into());
        }
        if let Err(error) = resume_allowed(state, &session) {
            resource_lease::release_native(state, &session).await;
            return Err(error.into());
        }
        if session.cloud.is_some() && !session.resources.current() {
            resource_lease::release_native(state, &session).await;
            return Err("cua_cloud_lease_expired".into());
        }
        if !session
            .user_control
            .resume_if_current(pause_revision, &session.paused)
        {
            // A newer explicit Pause wins even if the helper just acknowledged
            // Resume. Re-pause before releasing the native resource gate.
            if session.stopped.load(Ordering::SeqCst) {
                return Err("cua_session_stopped".into());
            }
            if state
                .computer_use
                .client()?
                .request_in_session(&session.context, "pause_session", json!({}))
                .await
                .is_err()
            {
                resource_lease::release_native(state, &session).await;
            }
            session.paused.store(true, Ordering::SeqCst);
            update(&session, "paused", None);
            return Err("cua_resume_superseded".into());
        }
        update(&session, "idle", None);
    } else {
        if session.stopped.load(Ordering::SeqCst) {
            return Err("cua_session_stopped".into());
        }
        // Pause can queue behind Resume while still interrupting in-flight input.
        session.user_control.pause();
        session.paused.store(true, Ordering::SeqCst);
        update(&session, "paused", None);
        drop(resources);
        refresh_resume(state, &session).await;
    }
    Ok(())
}

pub(super) fn resume_allowed(
    state: &LocalRuntimeState,
    session: &Session,
) -> Result<(), &'static str> {
    if session.stopped.load(Ordering::SeqCst) {
        return Err("cua_session_stopped");
    }
    let db = state
        .session_store
        .connection()
        .map_err(|_| "cua_authority_unavailable")?;
    let instance = store::instance(&db, &session.owner).map_err(|_| "cua_authority_unavailable")?;
    drop(db);
    if !instance.installed || !instance.enabled || instance.revision != session.revision {
        return Err("cua_authorization_revoked");
    }
    cloud::factory_lease(state, &session.owner).map_err(|_| "cua_factory_unavailable")?;
    if session.cloud.is_some() {
        return cloud::resume_available(state, session);
    }
    let conversation = state
        .session_store
        .conversation(&session.context.conversation_id)
        .map_err(|_| "cua_authority_unavailable")?
        .ok_or("cua_authorization_revoked")?;
    if conversation.tenant_id != session.owner.tenant_id
        || conversation.project_id != session.owner.project_id
    {
        return Err("cua_authorization_revoked");
    }
    let run = state
        .session_store
        .run(&session.context.run_id)
        .map_err(|_| "cua_authority_unavailable")?;
    if let Some(run) = run {
        if run.conversation_id != session.context.conversation_id
            || run.project_id != session.owner.project_id
            || run.status != super::super::DesktopRunStatus::Running
        {
            return Err("parent_run_not_running");
        }
        if let Some(child) = session.child.as_ref() {
            if child.revision != run.revision
                || !state.subagent_controls.plugin_execution_current(
                    &child.execution_id,
                    &session.context.conversation_id,
                    &run,
                    &child.subagent_id,
                    state.control_for_run(&run).as_ref(),
                )
            {
                return Err("cua_child_authority_revoked");
            }
        }
        if !state.control_for_run(&run).is_some_and(|control| {
            control.directive.load(Ordering::Acquire) == super::super::LocalRunControl::CONTINUE
        }) {
            return Err("parent_run_not_running");
        }
    } else {
        let active = state
            .agent_runs
            .lock()
            .map_err(|_| "cua_authority_unavailable")?;
        if !active
            .get(&session.context.conversation_id)
            .is_some_and(|active| {
                active.run_id.is_none()
                    && active.control.directive.load(Ordering::Acquire)
                        == super::super::LocalRunControl::CONTINUE
            })
        {
            return Err("parent_run_not_running");
        }
    }
    Ok(())
}
async fn refresh_resume(state: &Arc<LocalRuntimeState>, session: &Arc<Session>) {
    let _resources = session.resources.gate.lock().await;
    if session.stopped.load(Ordering::SeqCst) || !session.paused.load(Ordering::SeqCst) {
        return;
    }
    let allowed = resume_allowed(state, session);
    let extra = json!({"can_resume":allowed.is_ok(),"resume_blocked_reason":allowed.err()});
    update(session, "paused", Some(&extra));
    if session.cloud.is_some() && !session.resources.current() {
        return;
    }
    if let Ok(client) = state.computer_use.client() {
        let _=client.request_in_session(&session.context,"presentation_update",
            json!({"phase":"paused","can_resume":extra["can_resume"],"resume_blocked_reason":extra["resume_blocked_reason"]})).await;
    }
}

pub(super) fn record(state: &LocalRuntimeState, session: &Session) {
    let Ok(value) = session.presentation.lock() else {
        return;
    };
    if value.get("preview").is_none_or(Value::is_null) {
        return;
    }
    if let Ok(db) = state.session_store.connection() {
        let _=db.execute("INSERT INTO desktop_cua_presentations_v2 VALUES(?1,?2,?3,?4,?5) ON CONFLICT(user_id,tenant_id,project_id,device_id) DO UPDATE SET presentation_json=excluded.presentation_json",
            rusqlite::params![session.owner.user_id,session.owner.tenant_id,session.owner.project_id,session.owner.device_id,value.to_string()]);
    }
}
pub(super) fn recent(state: &LocalRuntimeState, owner: &Owner) -> Result<Option<Value>, String> {
    use rusqlite::OptionalExtension;
    let db = state.session_store.connection()?;
    let raw:Option<String>=db.query_row("SELECT presentation_json FROM desktop_cua_presentations_v2 WHERE user_id=?1 AND tenant_id=?2 AND project_id=?3 AND device_id=?4",
        rusqlite::params![owner.user_id,owner.tenant_id,owner.project_id,owner.device_id],|row|row.get(0)).optional().map_err(|_|"cua_presentation_unavailable")?;
    raw.map(|raw| serde_json::from_str(&raw).map_err(|_| "cua_presentation_invalid".to_owned()))
        .transpose()
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn target_icon_and_preview_do_not_cross_session_owners() {
        let session = Session {
            resources: Default::default(),
            dispatch: tokio::sync::Mutex::new(()),
            owner: Owner {
                user_id: "u".into(),
                tenant_id: "t".into(),
                project_id: "p".into(),
                device_id: "d".into(),
            },
            context: CuaCallContext {
                user_id: "u".into(),
                tenant_id: "t".into(),
                project_id: "p".into(),
                device_id: "d".into(),
                conversation_id: "c".into(),
                run_id: "r".into(),
                session_id: "s".into(),
            },
            revision: 1,
            stopped: AtomicBool::new(false),
            paused: AtomicBool::new(false),
            user_control: Default::default(),
            presentation: Mutex::new(json!({"phase":"idle"})),
            child: None,
            cloud: None,
        };
        observed(
            &session,
            &json!({"target":{"app_id":"fixture"},"app_icon":{"artifact_id":"icon"},"screenshot":{"artifact_id":"image","width":40,"height":50},"snapshot_id":"snapshot","window_id":"window"}),
        );
        let value = session.presentation.lock().unwrap().clone();
        assert_eq!(value["preview"]["snapshot_id"], "snapshot");
        assert_eq!(value["app_icon"]["artifact_id"], "icon");
        for timestamp in [&value["updated_at"], &value["preview"]["observed_at"]] {
            assert!(chrono::DateTime::parse_from_rfc3339(timestamp.as_str().unwrap()).is_ok());
        }
        session.paused.store(true, Ordering::SeqCst);
        update(&session, "paused", None);
        update(&session, "acting", None);
        assert_eq!(session.presentation.lock().unwrap()["phase"], "paused");
    }
    fn owned_session(
        owner: Owner,
        conversation_id: &str,
        run_id: &str,
        revision: u64,
    ) -> Arc<Session> {
        Arc::new(Session {
            context: CuaCallContext {
                user_id: owner.user_id.clone(),
                tenant_id: owner.tenant_id.clone(),
                project_id: owner.project_id.clone(),
                device_id: owner.device_id.clone(),
                conversation_id: conversation_id.into(),
                run_id: run_id.into(),
                session_id: "presentation-session".into(),
            },
            owner,
            resources: Default::default(),
            dispatch: tokio::sync::Mutex::new(()),
            revision,
            stopped: AtomicBool::new(false),
            paused: AtomicBool::new(false),
            user_control: Default::default(),
            presentation: Mutex::new(json!({"phase":"idle"})),
            child: None,
            cloud: None,
        })
    }
    #[test]
    fn recent_preview_retains_artifact_identity_after_stop_and_rejects_foreign_owner() {
        let state = crate::local_runtime::tests::test_state("cua-recent-preview");
        let owner = super::super::tests::owner(&state);
        let session = owned_session(owner.clone(), "conversation", "run", 0);
        observed(
            &session,
            &json!({"screenshot":{"artifact_id":"cua-image-owned","mime_type":"image/png","width":40,"height":50},"snapshot_id":"snapshot","window_id":"window"}),
        );
        update(&session, "stopped", None);
        record(&state, &session);
        let presentation = recent(&state, &owner).unwrap().unwrap();
        assert_eq!(presentation["preview"]["artifact_id"], "cua-image-owned");
        assert_eq!(presentation["phase"], "stopped");
        assert_eq!(presentation["can_resume"], false);
        let mut other = owner.clone();
        other.user_id = "foreign".into();
        assert!(recent(&state, &other).unwrap().is_none());
        other = owner;
        other.project_id = "foreign".into();
        assert!(recent(&state, &other).unwrap().is_none());
    }
    #[tokio::test]
    async fn pause_resume_requires_live_parent_and_invalidates_observation_without_recording() {
        let state = crate::local_runtime::tests::test_state("cua-presentation-resume");
        super::super::cloud_tests::publish_factory(&state, true).await;
        let (conversation, run) =
            crate::local_runtime::tests::seed_controlled_run(&state, "cua-presentation");
        let owner = Owner {
            user_id: "user".into(),
            tenant_id: conversation.tenant_id.clone(),
            project_id: conversation.project_id.clone(),
            device_id: state.session_store.installation_id().into(),
        };
        let instance = store::update(
            &state.session_store.connection().unwrap(),
            &owner,
            0,
            "enable",
            None,
        )
        .unwrap();
        let helper = super::super::management_lifecycle_tests::Helper::new(false);
        assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
        let session = owned_session(owner.clone(), &conversation.id, &run.id, instance.revision);
        state
            .computer_use
            .sessions
            .lock()
            .unwrap()
            .insert(session.context.session_id.clone(), session.clone());
        let control = state
            .claim_agent_run(&conversation.id, Some(&run.id))
            .unwrap();
        let host = CuaToolHost::new(helper.client.clone()).with_context(session.context.clone());
        host.call(
            "computer_get_app_state",
            r#"{"app":"pid:10","window_id":"window-1"}"#,
        )
        .await
        .unwrap();
        pause_resume(&state, &owner, &session.context.session_id, false)
            .await
            .unwrap();
        assert!(session.paused.load(Ordering::SeqCst));
        assert_eq!(
            session.presentation.lock().unwrap()["can_resume"],
            true,
            "{:?}",
            resume_allowed(&state, &session)
        );
        pause_resume(&state, &owner, &session.context.session_id, true)
            .await
            .unwrap();
        assert!(!session.paused.load(Ordering::SeqCst));
        assert!(
            host.call(
                "computer_click",
                r#"{"app":"pid:10","snapshot_id":"snapshot-round1","x":10,"y":20}"#
            )
            .await
            .is_err()
        );
        assert!(
            !helper
                .requests()
                .iter()
                .any(|r| r["method"] == "audio_start" || r["method"] == "perform_action")
        );
        pause_resume(&state, &owner, &session.context.session_id, false)
            .await
            .unwrap();
        control.request_pause();
        assert_eq!(
            resume_allowed(&state, &session),
            Err("parent_run_not_running")
        );
        assert!(
            pause_resume(&state, &owner, &session.context.session_id, true)
                .await
                .is_err()
        );
        let mut foreign = owner.clone();
        foreign.user_id = "foreign".into();
        assert!(
            pause_resume(&state, &foreign, &session.context.session_id, true)
                .await
                .is_err()
        );
        state
            .computer_use
            .close_session(&state, &session.context.session_id)
            .await;
        assert!(
            pause_resume(&state, &owner, &session.context.session_id, true)
                .await
                .is_err()
        );
        state.release_agent_run(&conversation.id);
    }
}
