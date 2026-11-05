//! Exercise local locked-use leases with mock IPC; no OS session is locked.
use super::*;
use crate::local_runtime::{
    authority_store::DesktopRunStatus,
    knowledge_authority_v2::agent_access::{self, RunAuthorization},
};
use std::{future::Future, sync::mpsc};

struct Fixture {
    state: Arc<LocalRuntimeState>,
    authorization: Arc<RunAuthorization>,
    native: NativeIdentity,
    factory: Arc<ActivePlatformPluginGenerationLeaseV2>,
    session: Arc<Session>,
    run: DesktopRun,
    helper: management_lifecycle_tests::Helper,
}

impl Fixture {
    async fn new() -> Self {
        let token = "locked-use-execution";
        let state = crate::local_runtime::tests::test_state(token);
        cloud_tests::publish_factory(&state, true).await;
        let auth = state
            .session_store
            .validate_session_credential(token, chrono::Utc::now().timestamp_millis())
            .unwrap()
            .unwrap();
        let owner = Owner {
            user_id: auth.user.user_id.clone(),
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
            device_id: state.session_store.installation_id().into(),
        };
        let helper = management_lifecycle_tests::Helper::new(false);
        assert!(state.computer_use.client.set(helper.client.clone()).is_ok());
        for request in [
            json!({"action":"locked_use_install","expected_revision":0}),
            json!({"action":"enable","expected_revision":0}),
            json!({"action":"configure","capability":"locked_use","enabled":true,"expected_revision":1}),
        ] {
            api::operation(&state, &owner, serde_json::from_value(request).unwrap())
                .await
                .unwrap();
        }
        let (conversation, run) =
            crate::local_runtime::tests::seed_controlled_run(&state, "locked-use-execution");
        assert_eq!(run.status, DesktopRunStatus::Running);
        let factory = cloud::factory_lease(&state, &owner).unwrap();
        let authorization = RunAuthorization::capture(
            auth,
            Some(factory.clone()),
            &conversation,
            &run.message_id,
            Some(&run.id),
        )
        .unwrap();
        let native = agent_access::scope(Some(authorization.clone()), async {
            tool_host(&state, &conversation, Some(&run)).unwrap();
            NativeIdentity::Local(
                PluginNativeIdentityV2::capture(&state, &conversation, Some(&run)).unwrap(),
            )
        })
        .await;
        let session = state
            .computer_use
            .sessions
            .lock()
            .unwrap()
            .values()
            .find(|session| session.context.run_id == run.id)
            .unwrap()
            .clone();
        Self {
            state,
            authorization,
            native,
            factory,
            session,
            run,
            helper,
        }
    }

    async fn enable(&self) {
        let output = agent_access::scope(Some(self.authorization.clone()), async {
            call(
                &self.state,
                &self.session,
                &self.native,
                &self.factory,
                &self.helper.client,
                &json!({"enabled":true}),
            )
            .await
            .unwrap()
        })
        .await;
        assert_eq!(
            serde_json::from_str::<Value>(&output.output_json).unwrap()["enabled"],
            true
        );
        assert_eq!(
            self.state
                .session_store
                .run(&self.run.id)
                .unwrap()
                .unwrap()
                .status,
            DesktopRunStatus::Running
        );
    }

    fn requests(&self, method: &str) -> Vec<Value> {
        self.helper
            .requests()
            .into_iter()
            .filter(|request| request["method"] == method)
            .collect()
    }

    async fn wait_for(&self, method: &str, count: usize) {
        tokio::time::timeout(Duration::from_secs(4), async {
            while self.requests(method).len() < count {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .unwrap_or_else(|_| {
            panic!(
                "expected {count} {method} requests; got {:?}",
                self.helper.requests()
            )
        });
    }

    async fn close(&self) {
        self.session.stopped.store(true, Ordering::SeqCst);
        self.wait_for("locked_use_disable", 1).await;
        self.helper.client.shutdown().await;
        std::fs::remove_dir_all(self.state.workspace_root.lock().unwrap().as_path()).unwrap();
    }

    async fn assert_renewal_stopped(&self) {
        self.wait_for("locked_use_disable", 1).await;
        let count = self.requests("locked_use_renew").len();
        tokio::time::sleep(Duration::from_millis(1100)).await;
        assert_eq!(self.requests("locked_use_renew").len(), count);
        assert!(self
            .state
            .computer_use
            .locked_use
            .active
            .lock()
            .unwrap()
            .is_empty());
    }

    async fn replace_factory(&self, enabled: bool) {
        let mut wire: Value = serde_json::from_str(include_str!(
            "../../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
        ))
        .unwrap();
        for entry in wire["entries"].as_array_mut().unwrap() {
            if entry["module_ref"] == module::MODULE_REF {
                entry["enabled"] = json!(enabled);
            }
        }
        wire["generation"] = json!(22);
        wire.as_object_mut().unwrap().remove("digest");
        wire["digest"] =
            json!(crate::local_runtime::tool_authority::canonical_json_digest(&wire).unwrap());
        let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string()).unwrap();
        let generation = crate::local_runtime::platform_plugin_sync_v2::desktop_loader(None, None)
            .stage(snapshot.clone())
            .await
            .unwrap();
        let retirement = self
            .state
            .platform_plugin_authority_v2
            .replace_local_baseline(&snapshot, &wire, generation);
        tokio::spawn(async move {
            retirement.dispose().await;
        });
    }
}

fn bounded(test: impl Future<Output = ()> + Send + 'static) {
    let (done, completed) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(test);
        done.send(()).unwrap();
    });
    // A Tokio deadline cannot preempt a synchronous database mutex deadlock.
    completed
        .recv_timeout(Duration::from_secs(15))
        .expect("locked-use worker must finish without blocking the session store");
    worker.join().unwrap();
}

