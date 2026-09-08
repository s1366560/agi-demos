use super::*;

#[tokio::test]
async fn renderer_cannot_supply_cloud_authority_actor_credentials_or_omit_generation_condition() {
    let f = Fixture::new().await;
    let revision = f.observation().await;
    for field in [
        "credential",
        "base_url",
        "remote_actor_id",
        "authority",
        "actor_id",
        "bearer",
        "profile",
    ] {
        let mut body = f.target(&revision);
        body[field] = json!("forged");
        f.cloud.calls.lock().unwrap().clear();
        assert_eq!(
            f.request("sync-bind", body).await.0,
            StatusCode::UNPROCESSABLE_ENTITY
        );
        assert!(f.cloud.calls.lock().unwrap().is_empty());
    }
    for field in [
        "expected_connection_revision",
        "expected_generation",
        "scope",
    ] {
        let mut body = f.target(&revision);
        body.as_object_mut().unwrap().remove(field);
        assert_eq!(
            f.request("sync-bind", body).await.0,
            StatusCode::UNPROCESSABLE_ENTITY
        );
    }
    for value in [json!(0), json!(1.5), json!(true), json!("1"), json!(null)] {
        let mut body = f.target(&revision);
        body["expected_generation"]["descriptor"]["generation"] = value;
        assert_ne!(f.request("sync-bind", body).await.0, StatusCode::OK);
    }
}

#[tokio::test]
async fn unauthorized_enrollment_and_mismatched_enrollment_scope_do_not_bind() {
    let f = Fixture::new().await;
    let revision = f.observation().await;
    f.cloud.can_enroll.store(false, Ordering::SeqCst);
    assert_eq!(
        f.request("sync-enroll", f.target(&revision)).await.0,
        StatusCode::FORBIDDEN
    );
    assert_eq!(f.cloud.posts.load(Ordering::SeqCst), 0);
    for (field, value) in [
        ("actor_id", json!("other")),
        ("tenant_id", json!("other")),
        ("project_id", json!("other")),
        ("enabled", json!("true")),
        ("can_enroll", json!(1)),
        ("contract_version", json!("2.0.0")),
        (
            "generation",
            json!({"contract_version":"1.0.0","descriptor":{"profile_id":"cloud-sync-fixture","generation":1,"digest":"sha256:bad"}}),
        ),
    ] {
        let mut enrollment = super::super::sync_cloud_fixture::enrollment_value();
        enrollment[field] = value;
        *f.cloud.enrollment_override.lock().unwrap() = Some(enrollment);
        assert_ne!(
            f.request("sync-bind", f.target(&revision)).await.0,
            StatusCode::OK
        );
        assert!(f.operation().sync_status().await.unwrap().link.is_none());
    }
}

#[tokio::test]
async fn discovery_rejects_foreign_tenant_projects_and_unbounded_or_malformed_page_metadata() {
    let f = Fixture::new().await;
    let revision = f.observation().await;
    let request = json!({"scope":f.scope,"expected_connection_revision":revision,"tenant_id":"remote-tenant"});
    f.cloud.catalog.lock().unwrap()["projects"]["projects"][0]["tenant_id"] = json!("foreign");
    assert_eq!(
        f.request("sync-projects", request).await.0,
        StatusCode::FORBIDDEN
    );
    for total in [json!(10001), json!(-1), json!(true), json!(1.0), json!("1")] {
        let value = json!({"tenants":[],"total":total,"page":1,"page_size":100});
        f.cloud
            .overrides
            .lock()
            .unwrap()
            .insert(("tenants".into(), 1), value);
        assert_eq!(
            f.request(
                "sync-tenants",
                json!({"scope":f.scope,"expected_connection_revision":revision})
            )
            .await
            .0,
            StatusCode::BAD_GATEWAY
        );
    }
}

#[tokio::test]
async fn disconnected_cloud_preserves_local_session_and_closed_release_rejects_new_routes() {
    let f = Fixture::new().await;
    let local = authenticated(&f.state).session_id;
    f.broker.clear().unwrap();
    let (status, result) = f.request("sync-connection", json!({"scope":f.scope})).await;
    assert_eq!(status, StatusCode::OK, "{result}");
    assert!(result["result"]["connection"].is_null());
    assert_eq!(authenticated(&f.state).session_id, local);
    publish(&f.state, &f.directory, 2, false).await;
    for path in [
        "sync-connection",
        "sync-tenants",
        "sync-projects",
        "sync-enrollment",
        "sync-enroll",
        "sync-bind",
    ] {
        assert_eq!(
            f.request(path, json!({})).await.0,
            StatusCode::SERVICE_UNAVAILABLE
        );
    }
}
