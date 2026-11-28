//! HTTP responses for a project without a local isolated sandbox.
#[cfg(target_arch = "wasm32")]
mod abi;

mod workspace;

use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
struct Request {
    method: String,
    path: String,
    project_id: String,
}

fn respond(data: &[u8]) -> Option<Vec<u8>> {
    let call: Request = serde_json::from_slice(data).ok()?;
    if call.method == "GET" {
        if let Some(plan) = workspace::read_plan(&call.path) {
            return serde_json::to_vec(&plan).ok();
        }
    }
    let sandbox = json!({
        "sandbox_id":format!("local-{}", call.project_id), "project_id":call.project_id,
        "tenant_id":"local", "status":"unavailable", "endpoint":null, "websocket_url":null,
        "desktop_port":null, "terminal_port":null, "desktop_url":null, "terminal_url":null,
        "is_healthy":false, "error_message":"isolated local sandbox is not configured"
    });
    let (status, body) = match (call.method.as_str(), call.path.as_str()) {
        ("GET", "sandbox") => (200, sandbox),
        ("POST", "sandbox") => (501, json!({"detail":"isolated local sandbox is not configured","sandbox":sandbox})),
        ("POST", "sandbox/desktop") => (501, json!({"detail":"isolated local desktop is not configured","sandbox":sandbox})),
        ("POST", "sandbox/proxy-auth-cookie") => (200, json!({"ok":true})),
        _ => return None,
    };
    serde_json::to_vec(&json!({"status":status,"body":body})).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reports_project_sandbox_status_and_original_response_shapes() {
        let call = |method: &str, path: &str| {
            let input = json!({"method":method, "path":path, "project_id":"sample"});
            let output = respond(&serde_json::to_vec(&input).unwrap()).unwrap();
            serde_json::from_slice::<serde_json::Value>(&output).unwrap()
        };
        let response = call("GET", "sandbox");
        assert_eq!(response["status"], 200);
        let sandbox = &response["body"];
        assert_eq!(sandbox["sandbox_id"], "local-sample");
        assert_eq!(sandbox["is_healthy"], false);
        assert_eq!(sandbox["status"], "unavailable");
        for (path, detail) in [
            ("sandbox", "isolated local sandbox is not configured"),
            ("sandbox/desktop", "isolated local desktop is not configured"),
        ] {
            assert_eq!(
                call("POST", path),
                json!({"status": 501, "body": {"sandbox": sandbox, "detail": detail}})
            );
        }
        assert_eq!(
            call("POST", "sandbox/proxy-auth-cookie"),
            json!({"status": 200, "body": {"ok": true}})
        );
    }
}