#[test]
fn running_local_run_enables_and_renews_without_blocking_store() {
    bounded(async {
        let fixture = Fixture::new().await;
        fixture.enable().await;
        assert!(
            !fixture.native.current(&fixture.state),
            "the captured identity cannot authorize callers outside its scope"
        );
        fixture.wait_for("locked_use_renew", 2).await;
        let enable = fixture.requests("locked_use_enable");
        assert_eq!(enable.len(), 1);
        for renewal in fixture.requests("locked_use_renew") {
            assert_eq!(
                renewal["params"]["generation"],
                enable[0]["params"]["generation"]
            );
            assert_eq!(renewal["params"]["run_id"], fixture.run.id);
        }
        assert_eq!(
            fixture
                .state
                .session_store
                .run(&fixture.run.id)
                .unwrap()
                .unwrap()
                .revision,
            fixture.run.revision
        );
        assert!(fixture.requests("locked_use_disable").is_empty());
        fixture.close().await;
    });
}

#[test]
fn running_local_lease_stops_renewing_after_run_invalidation() {
    bounded(async {
        let fixture = Fixture::new().await;
        fixture.enable().await;
        fixture.wait_for("locked_use_renew", 1).await;
        fixture
            .state
            .session_store
            .transition_run(
                &fixture.run.id,
                fixture.run.revision,
                DesktopRunStatus::Cancelled,
                None,
                &crate::local_runtime::now_iso(),
            )
            .unwrap();
        fixture.assert_renewal_stopped().await;
        fixture.close().await;
    });
}

#[test]
fn running_local_lease_survives_cell_completion_until_explicit_run_release() {
    bounded(async {
        let fixture = Fixture::new().await;
        let cell = Arc::new(AtomicBool::new(true));
        crate::local_runtime::execution_authority::with_cell_lifetime(
            cell.clone(),
            fixture.enable(),
        )
        .await;
        fixture.wait_for("locked_use_renew", 1).await;
        cell.store(false, Ordering::SeqCst);
        fixture.wait_for("locked_use_renew", 3).await;
        assert!(fixture.requests("locked_use_disable").is_empty());
        fixture
            .state
            .computer_use
            .release_locked_run(&fixture.state, &fixture.run.id, "awaiting_human")
            .await;
        fixture.assert_renewal_stopped().await;
        fixture.close().await;
    });
}

#[test]
fn lease_is_revoked_for_every_non_running_run_state() {
    for status in [
        DesktopRunStatus::NeedsApproval,
        DesktopRunStatus::NeedsInput,
        DesktopRunStatus::Paused,
        DesktopRunStatus::ReadyReview,
        DesktopRunStatus::Disconnected,
    ] {
        bounded(async move {
            let fixture = Fixture::new().await;
            fixture.enable().await;
            let result = fixture
                .state
                .persist_authoritative_run_outcome(
                    &fixture.run,
                    status,
                    None,
                    &crate::local_runtime::now_iso(),
                )
                .await;
            // The fixture has no final checkpoint; ReadyReview quarantines the
            // run as disconnected, and must still revoke continuity immediately.
            if status != DesktopRunStatus::ReadyReview {
                result.unwrap();
            }
            fixture.assert_renewal_stopped().await;
            fixture.close().await;
        });
    }
}

