//! Delayed native start replies must retain their trusted engine binding.
use super::*;
use agistack_core::agent::tool_policy::ToolPolicyContext;

#[tokio::test]
async fn late_start_binds_each_terminal_receipt_without_reopening_or_reassigning_it() {
    for (status, retry) in [
        ("saved", false),
        ("failed", true),
        ("failed", false),
        ("pending_export", false),
    ] {
        let fixture = Fixture::new().await;
        fixture.stop().await;
        let mut record = recordings_store::get(&fixture.state, fixture.id())
            .unwrap()
            .unwrap();
        record.receipt["status"] = json!(status);
        record.receipt["can_retry_export"] = json!(retry);
        record.engine_session_id = None;
        recordings_store::save(&fixture.state, &record).unwrap();
        let original = record.receipt;
        for engine in ["originating-engine", "another-engine"] {
            let identity = ToolPolicyContext {
                session_id: engine,
                round: 1,
                tool: "computer_audio_start",
            };
            call_identity::scope(
                &identity,
                recordings::ingest(
                    &fixture.state,
                    &fixture.owner,
                    &fixture.context,
                    &json!({"recordings":[fixture.receipt]}),
                ),
            )
            .await
            .unwrap();
            let updated = recordings_store::get(&fixture.state, fixture.id())
                .unwrap()
                .unwrap();
            assert_eq!(updated.receipt, original);
            assert_eq!(
                updated.engine_session_id.as_deref(),
                Some("originating-engine"),
                "late start binding for {status}, retry={retry}",
            );
        }
        fixture.close().await;
    }
}
