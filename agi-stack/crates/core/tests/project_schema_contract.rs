use agistack_core::project_schema::ProjectSchemaDocument;
use serde_json::Value;

#[test]
fn shared_schema_snapshot_and_transition_fixtures() {
    let cases: Value = serde_json::from_str(include_str!(
        "../../../../contracts/project-schema-v1/fixtures.json"
    ))
    .expect("shared fixture JSON");
    for case in cases.as_array().expect("fixture cases") {
        let raw = case["document"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| case["document"].to_string());
        let result = ProjectSchemaDocument::from_json(&raw).and_then(|document| {
            if let Some(previous) = case.get("previous") {
                let previous = if previous.is_null() {
                    None
                } else {
                    Some(ProjectSchemaDocument::from_json(&previous.to_string())?)
                };
                let expected = case["expected_revision"]
                    .as_u64()
                    .and_then(|revision| u32::try_from(revision).ok())
                    .ok_or(agistack_core::project_schema::ProjectSchemaError::RevisionConflict)?;
                document.validate_successor(previous.as_ref(), expected)?;
            }
            let roundtrip = ProjectSchemaDocument::from_json(&document.to_value().to_string())?;
            assert_eq!(roundtrip, document);
            assert_eq!(roundtrip.schema_id(), document.schema_id());
            assert_eq!(roundtrip.tenant_id(), document.tenant_id());
            assert_eq!(roundtrip.project_id(), document.project_id());
            assert_eq!(roundtrip.revision(), document.revision());
            assert_eq!(roundtrip.is_deleted(), document.is_deleted());
            assert_eq!(roundtrip.entity_types(), document.entity_types());
            assert_eq!(roundtrip.edge_types(), document.edge_types());
            assert_eq!(roundtrip.mappings(), document.mappings());
            assert_eq!(roundtrip.tombstones(), document.tombstones());
            Ok(())
        });
        assert_eq!(
            result.is_ok(),
            case["valid"].as_bool().unwrap(),
            "{}: {result:?}",
            case["name"]
        );
    }
}