#[test]
fn running_local_lease_stops_when_factory_is_replaced_or_removed() {
    for enabled in [true, false] {
        bounded(async move {
            let fixture = Fixture::new().await;
            assert!(crate::local_runtime::execution_authority::current_cell_lifetime().is_none());
            fixture.enable().await;
            fixture.wait_for("locked_use_renew", 1).await;
            fixture.replace_factory(enabled).await;
            assert_eq!(
                cloud::factory_lease(&fixture.state, &fixture.session.owner).is_ok(),
                enabled
            );
            assert_ne!(
                fixture
                    .state
                    .platform_plugin_authority_v2
                    .acquire_generation()
                    .unwrap()
                    .descriptor(),
                fixture.factory.descriptor()
            );
            assert_eq!(
                api::snapshot(&fixture.state, &fixture.session.owner).unwrap()["instance"]
                    ["revision"],
                fixture.session.revision
            );
            assert_eq!(
                fixture
                    .state
                    .session_store
                    .run(&fixture.run.id)
                    .unwrap()
                    .unwrap()
                    .revision,
                fixture.run.revision
            );
            agent_access::scope(Some(fixture.authorization.clone()), async {
                assert!(
                    fixture.native.current(&fixture.state),
                    "session and Running run remain valid"
                );
            })
            .await;
            assert!(!fixture.session.stopped.load(Ordering::SeqCst));
            fixture.assert_renewal_stopped().await;
            fixture.close().await;
        });
    }
}

#[test]
fn captured_scope_does_not_keep_revoked_session_authorized() {
    bounded(async {
        let fixture = Fixture::new().await;
        fixture.enable().await;
        fixture.wait_for("locked_use_renew", 1).await;
        assert!(fixture
            .state
            .session_store
            .revoke_session(
                "locked-use-execution",
                chrono::Utc::now().timestamp_millis()
            )
            .unwrap());
        fixture.assert_renewal_stopped().await;
        fixture.close().await;
    });
}

#[test]
fn disable_tool_reply_does_not_expose_another_sessions_revoked_binding() {
    bounded(async {
        let fixture = Fixture::new().await;
        let foreign = json!({"enabled":false,"state":"suppressed","phase":"idle",
            "requires_manual_unlock":true,"reason":"guardian_unavailable",
            "revoked_binding":{"session_id":"foreign-session","run_id":"foreign-run",
                "generation":"foreign-generation"}});
        std::fs::write(
            fixture.helper.root.join("locked_use_disable_result"),
            foreign.to_string(),
        )
        .unwrap();
        assert!(fixture
            .state
            .computer_use
            .locked_use
            .active
            .lock()
            .unwrap()
            .is_empty());
        let output = agent_access::scope(Some(fixture.authorization.clone()), async {
            call(
                &fixture.state,
                &fixture.session,
                &fixture.native,
                &fixture.factory,
                &fixture.helper.client,
                &json!({"enabled":false}),
            )
            .await
            .unwrap()
        })
        .await;
        let returned: Value = serde_json::from_str(&output.output_json).unwrap();
        for key in ["session_id", "run_id", "generation", "revoked_binding"] {
            assert!(
                returned.get(key).is_none(),
                "foreign identity in tool reply: {key}"
            );
        }
        assert_eq!(returned["enabled"], false);
        assert_eq!(returned["requires_manual_unlock"], true);
        assert_eq!(returned["reason"], "guardian_unavailable");
        assert!(!output.output_json.contains("foreign-"));
        assert_eq!(
            fixture
                .state
                .computer_use
                .locked_use
                .status
                .lock()
                .unwrap()
                .as_ref()
                .unwrap()["revoked_binding"],
            foreign["revoked_binding"],
            "host-only cache keeps the raw native status for owner-filtered projection"
        );
        let requests = fixture.requests("locked_use_disable");
        assert_eq!(requests.len(), 1);
        assert_eq!(
            requests[0]["params"]["session_id"],
            fixture.session.context.session_id
        );
        assert!(requests[0]["params"].get("generation").is_none());
        fixture.close().await;
        std::fs::remove_dir_all(&fixture.helper.root).unwrap();
    });
}

#[test]
fn disable_tool_reply_preserves_its_own_latest_host_issued_terminal_identity() {
    bounded(async {
        let fixture = Fixture::new().await;
        fixture.enable().await;
        let generation = fixture.requests("locked_use_enable")[0]["params"]["generation"].clone();
        let terminal = json!({"enabled":false,"state":"suppressed","phase":"idle",
            "requires_manual_unlock":true,
            "revoked_binding":{"session_id":fixture.session.context.session_id,
                "run_id":fixture.session.context.run_id,"generation":generation}});
        std::fs::write(
            fixture.helper.root.join("locked_use_disable_result"),
            terminal.to_string(),
        )
        .unwrap();
        let output = agent_access::scope(Some(fixture.authorization.clone()), async {
            call(
                &fixture.state,
                &fixture.session,
                &fixture.native,
                &fixture.factory,
                &fixture.helper.client,
                &json!({"enabled":false}),
            )
            .await
            .unwrap()
        })
        .await;
        let returned: Value = serde_json::from_str(&output.output_json).unwrap();
        assert_eq!(returned, terminal);
        assert!(returned.get("generation").is_none());
        assert!(fixture
            .state
            .computer_use
            .locked_use
            .active
            .lock()
            .unwrap()
            .is_empty());
        fixture.close().await;
        std::fs::remove_dir_all(&fixture.helper.root).unwrap();
    });
}
