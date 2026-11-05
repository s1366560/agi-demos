use super::*;
use crate::computer_use_device_v2::continuity_authority::Input;
use std::sync::atomic::Ordering;

fn input() -> Input {
    Input {
        device_id: "device".into(),
        session_id: "engine-session".into(),
        cell_id: None,
        step_id: None,
        parent_request_id: None,
    }
}

#[tokio::test]
async fn continuity_outlives_tool_claim_but_not_run_revision_or_connection() {
    let (broker, authority, mut receive) = fixture();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .push(ToolDefinition::name_only("computer_locked_use"));
    let call = dispatch(&broker, 1, "computer_locked_use", "{\"enabled\":true}");
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    let lease = broker
        .continuity_authority(&id, "user", &input())
        .await
        .unwrap();
    assert!(
        lease["expires_at_ms"].as_i64().unwrap() <= chrono::Utc::now().timestamp_millis() + 5000
    );
    broker
        .receive_result(
            "connection",
            &id,
            "{\"enabled\":true}".into(),
            false,
            vec![],
        )
        .unwrap();
    call.await.unwrap().unwrap();
    broker
        .requests
        .lock()
        .unwrap()
        .get_mut(&id)
        .unwrap()
        .claim
        .expires_at = 1;
    broker
        .continuity_authority(&id, "user", &input())
        .await
        .unwrap();
    assert_eq!(broker.requests.lock().unwrap()[&id].claim.expires_at, 1);
    assert!(broker.claim(&id, "user", "device").is_err());
    assert!(receive.try_recv().is_err());
    authority.running.store(false, Ordering::SeqCst);
    assert!(broker
        .continuity_authority(&id, "user", &input())
        .await
        .is_err());
    authority.running.store(true, Ordering::SeqCst);
    authority.current.store(false, Ordering::SeqCst);
    assert!(broker
        .continuity_authority(&id, "user", &input())
        .await
        .is_err());
    authority.current.store(true, Ordering::SeqCst);
    broker.devices.lock().unwrap().clear();
    assert!(broker
        .continuity_authority(&id, "user", &input())
        .await
        .is_err());
}

#[tokio::test]
async fn continuity_rejects_other_tools_and_disable_or_forged_scope() {
    let (broker, _, mut receive) = fixture();
    let call = dispatch(&broker, 1, "computer_get_app_state", "{}");
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    assert!(broker
        .continuity_authority(&id, "user", &input())
        .await
        .is_err());
    broker
        .receive_result("connection", &id, "{}".into(), false, vec![])
        .unwrap();
    call.await.unwrap().unwrap();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .push(ToolDefinition::name_only("computer_locked_use"));
    let call = dispatch(&broker, 2, "computer_locked_use", "{\"enabled\":false}");
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    broker.claim(&id, "user", "device").unwrap();
    assert!(broker
        .continuity_authority(&id, "user", &input())
        .await
        .is_err());
    assert!(broker
        .continuity_authority(&id, "other", &input())
        .await
        .is_err());
    broker
        .receive_result("connection", &id, "{}".into(), false, vec![])
        .unwrap();
    call.await.unwrap().unwrap();
}
