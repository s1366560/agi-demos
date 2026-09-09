use agistack_core::project_schema::{
    projection::{
        equivalent_content, project_bootstrap, project_root_after_empty_seed, project_successor,
    },
    ProjectSchemaDocument, MAX_REVISION,
};
use serde_json::{json, Value};

const ENTITY_A: &str = "00000000-0000-4000-8000-000000000002";
const ENTITY_B: &str = "00000000-0000-4000-8000-000000000003";
const EDGE: &str = "00000000-0000-4000-8000-000000000004";
const MAPPING: &str = "00000000-0000-4000-8000-000000000005";

fn root() -> ProjectSchemaDocument {
    let member = |id, name| {
        json!({
            "id":id,"name":name,"description":"Uninterpreted description",
            "schema":{"opaque":[null,true,0.5,"name",{"unchanged":9007199254740991_i64}]},
            "status":"ENABLED","source":"user",
        })
    };
    parse(json!({
        "format_version":1,"tenant_id":"native-tenant","project_id":"native-project",
        "schema_id":"00000000-0000-4000-8000-000000000001",
        "revision":1,"deleted":false,
        "entity_types":[member(ENTITY_A,"Person"),member(ENTITY_B,"Organization")],
        "edge_types":[member(EDGE,"MAINTAINS")],
        "mappings":[{"id":MAPPING,"source_type_id":ENTITY_A,"target_type_id":ENTITY_B,
            "edge_type_id":EDGE,"status":"ENABLED","source":"user"}],"tombstones":[],
    }))
}

fn parse(value: Value) -> ProjectSchemaDocument {
    ProjectSchemaDocument::from_json(&value.to_string()).unwrap()
}

fn edit(
    document: &ProjectSchemaDocument,
    change: impl FnOnce(&mut Value),
) -> ProjectSchemaDocument {
    let mut value = document.to_value();
    change(&mut value);
    parse(value)
}

fn seed() -> ProjectSchemaDocument {
    edit(&root(), |value| {
        value["tenant_id"] = json!("cloud-tenant");
        value["project_id"] = json!("cloud-project");
        for field in ["entity_types", "edge_types", "mappings"] {
            value[field] = json!([]);
        }
    })
}

#[test]
fn bootstrap_projects_only_scope_and_keeps_opaque_definitions() {
    let source = root();
    let original = source.clone();
    let target = project_bootstrap(&source, "cloud-tenant", "cloud-project").unwrap();
    assert_eq!(target.tenant_id(), "cloud-tenant");
    assert_eq!(target.project_id(), "cloud-project");
    assert_eq!(target.revision(), 1);
    assert_eq!(target.entity_types(), source.entity_types());
    assert_eq!(target.edge_types(), source.edge_types());
    assert_eq!(target.mappings(), source.mappings());
    assert!(equivalent_content(&source, &target));
    assert_eq!(source, original);
    assert!(project_bootstrap(&source, "", "cloud-project").is_err());
}

#[test]
fn shifted_counters_preserve_old_tombstones_through_terminal_history() {
    let source1 = root();
    let target1 = seed();
    assert!(!equivalent_content(&source1, &target1));
    let target2 = project_root_after_empty_seed(&source1, &target1).unwrap();
    assert_eq!(target2.revision(), 2);
    assert!(equivalent_content(&source1, &target2));
    let source2 = edit(&source1, |value| {
        value["revision"] = json!(2);
        value["mappings"] = json!([]);
        value["tombstones"] = json!([{"id":MAPPING,"kind":"mapping","deleted_revision":2}]);
    });
    let target3 = project_successor(&source1, &source2, &target2).unwrap();
    assert_eq!(target3.revision(), 3);
    assert_eq!(target3.tombstones()[0].deleted_revision, 3);
    assert!(equivalent_content(&source2, &target3));
    let source3 = edit(&source2, |value| {
        value["revision"] = json!(3);
        value["entity_types"]
            .as_array_mut()
            .unwrap()
            .retain(|item| item["id"] == ENTITY_B);
        value["edge_types"] = json!([]);
        value["tombstones"].as_array_mut().unwrap().extend([
            json!({"id":ENTITY_A,"kind":"entity_type","deleted_revision":3}),
            json!({"id":EDGE,"kind":"edge_type","deleted_revision":3}),
        ]);
    });
    let target4 = project_successor(&source2, &source3, &target3).unwrap();
    assert_eq!(target4.revision(), 4);
    assert_eq!(
        target4
            .tombstones()
            .iter()
            .find(|item| item.id == MAPPING)
            .unwrap()
            .deleted_revision,
        3
    );
    for id in [ENTITY_A, EDGE] {
        assert_eq!(
            target4
                .tombstones()
                .iter()
                .find(|item| item.id == id)
                .unwrap()
                .deleted_revision,
            4
        );
    }
    let source4 = edit(&source3, |value| {
        value["revision"] = json!(4);
        value["deleted"] = json!(true);
        value["entity_types"] = json!([]);
        value["tombstones"]
            .as_array_mut()
            .unwrap()
            .push(json!({"id":ENTITY_B,"kind":"entity_type","deleted_revision":4}));
    });
    let target5 = project_successor(&source3, &source4, &target4).unwrap();
    assert!(target5.is_deleted());
    assert_eq!(target5.revision(), 5);
    assert!(equivalent_content(&source4, &target5));
    assert!(project_bootstrap(&source4, "other", "project").is_err());
    assert!(project_successor(&source1, &source3, &target2).is_err());
}

