use std::{fs, path::PathBuf, sync::Arc};

use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;
use agistack_plugin_host::{
    desktop_sidecar_host_definition_v2, desktop_sidecar_http_routes_definition_v2,
    parse_profile_snapshot_v2, DataPlaneTargetV2, LoaderV2, RuntimeGenerationV2,
};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::*;
use crate::local_runtime::{tests::test_state, LocalRuntimeState};

#[path = "http_tests.rs"]
mod http_tests;
#[path = "push_http_tests.rs"]
mod push_http_tests;
#[path = "push_session_tests.rs"]
mod push_session_tests;
#[path = "storage_tests.rs"]
mod storage_tests;

const TOKEN: &str = "knowledge-generation-test-token";

#[tokio::test]
async fn typed_mutations_reject_forged_authors_and_replay_after_deletion() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let auth = authenticated(&state);
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let scope = operation_scope(&auth, &lease);
    let operation = KnowledgeOperationV2::admit(lease, &auth, &scope).unwrap();
    let MemoryMutation::Create { mut memory } = mutation(&auth) else {
        panic!("create fixture")
    };
    memory.author_id = "forged-author".into();
    assert!(matches!(
        operation
            .mutate("forged-create", MemoryMutation::Create { memory })
            .await,
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    assert!(operation.changes(0, 20).await.unwrap().is_empty());
    let created = operation.mutate("create", mutation(&auth)).await.unwrap();
    let mut changed = created.receipt.memory.clone();
    changed.author_id = "forged-author".into();
    assert!(matches!(
        operation
            .mutate(
                "update",
                MemoryMutation::Update {
                    memory: changed,
                    expected_revision: 1
                }
            )
            .await,
        Err(KnowledgeAuthorityErrorV2::Knowledge(
            KnowledgeError::InvalidInput
        ))
    ));
    let mut changed = created.receipt.memory.clone();
    changed.content = "updated".into();
    let update = MemoryMutation::Update {
        memory: changed,
        expected_revision: 1,
    };
    let updated = operation.mutate("update", update.clone()).await.unwrap();
    operation
        .mutate(
            "delete",
            MemoryMutation::Delete {
                id: created.receipt.memory.id.clone(),
                expected_revision: 2,
            },
        )
        .await
        .unwrap();
    let replay = operation.mutate("update", update).await.unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.receipt.sequence, updated.receipt.sequence);
    assert_eq!(replay.receipt.memory.author_id, auth.user.user_id);
    assert_eq!(operation.changes(0, 20).await.unwrap().len(), 3);
    drop(operation);
    state.platform_plugin_authority_v2.deactivate().await;
}
const BOOTSTRAP: &str =
    include_str!("../../../../../../../shared/profiles/memstack-default-bootstrap.v2.json");

struct TestDirectory(PathBuf);
impl TestDirectory {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-authority-{}", Uuid::new_v4())))
    }
}
impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn fixture(number: u64) -> ProfileSnapshotV2 {
    let mut snapshot: Value = serde_json::from_str(BOOTSTRAP).unwrap();
    let entry = snapshot["entries"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|entry| entry["module_ref"] == MODULE_REF)
        .unwrap();
    assert_eq!(
        entry["enabled"], false,
        "the production release must stay disabled"
    );
    assert_eq!(
        entry["config"],
        json!({"release_contract": RELEASE_CONTRACT, "release_state": "closed"})
    );
    entry["enabled"] = json!(true);
    snapshot["profile_id"] = json!("knowledge-integration-test");
    snapshot["generation"] = json!(number);
    snapshot.as_object_mut().unwrap().remove("digest");
    snapshot["digest"] = json!(format!(
        "{:x}",
        Sha256::digest(serde_jcs::to_vec(&snapshot).unwrap())
    ));
    let snapshot = parse_profile_snapshot_v2(&serde_json::to_string(&snapshot).unwrap()).unwrap();
    let module = snapshot
        .manifests
        .iter()
        .flat_map(|manifest| manifest.modules.iter())
        .find(|module| module.module_ref == MODULE_REF)
        .unwrap();
    assert_eq!(module.contract, contract().unwrap());
    assert_eq!(
        module.artifact.digest,
        format!(
            "sha256:{:x}",
            Sha256::digest(include_bytes!("../knowledge_authority_v2.rs"))
        )
    );
    snapshot
}

async fn stage(
    directory: &TestDirectory,
    number: u64,
    validation: bool,
) -> (ProfileSnapshotV2, Arc<RuntimeGenerationV2>) {
    let snapshot = fixture(number);
    let mut knowledge = definition(Some(directory.0.clone())).unwrap();
    if validation {
        knowledge.module = Arc::new(KnowledgeModuleV2 {
            app_data_dir: Some(directory.0.clone()),
            internal_validation: true,
        });
    }
    let generation = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            knowledge,
        ],
    )
    .stage(snapshot.clone())
    .await
    .unwrap();
    (snapshot, generation)
}

async fn publish(
    state: &LocalRuntimeState,
    directory: &TestDirectory,
    number: u64,
    validation: bool,
) -> Arc<RuntimeGenerationV2> {
    let (snapshot, generation) = stage(directory, number, validation).await;
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(
            &snapshot,
            &serde_json::to_value(&snapshot).unwrap(),
            Arc::clone(&generation),
        )
        .await;
    generation
}

