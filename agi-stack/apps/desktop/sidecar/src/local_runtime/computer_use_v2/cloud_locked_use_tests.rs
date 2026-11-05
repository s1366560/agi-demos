//! Real HTTP renewals preserve resource continuity without extending a tool claim.
use super::super::cloud_tests::Fixture;
use super::*;

#[tokio::test]
async fn cloud_continuity_crosses_claim_expiry_and_stops_on_server_revocation() {
    let fixture = Fixture::new().await;
    let helper = super::super::management_lifecycle_tests::Helper::new(false);
    fixture
        .state
        .computer_use
        .client
        .set(helper.client.clone())
        .ok()
        .unwrap();
    fixture.publish_factory(true).await;
    for request in [
        json!({"action":"locked_use_install","expected_revision":0}),
        json!({"action":"enable","expected_revision":0}),
        json!({"action":"configure","capability":"locked_use","enabled":true,"expected_revision":1}),
    ] {
        api::operation(
            &fixture.state,
            &fixture.owner(),
            serde_json::from_value(request).unwrap(),
        )
        .await
        .unwrap();
    }
    fixture.operation("describe").await.unwrap();
    fixture.operation("ready").await.unwrap();
    fixture.authority.release.add_permits(1);
    fixture.operation("call").await.unwrap();
    let session = fixture
        .state
        .computer_use
        .sessions
        .lock()
        .unwrap()
        .values()
        .next()
        .unwrap()
        .clone();
    let (alive, epoch) = {
        let connections = fixture.state.computer_use.cloud_connections.lock().unwrap();
        let connection = connections.values().next().unwrap();
        (connection.alive.clone(), connection.epoch)
    };
    let lease = cloud::CloudLease {
        request_id: "request".into(),
        authorization_revision: 3,
        broker: fixture.broker.clone(),
        epoch,
        expires_at: chrono::Utc::now().timestamp() + 2,
        profile: "full_access".into(),
        approved_tools: Default::default(),
        allowed_mcp_servers: vec![],
        alive,
        cancelled: Arc::new(AtomicBool::new(false)),
        factory: cloud::factory_lease(&fixture.state, &fixture.owner()).unwrap(),
    };
    resource_lease::renew(&fixture.state, &session, lease.clone(), lease.expires_at)
        .await
        .unwrap();
    let native = NativeIdentity::Cloud(lease.clone());
    let factory = cloud::factory_lease(&fixture.state, &fixture.owner()).unwrap();
    super::super::locked_use::call(
        &fixture.state,
        &session,
        &native,
        &factory,
        &helper.client,
        &json!({"enabled":true}),
    )
    .await
    .unwrap();
    tokio::time::sleep(std::time::Duration::from_millis(3300)).await;
    assert!(
        !lease.current(&fixture.state),
        "one-shot claim still expires"
    );
    assert!(
        helper
            .requests()
            .iter()
            .filter(|row| row["method"] == "locked_use_renew")
            .count()
            >= 2
    );
    assert!(!helper
        .requests()
        .iter()
        .any(|row| row["method"] == "locked_use_disable"));
    assert!(!session.resources.released());
    *fixture.authority.resume_response.lock().unwrap() = Some(json!({"denied":true}));
    tokio::time::timeout(std::time::Duration::from_secs(3), async {
        while !helper
            .requests()
            .iter()
            .any(|row| row["method"] == "locked_use_disable")
        {
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap();
    tokio::time::sleep(std::time::Duration::from_millis(350)).await;
    assert!(session.resources.released());
    fixture.operation("close").await.unwrap();
    helper.client.shutdown().await;
}
