use super::*;
use crate::computer_use_device_v2::{media_storage, repl_output};
use agistack_core::ports::ObjectStore;

fn definition() -> ToolDefinition {
    ToolDefinition::new(
        "unrelated_name",
        "Fixture",
        json!({"x-agistack-display-kind":"repl_output"}),
    )
}
fn output(image_size: u64) -> Value {
    json!({"outputs":[{"type":"text","text":"before"},{"type":"text","text":"after"}],"artifacts":[{"kind":"image","artifact_id":"native_image","mime_type":"image/png","size_bytes":image_size,"url":"cua-artifact:native_image","store":"device"}],"output_order":[{"source":"text","index":0},{"source":"media","index":0},{"source":"text","index":1}]})
}
#[test]
fn declared_output_requires_exact_order_and_bound_media() {
    let binding = media_storage::Binding {
        native_id: "native_image".into(),
        artifact_id: Some("cloud_image".into()),
        mime_type: "image/png".into(),
        size_bytes: 30,
    };
    let value = output(30);
    let display =
        repl_output::display(&definition(), &value.to_string(), &[binding.clone()]).unwrap();
    assert_eq!(
        display["entries"][1],
        json!({"kind":"image","artifactId":"cloud_image","mimeType":"image/png","sizeBytes":30,"store":"conversation_tool_media"})
    );
    assert_eq!(display["entries"][2]["text"], "after");
    assert!(repl_output::display(
        &ToolDefinition::name_only("computer_cua"),
        &value.to_string(),
        &[binding.clone()]
    )
    .is_none());
    assert!(repl_output::display(&definition(), &value.to_string(), &[]).is_none());
    let mut no_order = value.clone();
    no_order.as_object_mut().unwrap().remove("output_order");
    assert!(
        repl_output::display(&definition(), &no_order.to_string(), &[binding.clone()]).is_none()
    );
    let mut duplicate = value.clone();
    duplicate["output_order"][1] = duplicate["output_order"][0].clone();
    assert!(
        repl_output::display(&definition(), &duplicate.to_string(), &[binding.clone()]).is_none()
    );
    assert!(repl_output::display(&definition(), &output(31).to_string(), &[binding]).is_none());
}
#[tokio::test]
async fn durable_owned_bytes_survive_broker_restart_and_reject_scope_or_corruption() {
    let store = Arc::new(InMemoryObjectStore::new());
    let descriptor = broker::Descriptor {
        artifact_id: "native_image".into(),
        mime_type: "image/png".into(),
        size_bytes: 3,
    };
    let saved = media_storage::save(
        store.as_ref(),
        &owner(),
        "conversation",
        "request",
        &descriptor,
        b"png",
    )
    .await
    .unwrap();
    let cloud_id = saved.artifact_id.as_ref().unwrap();
    assert_ne!(cloud_id, &descriptor.artifact_id);
    let (_, authority, _) = fixture();
    let restarted = Broker::new(authority, store.clone());
    let objects = restarted.objects.as_ref().unwrap().as_ref();
    let actual = media_storage::read(objects, &owner(), "conversation", cloud_id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(actual, ("image/png".into(), b"png".to_vec()));
    for different in [
        Owner {
            user_id: "other".into(),
            ..owner()
        },
        Owner {
            tenant_id: "other".into(),
            ..owner()
        },
        Owner {
            project_id: "other".into(),
            ..owner()
        },
    ] {
        assert!(
            media_storage::read(objects, &different, "conversation", cloud_id)
                .await
                .unwrap()
                .is_none()
        );
    }
    assert!(media_storage::read(objects, &owner(), "other", cloud_id)
        .await
        .unwrap()
        .is_none());
    assert!(
        media_storage::read(objects, &owner(), "conversation", &descriptor.artifact_id)
            .await
            .unwrap()
            .is_none()
    );
    let key = store
        .list("conversation-tool-media/")
        .await
        .unwrap()
        .into_iter()
        .find(|key| key.ends_with("/bytes"))
        .unwrap();
    store
        .put(&key, b"bad".to_vec(), Some("image/png"))
        .await
        .unwrap();
    assert!(
        media_storage::read(objects, &owner(), "conversation", cloud_id)
            .await
            .is_err()
    );
}
#[tokio::test]
async fn broker_publishes_only_stored_media_for_exact_completed_invocation() {
    let (broker, _, mut receive) = fixture();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools[0]
        .input_schema = Some(json!({"x-agistack-display-kind":"repl_output"}));
    let content = STANDARD.decode(PNG).unwrap();
    let output = output(content.len() as u64).to_string();
    let call = dispatch(&broker, 1, "computer_get_app_state", "{}");
    let message = receive.recv().await.unwrap();
    let id = message["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    let descriptor = broker::Descriptor {
        artifact_id: "native_image".into(),
        mime_type: "image/png".into(),
        size_bytes: content.len() as u64,
    };
    broker
        .receive_result("connection", id, output.clone(), false, vec![descriptor])
        .unwrap();
    assert!(broker
        .current_tool_display(
            &owner(),
            "conversation",
            "engine-session",
            1,
            "computer_get_app_state",
            "{}",
            &output
        )
        .is_none());
    broker
        .receive_media("connection", id, "native_image", "image/png", 0, PNG, true)
        .unwrap();
    broker.complete(id).await.unwrap();
    let result = call.await.unwrap().unwrap();
    let display = broker
        .current_tool_display(
            &owner(),
            "conversation",
            "engine-session",
            1,
            "computer_get_app_state",
            "{}",
            &result.output_json,
        )
        .unwrap();
    let cloud_id = display["entries"][1]["artifactId"].as_str().unwrap();
    assert_ne!(cloud_id, "native_image");
    let (_, bytes) = media_storage::read(
        broker.objects.as_ref().unwrap().as_ref(),
        &owner(),
        "conversation",
        cloud_id,
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(bytes, content);
    assert!(broker
        .current_tool_display(
            &owner(),
            "conversation",
            "engine-session",
            2,
            "computer_get_app_state",
            "{}",
            &output
        )
        .is_none());
    assert!(broker
        .current_tool_display(
            &owner(),
            "conversation",
            "other",
            1,
            "computer_get_app_state",
            "{}",
            &output
        )
        .is_none());
    assert!(broker
        .current_tool_display(
            &owner(),
            "conversation",
            "engine-session",
            1,
            "computer_get_app_state",
            "{}",
            "policy replacement"
        )
        .is_none());
    let cache = broker.cache.lock().unwrap().take();
    if let Some(cache) = cache {
        std::fs::remove_dir_all(cache).unwrap();
    }
}

#[test]
fn media_limits_keep_order_and_text_without_manufacturing_cloud_ids() {
    let sizes = [10, 10, 10, 4, 2, 11];
    let descriptors = sizes
        .iter()
        .enumerate()
        .map(|(index, size)| broker::Descriptor {
            artifact_id: format!("native_{index}"),
            mime_type: "audio/wav".into(),
            size_bytes: size * 1024 * 1024,
        })
        .collect::<Vec<_>>();
    let media = descriptors.iter().map(|descriptor|json!({"kind":"audio","artifact_id":descriptor.artifact_id,"mime_type":descriptor.mime_type,"size_bytes":descriptor.size_bytes})).collect::<Vec<_>>();
    let mut order = vec![json!({"source":"text","index":0})];
    order.extend((0..6).map(|index| json!({"source":"media","index":index})));
    order.push(json!({"source":"text","index":1}));
    let output = json!({"outputs":[{"type":"text","text":"before"},{"type":"text","text":"after"}],"artifacts":media,"output_order":order}).to_string();
    let admitted = repl_output::admitted_media(&definition(), &output, &descriptors).unwrap();
    assert_eq!(
        admitted,
        ["native_0", "native_1", "native_2", "native_4"]
            .into_iter()
            .map(str::to_owned)
            .collect()
    );
    let bindings = descriptors
        .iter()
        .map(|descriptor| media_storage::Binding {
            native_id: descriptor.artifact_id.clone(),
            artifact_id: admitted
                .contains(&descriptor.artifact_id)
                .then(|| format!("cloud_{}", descriptor.artifact_id)),
            mime_type: descriptor.mime_type.clone(),
            size_bytes: descriptor.size_bytes,
        })
        .collect::<Vec<_>>();
    let display = repl_output::display(&definition(), &output, &bindings).unwrap();
    assert_eq!(display["entries"][0]["text"], "before");
    assert_eq!(
        display["entries"][4],
        json!({"kind":"unavailable","reason":"media_size_limit"})
    );
    assert_eq!(
        display["entries"][6],
        json!({"kind":"unavailable","reason":"media_size_limit"})
    );
    assert_eq!(display["entries"][7]["text"], "after");
    let long =
        json!({"outputs":[{"type":"text","text":"a".repeat(32769)}],"artifacts":[]}).to_string();
    assert_eq!(
        repl_output::display(&definition(), &long, &[]).unwrap()["entries"][0]["text"]
            .as_str()
            .unwrap()
            .len(),
        32768
    );
}

#[tokio::test]
async fn media_store_rejects_oversized_assets_and_invalid_mime_before_writes() {
    let store = InMemoryObjectStore::new();
    let bytes = vec![0; 10 * 1024 * 1024 + 1];
    let large = broker::Descriptor {
        artifact_id: "large".into(),
        mime_type: "audio/wav".into(),
        size_bytes: bytes.len() as u64,
    };
    assert!(
        media_storage::save(&store, &owner(), "conversation", "request", &large, &bytes)
            .await
            .is_err()
    );
    let invalid = broker::Descriptor {
        artifact_id: "html".into(),
        mime_type: "text/html".into(),
        size_bytes: 3,
    };
    assert!(media_storage::save(
        &store,
        &owner(),
        "conversation",
        "request",
        &invalid,
        b"bad"
    )
    .await
    .is_err());
    assert!(store.list("").await.unwrap().is_empty());
}