fn authenticated(state: &LocalRuntimeState) -> AuthenticatedContext {
    state
        .session_store
        .validate_session_credential(TOKEN, chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap()
}

fn operation_scope(
    auth: &AuthenticatedContext,
    lease: &ActivePlatformPluginGenerationLeaseV2,
) -> KnowledgeOperationScopeV2 {
    KnowledgeOperationScopeV2 {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
        context_revision: auth.workspace.revision,
        profile_id: lease.descriptor().profile_id.clone(),
        generation: lease.descriptor().generation,
        digest: lease.descriptor().digest.clone(),
    }
}

fn mutation(auth: &AuthenticatedContext) -> MemoryMutation {
    MemoryMutation::Create {
        memory: Memory {
            id: "knowledge-test-memory".into(),
            project_id: auth.workspace.project_id.clone(),
            title: "Knowledge".into(),
            content: "generation-owned content".into(),
            author_id: auth.user.user_id.clone(),
            content_type: "text".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            embedding: None,
        },
    }
}

#[tokio::test]
async fn closed_generation_exposes_service_but_never_opens_storage() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, false).await;
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let auth = authenticated(&state);
    let scope = operation_scope(&auth, &lease);
    assert!(matches!(
        KnowledgeOperationV2::admit(lease, &auth, &scope),
        Err(KnowledgeAuthorityErrorV2::ReleaseClosed)
    ));
    assert!(!directory.0.exists());
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn generation_operation_checks_scope_revision_permissions_and_durable_receipts() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let auth = authenticated(&state);
    let scope = operation_scope(&auth, &lease);
    let mut wrong = scope.clone();
    wrong.context_revision += 1;
    assert!(matches!(
        KnowledgeOperationV2::admit(Arc::clone(&lease), &auth, &wrong),
        Err(KnowledgeAuthorityErrorV2::ScopeMismatch)
    ));
    wrong = scope.clone();
    wrong.tenant_id = "another-tenant".into();
    assert!(matches!(
        KnowledgeOperationV2::admit(Arc::clone(&lease), &auth, &wrong),
        Err(KnowledgeAuthorityErrorV2::ScopeMismatch)
    ));
    wrong = scope.clone();
    wrong.project_id = "another-project".into();
    assert!(matches!(
        KnowledgeOperationV2::admit(Arc::clone(&lease), &auth, &wrong),
        Err(KnowledgeAuthorityErrorV2::ScopeMismatch)
    ));
    wrong = scope.clone();
    wrong.generation += 1;
    assert!(matches!(
        KnowledgeOperationV2::admit(Arc::clone(&lease), &auth, &wrong),
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    assert!(!directory.0.exists());
    let operation = KnowledgeOperationV2::admit(Arc::clone(&lease), &auth, &scope).unwrap();
    let first = operation.mutate("create", mutation(&auth)).await.unwrap();
    let replay = operation.mutate("create", mutation(&auth)).await.unwrap();
    assert!(replay.replayed);
    assert_eq!(first.receipt.sequence, replay.receipt.sequence);
    assert_eq!(
        operation
            .get("knowledge-test-memory")
            .await
            .unwrap()
            .unwrap()
            .version,
        1
    );
    assert_eq!(operation.list(20, 0).await.unwrap().len(), 1);
    assert_eq!(operation.changes(0, 20).await.unwrap().len(), 1);
    assert!(operation
        .change(first.receipt.sequence)
        .await
        .unwrap()
        .is_some());
    let mut viewer = auth.clone();
    viewer.membership_role = "viewer".into();
    let view = KnowledgeOperationV2::admit(Arc::clone(&lease), &viewer, &scope).unwrap();
    assert!(view.get("knowledge-test-memory").await.unwrap().is_some());
    assert!(matches!(
        view.mutate("denied", mutation(&viewer)).await,
        Err(KnowledgeAuthorityErrorV2::Forbidden)
    ));
    drop(view);
    drop(operation);
    drop(lease);
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn operation_pins_old_generation_until_it_finishes_then_revokes_service() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let auth = authenticated(&state);
    let scope = operation_scope(&auth, &lease);
    let operation = KnowledgeOperationV2::admit(lease, &auth, &scope).unwrap();
    let escaped = Arc::clone(&operation.authority);
    operation.mutate("create", mutation(&auth)).await.unwrap();
    let (snapshot, generation) = stage(&directory, 2, false).await;
    let retirement = state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    assert!(operation
        .get("knowledge-test-memory")
        .await
        .unwrap()
        .is_some());
    let new_lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    assert!(matches!(
        KnowledgeOperationV2::admit(new_lease, &auth, &scope),
        Err(KnowledgeAuthorityErrorV2::GenerationMismatch)
    ));
    drop(operation);
    retirement.dispose().await;
    tokio::time::timeout(std::time::Duration::from_secs(5), async {
        loop {
            if matches!(
                escaped.repository(),
                Err(KnowledgeAuthorityErrorV2::Disposed)
            ) {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("generation release must dispose knowledge storage");
    assert!(matches!(
        escaped.repository(),
        Err(KnowledgeAuthorityErrorV2::Disposed)
    ));
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn contract_rejects_attempt_to_open_release_through_profile_config() {
    let directory = TestDirectory::new();
    let mut snapshot = fixture(1);
    let entry = snapshot
        .entries
        .iter_mut()
        .find(|entry| entry.module_ref == MODULE_REF)
        .unwrap();
    entry.config.insert("release_state".into(), json!("ready"));
    let result = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            definition(Some(directory.0.clone())).unwrap(),
        ],
    )
    .stage(snapshot)
    .await;
    assert!(matches!(
        result,
        Err(RuntimeV2Error::InvalidModuleConfig { .. })
    ));
    assert!(!directory.0.exists());
}