#[test]
fn baseline_uses_ids_and_exact_definitions_but_ignores_member_order() {
    let source = root();
    let target = project_bootstrap(&source, "cloud", "project").unwrap();
    let reordered = edit(&target, |value| {
        value["entity_types"].as_array_mut().unwrap().reverse()
    });
    assert!(equivalent_content(&source, &reordered));
    let next = edit(&source, |value| value["revision"] = json!(2));
    assert!(project_successor(&source, &next, &reordered).is_ok());
    for field in ["name", "description", "source"] {
        let changed = edit(&target, |value| {
            value["entity_types"][0][field] = json!("different")
        });
        assert!(!equivalent_content(&source, &changed));
        assert!(project_successor(&source, &next, &changed).is_err());
    }
    let changed = edit(&target, |value| {
        value["entity_types"][0]["schema"]["new"] = json!(true)
    });
    assert!(!equivalent_content(&source, &changed));
    let changed = edit(&target, |value| {
        value["schema_id"] = json!("00000000-0000-4000-8000-000000000099")
    });
    assert!(!equivalent_content(&source, &changed));
    assert!(project_successor(&source, &next, &changed).is_err());
}

#[test]
fn source_gaps_scope_changes_and_destination_exhaustion_cannot_be_projected() {
    let source = root();
    let target = project_bootstrap(&source, "cloud", "project").unwrap();
    let next = edit(&source, |value| value["revision"] = json!(2));
    let exhausted = edit(&target, |value| value["revision"] = json!(MAX_REVISION));
    assert!(project_successor(&source, &next, &exhausted).is_err());
    let gap = edit(&source, |value| value["revision"] = json!(3));
    assert!(project_successor(&source, &gap, &target).is_err());
    let foreign = edit(&next, |value| value["project_id"] = json!("foreign"));
    assert!(project_successor(&source, &foreign, &target).is_err());
    assert!(project_bootstrap(&next, "cloud", "project").is_err());
    assert!(project_root_after_empty_seed(&source, &target).is_err());
    let later_seed = edit(&seed(), |value| value["revision"] = json!(2));
    assert!(project_root_after_empty_seed(&source, &later_seed).is_err());
}

#[test]
fn missing_or_changed_tombstone_baseline_is_not_equivalent() {
    let source1 = root();
    let source2 = edit(&source1, |value| {
        value["revision"] = json!(2);
        value["mappings"] = json!([]);
        value["tombstones"] = json!([{"id":MAPPING,"kind":"mapping","deleted_revision":2}]);
    });
    let target1 = project_bootstrap(&source1, "cloud", "project").unwrap();
    let target2 = project_successor(&source1, &source2, &target1).unwrap();
    let source3 = edit(&source2, |value| value["revision"] = json!(3));
    for corrupt in [
        edit(&target2, |value| value["tombstones"] = json!([])),
        edit(&target2, |value| {
            value["tombstones"][0]["kind"] = json!("edge_type")
        }),
    ] {
        assert!(!equivalent_content(&source2, &corrupt));
        assert!(project_successor(&source2, &source3, &corrupt).is_err());
    }
    let reinterpreted = edit(&source3, |value| {
        value["tombstones"][0]["deleted_revision"] = json!(3)
    });
    assert!(project_successor(&source2, &reinterpreted, &target2).is_err());
}
