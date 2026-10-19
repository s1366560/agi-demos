use super::*;
use crate::computer_use_device_v2::resume_authority::{resume_authority, ResumeState};
use axum::{body::Body, http::Request};
use std::sync::atomic::Ordering;
use tower::ServiceExt;

async fn completed_request(broker: &Broker, receive: &mut mpsc::Receiver<Value>) -> String {
    let call = dispatch(broker, 1, "computer_get_app_state", "{}");
    let frame = receive.recv().await.unwrap();
    let id = frame["request_id"].as_str().unwrap().to_owned();
    broker.claim(&id, "user", "device").unwrap();
    broker
        .receive_result(
            "connection",
            &id,
            "{\"observed\":true}".into(),
            false,
            vec![],
        )
        .unwrap();
    call.await.unwrap().unwrap();
    id
}

#[tokio::test]
async fn fresh_resume_lease_preserves_expired_invocation_and_does_not_replay() {
    let (broker, _, mut receive) = fixture();
    let id = completed_request(&broker, &mut receive).await;
    broker
        .requests
        .lock()
        .unwrap()
        .get_mut(&id)
        .unwrap()
        .claim
        .expires_at = 1;
    let before = chrono::Utc::now().timestamp();
    let authority = broker
        .resume_authority(&id, "user", "device", "engine-session")
        .await
        .unwrap();
    let value = serde_json::to_value(authority).unwrap();
    assert_eq!(value.as_object().unwrap().len(), 10);
    assert_eq!(value["request_id"], id);
    assert_eq!(value["user_id"], "user");
    assert_eq!(value["tenant_id"], "tenant");
    assert_eq!(value["project_id"], "project");
    assert_eq!(value["device_id"], "device");
    assert_eq!(value["conversation_id"], "conversation");
    assert_eq!(value["run_id"], "run");
    assert_eq!(value["session_id"], "engine-session");
    assert_eq!(value["authorization_revision"], 3);
    assert!(value["expires_at"].as_i64().unwrap() >= before + 30);
    assert!(value["expires_at"].as_i64().unwrap() <= chrono::Utc::now().timestamp() + 30);
    let requests = broker.requests.lock().unwrap();
    let request = &requests[&id];
    assert_eq!(request.status, "completed");
    assert_eq!(request.claim.expires_at, 1);
    assert_eq!(
        request.result.as_ref().unwrap().output_json,
        "{\"observed\":true}"
    );
    drop(requests);
    assert!(broker.claim(&id, "user", "device").is_err());
    assert!(receive.try_recv().is_err());
}

#[tokio::test]
async fn resume_rejects_wrong_scope_pending_unknown_failed_and_inactive_parent() {
    let (broker, authority, mut receive) = fixture();
    let id = completed_request(&broker, &mut receive).await;
    for (user, device, session) in [
        ("other", "device", "engine-session"),
        ("user", "other", "engine-session"),
        ("user", "device", "other"),
    ] {
        assert!(broker
            .resume_authority(&id, user, device, session)
            .await
            .is_err());
    }
    for status in ["requested", "claimed", "receiving", "saving", "unknown"] {
        broker.requests.lock().unwrap().get_mut(&id).unwrap().status = status;
        assert!(broker
            .resume_authority(&id, "user", "device", "engine-session")
            .await
            .is_err());
    }
    {
        let mut requests = broker.requests.lock().unwrap();
        requests.get_mut(&id).unwrap().status = "completed";
        requests.get_mut(&id).unwrap().failed = true;
    }
    assert!(broker
        .resume_authority(&id, "user", "device", "engine-session")
        .await
        .is_err());
    broker.requests.lock().unwrap().get_mut(&id).unwrap().failed = false;
    authority.current.store(false, Ordering::SeqCst);
    assert!(broker
        .resume_authority(&id, "user", "device", "engine-session")
        .await
        .is_err());
    authority.current.store(true, Ordering::SeqCst);
    authority.running.store(false, Ordering::SeqCst);
    assert!(broker
        .resume_authority(&id, "user", "device", "engine-session")
        .await
        .is_err());
    assert!(receive.try_recv().is_err());
}

#[tokio::test]
async fn cancellation_tombstone_keeps_completed_result_but_prevents_resume() {
    for cancel_by in ["request", "conversation", "run", "disconnect"] {
        let (broker, _, mut receive) = fixture();
        let id = completed_request(&broker, &mut receive).await;
        match cancel_by {
            "request" => broker.cancel(&id),
            "conversation" => broker.cancel_conversation(&owner(), "conversation"),
            "run" => broker.cancel_run(&owner(), "run"),
            "disconnect" => broker.disconnect("connection"),
            _ => unreachable!(),
        }
        assert!(broker
            .resume_authority(&id, "user", "device", "engine-session")
            .await
            .is_err());
        let requests = broker.requests.lock().unwrap();
        let request = &requests[&id];
        assert!(request.cancelled);
        assert_eq!(request.status, "completed");
        assert!(request.result.is_some());
    }
}

