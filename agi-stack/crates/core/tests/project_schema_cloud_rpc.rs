use agistack_core::project_schema::{
    cloud_rpc::{
        CloudSchemaHistoryPage, CloudSchemaHistoryQuery, CloudSchemaProtocolError,
        CloudSchemaReceipt, CloudSchemaReceiptQuery, CloudSchemaReplaceRequest,
        MAX_CLOUD_SCHEMA_BYTES,
    },
    ProjectSchemaDocument,
};
use serde_json::{json, Value};

#[path = "project_schema_cloud_rpc/history.rs"]
mod history;

const SCHEMA: &str = "00000000-0000-4000-8000-000000000001";
const MEMBER: &str = "00000000-0000-4000-8000-000000000002";
const CHANGE: &str = "00000000-0000-4000-8000-999999999999";
const NEXT_CHANGE: &str = "00000000-0000-4000-8000-999999999998";

fn document(revision: u32) -> Value {
    json!({"format_version":1,"tenant_id":"tenant-a","project_id":"project-a",
        "schema_id":SCHEMA,"revision":revision,"deleted":false,
        "entity_types":[{"id":MEMBER,"name":"人物","description":"",
            "schema":{"opaque":{"number":0.25,"negative_zero":-0.0,"reference":"https://invalid.example/schema"}},
            "status":"ENABLED","source":"user"}],
        "edge_types":[],"mappings":[],"tombstones":[]})
}

fn receipt_raw(document: &Value, change: &str) -> String {
    // Different formatting from native canonical receipts is intentional.
    format!("{{ \"schema_id\" : \"{SCHEMA}\", \"revision\" : {}, \"sequence\" : {}, \"change_id\" : \"{change}\", \"document\" : {} }}",
        document["revision"], document["revision"], document)
}

fn receipt(document: &Value) -> CloudSchemaReceipt {
    CloudSchemaReceipt::from_json(&receipt_raw(document, CHANGE), "tenant-a", "project-a").unwrap()
}

#[test]
fn receipt_retains_cloud_json_without_native_actor_or_format_fields() {
    let raw = format!(" \n{}\t", receipt_raw(&document(1), CHANGE));
    let receipt = CloudSchemaReceipt::from_json(&raw, "tenant-a", "project-a").unwrap();
    assert_eq!(receipt.as_json(), raw);
    assert_eq!(receipt.revision(), 1);
    assert_eq!(receipt.change_id(), CHANGE);
    assert_eq!(
        receipt.document().entity_types()[0].schema["opaque"]["number"],
        0.25
    );
    for field in ["actor_id", "format_version", "receipt", "replayed"] {
        let mut value: Value = serde_json::from_str(&raw).unwrap();
        value[field] = json!(1);
        assert!(
            CloudSchemaReceipt::from_json(&value.to_string(), "tenant-a", "project-a").is_err(),
            "{field}"
        );
    }
}

#[test]
fn receipt_checks_all_identity_relationships_and_scope() {
    for (field, bad) in [
        ("schema_id", json!(MEMBER)),
        ("revision", json!(2)),
        ("sequence", json!(2)),
        ("change_id", json!("00000000-0000-0000-0000-000000000000")),
    ] {
        let mut value: Value = serde_json::from_str(&receipt_raw(&document(1), CHANGE)).unwrap();
        value[field] = bad;
        assert!(
            CloudSchemaReceipt::from_json(&value.to_string(), "tenant-a", "project-a").is_err(),
            "{field}"
        );
    }
    let raw = receipt_raw(&document(1), CHANGE);
    for (tenant, project) in [("other", "project-a"), ("tenant-a", "other")] {
        assert_eq!(
            CloudSchemaReceipt::from_json(&raw, tenant, project),
            Err(CloudSchemaProtocolError::ScopeMismatch)
        );
    }
    for field in ["schema_id", "revision", "sequence", "change_id", "document"] {
        let mut value: Value = serde_json::from_str(&raw).unwrap();
        value.as_object_mut().unwrap().remove(field);
        assert!(
            CloudSchemaReceipt::from_json(&value.to_string(), "tenant-a", "project-a").is_err(),
            "{field}"
        );
    }
}

