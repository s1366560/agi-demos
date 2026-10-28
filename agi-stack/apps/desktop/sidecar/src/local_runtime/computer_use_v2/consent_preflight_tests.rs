//! Exercise both production permission gates through private mock native IPC.
//! No operating-system input or locked-use behavior is simulated by these assertions.
use super::*;
use crate::local_runtime::{
    authority_store::{DesktopPermissionProfile, DesktopRun},
    authorized_tool_host::AuthorizedRunToolHost,
};

const TYPE_TEXT: &str = "computer_type_text";
const MARKER: &str = "consent-preflight-final-input";

struct PreflightFixture {
    fixture: Fixture,
    conversation: LocalConversation,
    run: DesktopRun,
    authorization: Arc<RunAuthorization>,
}

impl PreflightFixture {
    async fn new() -> Self {
        let fixture = Fixture::new().await;
        let (conversation, run) = crate::local_runtime::tests::seed_controlled_run(
            &fixture.state,
            "native-input-preflight",
        );
        assert_eq!(
            run.permission_profile,
            DesktopPermissionProfile::WorkspaceWrite
        );
        let auth = fixture
            .state
            .session_store
            .validate_session_credential(
                "cua-native-consent-fixture",
                chrono::Utc::now().timestamp_millis(),
            )
            .unwrap()
            .unwrap();
        let authorization = RunAuthorization::capture(
            auth,
            Some(cloud::factory_lease(&fixture.state, &fixture.owner).unwrap()),
            &conversation,
            &run.message_id,
            Some(&run.id),
        )
        .unwrap();
        Self {
            fixture,
            conversation,
            run,
            authorization,
        }
    }

    fn host(&self) -> AuthorizedRunToolHost {
        let native = tool_host(&self.fixture.state, &self.conversation, Some(&self.run)).unwrap();
        AuthorizedRunToolHost::new(
            native,
            self.fixture.state.session_store.clone(),
            self.run.clone(),
        )
        .with_once_permissions(self.fixture.state.run_once_tool_permissions.clone())
    }

    fn approve_outer_once(&self) {
        assert!(self
            .fixture
            .state
            .run_once_tool_permissions
            .lock()
            .unwrap()
            .insert((self.run.id.clone(), TYPE_TEXT.into())));
    }

    fn has_outer_once(&self) -> bool {
        self.fixture
            .state
            .run_once_tool_permissions
            .lock()
            .unwrap()
            .contains(&(self.run.id.clone(), TYPE_TEXT.into()))
    }

    fn actions(&self) -> Vec<Value> {
        self.fixture
            .helper
            .requests()
            .into_iter()
            .filter(|request| request["method"] == "perform_action")
            .collect()
    }

    async fn call(
        &self,
        host: &dyn ToolHost,
        round: u64,
        tool: &str,
        input: Value,
    ) -> CoreResult<Value> {
        let context = ToolPolicyContext {
            session_id: "native-input-preflight-engine",
            round,
            tool,
        };
        let result =
            call_identity::scope(&context, host.call_with_content(tool, &input.to_string()))
                .await?;
        Ok(serde_json::from_str(&result.output_json).unwrap())
    }

    async fn observe(&self, host: &dyn ToolHost, round: u64) -> Value {
        self.call(
            host,
            round,
            "computer_get_app_state",
            json!({"app":"fixture"}),
        )
        .await
        .unwrap()
    }

    async fn initial_snapshot(&self, host: &dyn ToolHost) -> Value {
        let pending = self.observe(host, 1).await;
        assert_eq!(pending["error"], "cua_permission_required");
        assert_eq!(pending["request"]["capability"], "observe");
        self.fixture
            .grant(&pending["request"]["request_id"], "session")
            .await
            .unwrap();
        let observed = self.observe(host, 2).await;
        assert_eq!(observed["snapshot_id"], "snapshot-round1");
        observed
    }

    fn input(snapshot: &Value) -> Value {
        json!({
            "app":"fixture",
            "snapshot_id":snapshot["snapshot_id"],
            "window_id":snapshot["window_id"],
            "text":MARKER
        })
    }

    async fn close(&self) {
        self.fixture
            .state
            .computer_use
            .stop_owner(&self.fixture.state, &self.fixture.owner, "revoked")
            .await;
        self.fixture.helper.client.shutdown().await;
    }
}

