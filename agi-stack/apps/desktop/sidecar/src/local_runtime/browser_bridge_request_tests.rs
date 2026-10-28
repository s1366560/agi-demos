//! Request cancellation cleans up the authenticated bridge's exact waiter.
use super::{tests::*, *};

#[tokio::test]
async fn dropped_browser_read_retires_its_waiter_and_late_reply_cannot_settle_the_next_read() {
    let bridge = start_test_bridge().await;
    let mut broker = connect_broker(&bridge.registry.ws_url, Some(&bridge.registry.token))
        .await
        .unwrap();
    broker_answer_hello(&mut broker, Some(BACKEND_IAB)).await;
    wait_for_backends(&bridge.runtime, &[BACKEND_IAB]).await;
    let server = bridge.runtime.server();
    let first_server = server.clone();
    let first = tokio::spawn(async move {
        first_server
            .request_on(BACKEND_IAB, "heldRead", json!({}))
            .await
    });
    let (old_id, _, _) = broker_next_request(&mut broker).await;
    let session = server.resolve_session(BACKEND_IAB).unwrap();
    assert_eq!(session.waiters.lock().unwrap().len(), 1);
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    assert!(session.waiters.lock().unwrap().is_empty());
    let next_server = server.clone();
    let next = tokio::spawn(async move {
        next_server
            .request_on(BACKEND_IAB, "freshRead", json!({}))
            .await
    });
    let (new_id, _, _) = broker_next_request(&mut broker).await;
    assert_ne!(old_id, new_id);
    broker_respond(&mut broker, old_id, json!("stale poison")).await;
    // The two replies use the same ordered transport. The stale id must never
    // consume the new waiter, regardless of which task runs next.
    assert_eq!(
        session
            .waiters
            .lock()
            .unwrap()
            .keys()
            .copied()
            .collect::<Vec<_>>(),
        vec![new_id]
    );
    assert!(!next.is_finished());
    broker_respond(&mut broker, new_id, json!("fresh receipt")).await;
    assert_eq!(next.await.unwrap().unwrap(), json!("fresh receipt"));
    assert!(session.waiters.lock().unwrap().is_empty());
    bridge.runtime.stop();
    std::fs::remove_dir_all(&bridge.root).unwrap();
}
