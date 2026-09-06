use agistack_adapters_http_llm::HttpLlm;
use agistack_core::ports::{LlmPort, ToolDefinition};
use serde_json::json;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

#[tokio::test]
async fn tool_contract_reaches_real_http_request_and_preserves_structured_action() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut request = Vec::new();
        loop {
            let mut buffer = [0; 4096];
            let n = socket.read(&mut buffer).await.unwrap();
            assert!(n > 0);
            request.extend_from_slice(&buffer[..n]);
            if let Some(offset) = request.windows(4).position(|v| v == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&request[..offset]);
                let length: usize = headers
                    .lines()
                    .find_map(|line| {
                        let (name, value) = line.split_once(':')?;
                        name.eq_ignore_ascii_case("content-length")
                            .then(|| value.trim().parse().unwrap())
                    })
                    .unwrap();
                if request.len() >= offset + 4 + length {
                    break;
                }
            }
        }
        let action = json!({"kind":"call_tool","tool":"submit_plan","input_json":{"tasks":[{"content":"Inspect README","priority":"high"}]}});
        let body = json!({"choices":[{"message":{"content":action.to_string()}}]}).to_string();
        socket.write_all(format!("HTTP/1.1 200 OK\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",body.len(),body).as_bytes()).await.unwrap();
        let offset = request.windows(4).position(|v| v == b"\r\n\r\n").unwrap() + 4;
        serde_json::from_slice::<serde_json::Value>(&request[offset..]).unwrap()
    });
    let definition = ToolDefinition::new(
        "submit_plan",
        "Persist the ordered human-reviewable plan.",
        json!({
            "type":"object", "required":["tasks"], "properties":{"tasks":{"type":"array","minItems":1,"maxItems":50,
            "items":{"type":"object","required":["content"],"properties":{"content":{"type":"string","minLength":1},"priority":{"enum":["high","medium","low"]}}}}}
        }),
    );
    let llm = HttpLlm::new(format!("http://{address}"), "fixture");
    let action = llm
        .decide_with_tools(
            "Plan a read-only inspection",
            0,
            &[],
            std::slice::from_ref(&definition),
        )
        .await
        .unwrap();
    let body = server.await.unwrap();
    let prompt = body["messages"][1]["content"].as_str().unwrap();
    assert!(prompt.contains(&serde_json::to_string(&definition).unwrap()));
    assert!(prompt.contains("input_schema"));
    match action {
        agistack_core::agent::AgentAction::CallTool { tool, input_json } => {
            assert_eq!(tool, "submit_plan");
            assert_eq!(
                serde_json::from_str::<serde_json::Value>(&input_json).unwrap()["tasks"][0]
                    ["content"],
                "Inspect README"
            );
        }
        other => panic!("unexpected action: {other:?}"),
    }
}