#[test]
fn duplicate_keys_are_rejected_before_any_value_conversion() {
    let raw = receipt_raw(&document(1), CHANGE);
    for bad in [
        raw.replacen("\"revision\" : 1", "\"revision\" : 1,\"revision\":1", 1),
        raw.replacen(
            "\"revision\" : 1",
            "\"revision\" : 1,\"\\u0072evision\":1",
            1,
        ),
        raw.replacen(
            "\"format_version\":1",
            "\"format_version\":1,\"format_version\":1",
            1,
        ),
        raw.replacen("\"number\":0.25", "\"number\":0.25,\"number\":2", 1),
    ] {
        assert_ne!(bad, raw);
        assert!(CloudSchemaReceipt::from_json(&bad, "tenant-a", "project-a").is_err());
    }
}

#[test]
fn protocol_numbers_require_integer_tokens_and_portable_opaque_numbers_remain_opaque() {
    let raw = receipt_raw(&document(1), CHANGE);
    for field in ["revision", "sequence"] {
        for token in ["1.0", "1e0", "-0", "true", "2147483648", "null"] {
            let bad = raw.replacen(
                &format!("\"{field}\" : 1"),
                &format!("\"{field}\" : {token}"),
                1,
            );
            assert!(
                CloudSchemaReceipt::from_json(&bad, "tenant-a", "project-a").is_err(),
                "{field}: {token}"
            );
        }
    }
    for token in ["1.0", "1e0", "-0"] {
        let bad = raw.replace("\"revision\":1", &format!("\"revision\":{token}"));
        assert!(
            CloudSchemaReceipt::from_json(&bad, "tenant-a", "project-a").is_err(),
            "document: {token}"
        );
    }
    for token in ["0.0", "0.25", "-0", "1e2"] {
        let valid = raw.replace("\"number\":0.25", &format!("\"number\":{token}"));
        assert!(
            CloudSchemaReceipt::from_json(&valid, "tenant-a", "project-a").is_ok(),
            "opaque: {token}"
        );
    }
    for token in ["NaN", "Infinity", "1e999", "9007199254740992"] {
        let bad = raw.replace("\"number\":0.25", &format!("\"number\":{token}"));
        assert!(CloudSchemaReceipt::from_json(&bad, "tenant-a", "project-a").is_err());
    }
}

#[test]
fn unicode_and_byte_limit_are_checked_on_original_receipts() {
    let raw = receipt_raw(&document(1), CHANGE);
    for bad in [
        raw.replace("人物", "\\ud800"),
        raw.replace("人物", "\\udc00"),
        raw.replace("人物", "\\u0000"),
    ] {
        assert!(CloudSchemaReceipt::from_json(&bad, "tenant-a", "project-a").is_err());
    }
    let at_limit = format!("{}{}", raw, " ".repeat(MAX_CLOUD_SCHEMA_BYTES - raw.len()));
    assert!(CloudSchemaReceipt::from_json(&at_limit, "tenant-a", "project-a").is_ok());
    assert!(CloudSchemaReceipt::from_json(&(at_limit + " "), "tenant-a", "project-a").is_err());
}

#[test]
fn first_receipt_cannot_claim_a_terminal_or_historical_root() {
    let mut bad = document(1);
    bad["entity_types"] = json!([]);
    bad["tombstones"] = json!([{"id":MEMBER,"kind":"entity_type","deleted_revision":1}]);
    assert!(
        CloudSchemaReceipt::from_json(&receipt_raw(&bad, CHANGE), "tenant-a", "project-a").is_err()
    );
    bad["tombstones"] = json!([]);
    bad["deleted"] = json!(true);
    assert!(
        CloudSchemaReceipt::from_json(&receipt_raw(&bad, CHANGE), "tenant-a", "project-a").is_err()
    );
}

#[test]
fn replacement_preserves_request_bytes_and_accepts_only_its_actual_receipt() {
    let previous = receipt(&document(1));
    let candidate = ProjectSchemaDocument::from_json(&document(2).to_string()).unwrap();
    let request = CloudSchemaReplaceRequest::new(&previous, &candidate, NEXT_CHANGE).unwrap();
    let raw = format!(" \n{} ", request.as_json());
    let restored = CloudSchemaReplaceRequest::from_json(&raw, &previous).unwrap();
    assert_eq!(restored.as_json(), raw);
    assert_eq!(restored.expected_revision(), 1);
    assert_eq!(restored.change_id(), NEXT_CHANGE);
    let accepted = CloudSchemaReceipt::from_json(
        &receipt_raw(&document(2), NEXT_CHANGE),
        "tenant-a",
        "project-a",
    )
    .unwrap();
    restored.require_receipt(&accepted).unwrap();
    assert!(restored.require_receipt(&receipt(&document(2))).is_err());
    let newer = CloudSchemaReceipt::from_json(
        &receipt_raw(&document(3), NEXT_CHANGE),
        "tenant-a",
        "project-a",
    )
    .unwrap();
    assert!(restored.require_receipt(&newer).is_err());
    let mut changed = document(2);
    changed["entity_types"][0]["schema"]["opaque"]["number"] = json!(0.5);
    let wrong =
        CloudSchemaReceipt::from_json(&receipt_raw(&changed, NEXT_CHANGE), "tenant-a", "project-a")
            .unwrap();
    assert!(restored.require_receipt(&wrong).is_err());
}