#[tokio::test]
async fn resume_rechecks_original_device_owner_catalog_and_agent_policy() {
    let (broker, _, mut receive) = fixture();
    let id = completed_request(&broker, &mut receive).await;
    let original = broker.devices.lock().unwrap()["connection"].clone();
    for mutation in ["device", "owner", "tool"] {
        let mut device = original.clone();
        match mutation {
            "device" => device.device_id = "replacement".into(),
            "owner" => device.owner.project_id = "other-project".into(),
            "tool" => device
                .tools
                .retain(|tool| tool.name != "computer_get_app_state"),
            _ => unreachable!(),
        }
        broker
            .devices
            .lock()
            .unwrap()
            .insert("connection".into(), device);
        assert!(broker
            .resume_authority(&id, "user", "device", "engine-session")
            .await
            .is_err());
    }
    broker
        .devices
        .lock()
        .unwrap()
        .insert("connection".into(), original);
    broker
        .requests
        .lock()
        .unwrap()
        .get_mut(&id)
        .unwrap()
        .run
        .agent_profile
        .allowed_tools = Some(vec![]);
    assert!(broker
        .resume_authority(&id, "user", "device", "engine-session")
        .await
        .is_err());
}

#[tokio::test]
async fn cancellation_during_authority_read_is_rechecked_before_issuing_lease() {
    struct WaitingAuthority {
        entered: tokio::sync::Notify,
        release: tokio::sync::Notify,
    }
    #[async_trait]
    impl authority::Authority for WaitingAuthority {
        async fn prepare(
            &self,
            _: &Owner,
            _: &str,
            _: &str,
            _: &str,
        ) -> CoreResult<authority::RunAuthority> {
            Ok(run())
        }
        async fn recheck(&self, _: &Owner, _: &str, _: &authority::RunAuthority) -> CoreResult<()> {
            Ok(())
        }
        async fn recheck_running(
            &self,
            _: &Owner,
            _: &str,
            _: &authority::RunAuthority,
        ) -> CoreResult<()> {
            self.entered.notify_one();
            self.release.notified().await;
            Ok(())
        }
    }
    let (mut broker, _, mut receive) = fixture();
    let id = completed_request(&broker, &mut receive).await;
    let authority = Arc::new(WaitingAuthority {
        entered: tokio::sync::Notify::new(),
        release: tokio::sync::Notify::new(),
    });
    broker.authority = Some(authority.clone());
    let cloned = broker.clone();
    let request_id = id.clone();
    let resume = tokio::spawn(async move {
        cloned
            .resume_authority(&request_id, "user", "device", "engine-session")
            .await
    });
    authority.entered.notified().await;
    broker.cancel(&id);
    authority.release.notify_one();
    assert!(resume.await.unwrap().is_err());
}

#[tokio::test]
async fn resume_route_validates_body_membership_and_returns_minimal_authority() {
    let (broker, _, mut receive) = fixture();
    let id = completed_request(&broker, &mut receive).await;
    {
        let mut requests = broker.requests.lock().unwrap();
        let request = requests.get_mut(&id).unwrap();
        request.owner.tenant_id = "dev-tenant".into();
        request.owner.project_id = "dev-project".into();
        request.claim.tenant_id = "dev-tenant".into();
        request.claim.project_id = "dev-project".into();
        broker
            .devices
            .lock()
            .unwrap()
            .get_mut("connection")
            .unwrap()
            .owner = request.owner.clone();
    }
    let router = Router::new()
        .route(
            "/requests/:request_id/resume-authority",
            post(resume_authority),
        )
        .layer(Extension(Identity {
            user_id: "user".into(),
            _api_key_id: "fixture-key".into(),
        }))
        .with_state(ResumeState {
            broker: broker.clone(),
            auth: Arc::new(crate::auth::DevAuthenticator::new("user")),
        });
    let request = |body: Value| {
        Request::builder()
            .method("POST")
            .uri(format!("/requests/{id}/resume-authority"))
            .header("content-type", "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    };
    for body in [
        json!({"device_id":"device"}),
        json!({"device_id":"device","session_id":"engine-session","run_id":"replacement"}),
        json!({"device_id":"","session_id":"engine-session"}),
        json!({"device_id":"device","session_id":"x".repeat(257)}),
    ] {
        assert_eq!(
            router
                .clone()
                .oneshot(request(body))
                .await
                .unwrap()
                .status(),
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }
    let body = json!({"device_id":"device","session_id":"engine-session"});
    let response = router.clone().oneshot(request(body.clone())).await.unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    let bytes = axum::body::to_bytes(response.into_body(), 4096)
        .await
        .unwrap();
    let output: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(output.as_object().unwrap().len(), 10);
    assert_eq!(output["request_id"], id);
    {
        let mut requests = broker.requests.lock().unwrap();
        let request = requests.get_mut(&id).unwrap();
        request.owner.project_id = "unauthorized-project".into();
        broker
            .devices
            .lock()
            .unwrap()
            .get_mut("connection")
            .unwrap()
            .owner = request.owner.clone();
    }
    assert_eq!(
        router.oneshot(request(body)).await.unwrap().status(),
        StatusCode::CONFLICT
    );
    assert!(receive.try_recv().is_err());
}
