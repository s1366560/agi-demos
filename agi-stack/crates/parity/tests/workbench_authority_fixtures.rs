use std::{fs, path::PathBuf};

use serde_json::Value;

const FIXTURE_NAMES: [&str; 5] = [
    "hitl-authority.v1.json",
    "workspace-surface.v1.json",
    "artifact-content.v1.json",
    "sandbox-runtime.v1.json",
    "automation-run-receipt.v1.json",
];

fn fixture_path(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../shared/fixtures")
        .join(name)
}

fn load_fixture(name: &str) -> Value {
    let bytes = fs::read(fixture_path(name)).expect("shared workbench fixture must exist");
    serde_json::from_slice(&bytes).expect("shared workbench fixture must be valid JSON")
}

#[test]
fn workbench_authority_fixtures_are_cross_client_canonical() {
    for name in FIXTURE_NAMES {
        let fixture = load_fixture(name);
        assert_eq!(fixture["schema_version"], "1.0.0", "{name}");
        assert_eq!(
            fixture["web_expected_view_model"], fixture["desktop_expected_view_model"],
            "{name}"
        );
    }
}

#[test]
fn sandbox_and_automation_fixtures_preserve_fail_closed_authority() {
    let sandbox = load_fixture("sandbox-runtime.v1.json");
    let runtime = &sandbox["input"]["runtime"];
    let features = &sandbox["web_expected_view_model"]["features"];
    for name in [
        "terminal_interactive",
        "terminal_resume",
        "files",
        "kasm_vnc",
    ] {
        let availability = runtime[name]["availability"]
            .as_str()
            .expect("availability must be a string");
        let expected_available = matches!(availability, "available" | "degraded");
        assert_eq!(
            features[name]["available"].as_bool(),
            Some(expected_available),
            "{name}"
        );
        if !expected_available {
            assert!(
                runtime[name]["reason_code"]
                    .as_str()
                    .is_some_and(|reason| !reason.is_empty()),
                "{name}"
            );
        }
    }

    let automation = load_fixture("automation-run-receipt.v1.json");
    let receipt = &automation["input"]["receipt"];
    let expected = &automation["web_expected_view_model"];
    assert_eq!(receipt["contract_version"], 2);
    assert_eq!(expected["replay_safe"], true);
    assert!(expected.get("idempotency_key").is_none());
}

#[test]
fn hitl_and_artifact_fixtures_do_not_project_sensitive_command_fields() {
    let hitl = load_fixture("hitl-authority.v1.json");
    let hitl_view = &hitl["web_expected_view_model"];
    for key in ["response_data", "response_data_encrypted", "env_value"] {
        assert!(hitl_view.get(key).is_none(), "{key}");
    }

    let artifact = load_fixture("artifact-content.v1.json");
    let artifact_view = &artifact["web_expected_view_model"];
    assert_eq!(artifact_view["conflict_safe"], true);
    assert_eq!(artifact_view["has_idempotency_key"], true);
    assert!(artifact_view.get("idempotency_key").is_none());
}