#[test]
fn replacement_allows_member_order_canonicalization_only() {
    let previous = receipt(&document(1));
    let mut candidate = document(2);
    let mut extra = candidate["entity_types"][0].clone();
    extra["id"] = json!("00000000-0000-4000-8000-000000000003");
    extra["name"] = json!("组织");
    candidate["entity_types"]
        .as_array_mut()
        .unwrap()
        .push(extra);
    let request = CloudSchemaReplaceRequest::new(
        &previous,
        &ProjectSchemaDocument::from_json(&candidate.to_string()).unwrap(),
        NEXT_CHANGE,
    )
    .unwrap();
    candidate["entity_types"].as_array_mut().unwrap().reverse();
    let accepted = CloudSchemaReceipt::from_json(
        &receipt_raw(&candidate, NEXT_CHANGE),
        "tenant-a",
        "project-a",
    )
    .unwrap();
    request.require_receipt(&accepted).unwrap();
}

#[test]
fn replacement_rejects_invalid_or_rebased_intent() {
    let previous = receipt(&document(1));
    let request = CloudSchemaReplaceRequest::new(
        &previous,
        &ProjectSchemaDocument::from_json(&document(2).to_string()).unwrap(),
        NEXT_CHANGE,
    )
    .unwrap();
    for field in ["actor_id", "tenant_id", "scope", "schema_id", "if_match"] {
        let mut value: Value = serde_json::from_str(request.as_json()).unwrap();
        value[field] = json!("shadow");
        assert!(CloudSchemaReplaceRequest::from_json(&value.to_string(), &previous).is_err());
    }
    for token in ["0", "1.0", "1e0", "-0", "2"] {
        let bad = request.as_json().replace(
            "\"expected_revision\":1",
            &format!("\"expected_revision\":{token}"),
        );
        assert!(
            CloudSchemaReplaceRequest::from_json(&bad, &previous).is_err(),
            "{token}"
        );
    }
    assert!(
        CloudSchemaReplaceRequest::from_json(request.as_json(), &receipt(&document(2))).is_err()
    );
}

#[test]
fn existing_cloud_command_corpus_matches_strict_queries_and_replacement() {
    let fixtures: Value = serde_json::from_str(include_str!(
        "../../../../contracts/project-schema-v1/cloud-rpc-fixtures.json"
    ))
    .unwrap();
    for case in fixtures.as_array().unwrap() {
        let raw = case["value"].to_string();
        let valid = match case["definition"].as_str().unwrap() {
            "receiptRequest" => CloudSchemaReceiptQuery::from_json(&raw).is_ok(),
            "historyRequest" => CloudSchemaHistoryQuery::from_json(&raw).is_ok(),
            "replaceRequest" => {
                let mut root = case["value"]["document"].clone();
                root["revision"] = json!(1);
                CloudSchemaReplaceRequest::from_json(&raw, &receipt(&root)).is_ok()
            }
            "readRequest" => continue, // generation/read envelopes belong to the sidecar.
            // Bootstrap/preview belong to a later protocol batch, not this M2 decoder.
            _ => continue,
        };
        assert_eq!(valid, case["valid"].as_bool().unwrap(), "{}", case["name"]);
    }
}

#[test]
fn queries_reject_duplicate_shadow_fields_and_noninteger_cursors() {
    for token in ["0.0", "0e0", "-0", "2147483648", "true"] {
        let raw = format!("{{\"schema_id\":\"{SCHEMA}\",\"after_revision\":{token},\"limit\":1}}");
        assert!(CloudSchemaHistoryQuery::from_json(&raw).is_err());
    }
    let duplicate = format!(
        "{{\"schema_id\":\"{SCHEMA}\",\"schema_id\":\"{SCHEMA}\",\"change_id\":\"{CHANGE}\"}}"
    );
    assert!(CloudSchemaReceiptQuery::from_json(&duplicate).is_err());
}