#[tokio::test]
async fn native_input_preflight_restores_outer_once_and_session_grant_accepts_fresh_snapshot() {
    let fixture = PreflightFixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let original = fixture.host();
        let snapshot = fixture.initial_snapshot(&original).await;
        let input = PreflightFixture::input(&snapshot);
        fixture.approve_outer_once();

        let pending = fixture
            .call(&original, 3, TYPE_TEXT, input.clone())
            .await
            .unwrap();
        assert_eq!(pending["error"], "cua_permission_required");
        assert_eq!(pending["request"]["capability"], "control");
        assert!(
            fixture.has_outer_once(),
            "native consent must retain the generic Once"
        );
        assert!(
            fixture.actions().is_empty(),
            "preflight must not dispatch input"
        );

        // The preflight also leaves the snapshot available and the pending identity stable.
        let repeated = fixture
            .call(&original, 4, TYPE_TEXT, input.clone())
            .await
            .unwrap();
        assert_eq!(
            repeated["request"]["request_id"],
            pending["request"]["request_id"]
        );
        assert_eq!(repeated["error"], "cua_permission_required");
        assert!(fixture.has_outer_once());
        assert!(fixture.actions().is_empty());

        fixture
            .fixture
            .grant(&pending["request"]["request_id"], "session")
            .await
            .unwrap();
        assert!(fixture.has_outer_once());
        assert!(
            fixture.actions().is_empty(),
            "granting consent cannot dispatch input"
        );
        drop(original);

        // The production host rebuild must preserve the native session and both grants.
        let rebuilt = fixture.host();
        std::fs::write(
            fixture.fixture.helper.root.join("snapshot_id"),
            "snapshot-final",
        )
        .unwrap();
        let fresh = fixture.observe(&rebuilt, 5).await;
        assert_eq!(fresh["snapshot_id"], "snapshot-final");
        let final_input = PreflightFixture::input(&fresh);
        assert_ne!(final_input, input);
        let result = fixture
            .call(&rebuilt, 6, TYPE_TEXT, final_input.clone())
            .await
            .unwrap();
        assert_eq!(result["ok"], true);
        assert!(!fixture.has_outer_once());

        let actions = fixture.actions();
        assert_eq!(actions.len(), 1);
        assert_eq!(
            actions[0]["params"]["session_id"],
            pending["request"]["session_id"]
        );
        assert_eq!(actions[0]["params"]["snapshot_id"], "snapshot-final");
        assert_eq!(actions[0]["params"]["window_id"], "window-1");
        assert_eq!(actions[0]["params"]["app"], "pid:10");
        assert_eq!(actions[0]["params"]["action"]["kind"], "type_text");
        assert_eq!(actions[0]["params"]["action"]["text"], MARKER);
        assert_eq!(
            actions[0]["params"]["expected_identity_digest"],
            "fixture-identity"
        );
        let grants = store::grants(
            &fixture.fixture.state.session_store.connection().unwrap(),
            &fixture.fixture.owner,
        )
        .unwrap();
        assert!(grants.iter().any(|grant| grant.capability == "control"
            && grant.scope == store::GrantScope::Session
            && grant.session_id.as_deref() == pending["request"]["session_id"].as_str()));
        let requests = fixture.fixture.helper.requests();
        assert_eq!(
            requests
                .iter()
                .filter(|request| request["method"] == "begin_session")
                .count(),
            1
        );

        for round in [6, 7] {
            let error = fixture
                .call(&rebuilt, round, TYPE_TEXT, final_input.clone())
                .await
                .unwrap_err();
            assert!(error
                .to_string()
                .contains("outside the approved permission profile"));
        }
        assert_eq!(
            fixture.actions(),
            actions,
            "neither replay nor a new round can spend Once twice"
        );
    })
    .await;
    fixture.close().await;
}

#[tokio::test]
async fn native_input_non_consent_error_does_not_restore_outer_once() {
    let fixture = PreflightFixture::new().await;
    agent_access::scope(Some(fixture.authorization.clone()), async {
        let host = fixture.host();
        let snapshot = fixture.initial_snapshot(&host).await;
        fixture.approve_outer_once();
        let pending = fixture
            .call(&host, 3, TYPE_TEXT, PreflightFixture::input(&snapshot))
            .await
            .unwrap();
        assert_eq!(pending["error"], "cua_permission_required");
        assert!(fixture.has_outer_once());
        fixture
            .fixture
            .grant(&pending["request"]["request_id"], "session")
            .await
            .unwrap();

        std::fs::write(
            fixture.fixture.helper.root.join("snapshot_id"),
            "snapshot-fresh",
        )
        .unwrap();
        let fresh = fixture.observe(&host, 4).await;
        assert_eq!(fresh["snapshot_id"], "snapshot-fresh");
        let error = fixture
            .call(&host, 5, TYPE_TEXT, PreflightFixture::input(&snapshot))
            .await
            .unwrap_err();
        assert!(error.to_string().contains("cua_snapshot_stale"));
        assert!(
            !fixture.has_outer_once(),
            "ordinary errors cannot replenish generic Once"
        );
        assert!(fixture.actions().is_empty());

        let error = fixture
            .call(&host, 6, TYPE_TEXT, PreflightFixture::input(&fresh))
            .await
            .unwrap_err();
        assert!(error
            .to_string()
            .contains("outside the approved permission profile"));
        assert!(!fixture.has_outer_once());
        assert!(
            fixture.actions().is_empty(),
            "fresh input still requires a new generic approval"
        );
    })
    .await;
    fixture.close().await;
}
