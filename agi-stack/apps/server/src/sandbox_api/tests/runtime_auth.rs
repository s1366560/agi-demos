use super::super::*;
use super::*;

#[test]
fn runtime_auth_derives_stable_redacted_project_capabilities() {
    let auth = SandboxRuntimeAuth::try_new(TEST_RUNTIME_AUTH_SECRET).unwrap();
    let first = auth.token_for("project-1", "tenant-1");
    let repeated = auth.token_for("project-1", "tenant-1");
    let other_project = auth.token_for("project-2", "tenant-1");

    assert_eq!(first.expose(), repeated.expose());
    assert_eq!(
        first.expose(),
        "r7BvXRgklya4DCV4m5jTYxStydMjYsJzqJ5EsMev3-w"
    );
    assert_ne!(first.expose(), other_project.expose());
    assert_eq!(format!("{first:?}"), "[redacted]");
    assert!(!format!("{auth:?}").contains(TEST_RUNTIME_AUTH_SECRET));
    assert!(SandboxRuntimeAuth::try_new("short-secret").is_err());
}

#[test]
fn cloud_container_spec_enforces_profile_and_auth_contract() {
    let auth = SandboxRuntimeAuth::try_new(TEST_RUNTIME_AUTH_SECRET).unwrap();
    let token = auth.token_for("project-1", "tenant-1");

    let lite = sandbox_container_spec(
        "sandbox-mcp-server:latest",
        "project-1",
        "tenant-1",
        SandboxProfile::Lite,
        &token,
    );
    let lite_env = lite.env.iter().cloned().collect::<BTreeMap<_, _>>();
    assert_eq!(
        lite_env.get("MCP_AUTH_ENABLED").map(String::as_str),
        Some("true")
    );
    assert_eq!(
        lite_env.get("MCP_ALLOW_LOCALHOST").map(String::as_str),
        Some("false")
    );
    assert_eq!(
        lite_env.get("MCP_STATIC_TOKEN").map(String::as_str),
        Some(token.expose())
    );
    assert_eq!(
        lite_env.get("DESKTOP_ENABLED").map(String::as_str),
        Some("false")
    );
    assert_eq!(
        lite_env.get("TERMINAL_ENABLED").map(String::as_str),
        Some("false")
    );
    assert_eq!(
        lite.ports
            .iter()
            .map(|binding| binding.container_port)
            .collect::<Vec<_>>(),
        vec![MCP_CONTAINER_PORT]
    );
    assert!(!format!("{:?}", lite.labels).contains(token.expose()));

    let standard = sandbox_container_spec(
        "sandbox-mcp-server:latest",
        "project-1",
        "tenant-1",
        SandboxProfile::Standard,
        &token,
    );
    let standard_env = standard.env.iter().cloned().collect::<BTreeMap<_, _>>();
    assert_eq!(
        standard_env.get("DESKTOP_ENABLED").map(String::as_str),
        Some("true")
    );
    assert_eq!(
        standard_env.get("TERMINAL_ENABLED").map(String::as_str),
        Some("true")
    );
    assert_eq!(standard.ports.len(), 3);
}

#[test]
fn runtime_auth_headers_use_protocol_specific_schemes() {
    let token = SandboxRuntimeToken::from_exposed("private-capability");

    assert_eq!(
        sandbox_basic_auth_header(&token).unwrap().to_str().unwrap(),
        "Basic c2FuZGJveDpwcml2YXRlLWNhcGFiaWxpdHk="
    );
    assert_eq!(
        sandbox_bearer_auth_header(&token)
            .unwrap()
            .to_str()
            .unwrap(),
        "Bearer private-capability"
    );
}
