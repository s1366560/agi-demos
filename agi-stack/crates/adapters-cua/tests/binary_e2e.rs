//! Explicit opt-in native helper observation. This test never synthesizes input.
use agistack_adapters_cua::{CuaCallContext, CuaClient};
use serde_json::json;

#[tokio::test]
#[ignore = "requires a built native helper and an interactive desktop"]
async fn real_private_helper_capabilities_and_observation() {
    let helper = std::env::var_os("AGISTACK_CUA_TEST_HELPER")
        .expect("set AGISTACK_CUA_TEST_HELPER to the owned test helper");
    let client = CuaClient::builder().helper_path(helper).build();
    let capabilities = client.request("capabilities", json!({})).await.unwrap();
    assert_eq!(capabilities["protocol_version"], "MemstackComputerUseIPC-2");
    let context = CuaCallContext {
        user_id: "native-test".into(),
        tenant_id: "native-test".into(),
        project_id: "native-test".into(),
        device_id: "native-test".into(),
        conversation_id: "native-test".into(),
        run_id: "native-test".into(),
        session_id: "native-test".into(),
    };
    let apps = client
        .request_in_session(&context, "list_apps", json!({}))
        .await
        .unwrap();
    assert!(apps["apps"].is_array());
    client.stop_session(&context.session_id).await.unwrap();
    client.shutdown().await;
}
