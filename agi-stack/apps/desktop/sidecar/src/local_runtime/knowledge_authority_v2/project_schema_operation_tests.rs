//! Internal-only operation tests; no public schema endpoint is installed.
use super::super::project_schema::{ProjectSchemaOperationError, ProjectSchemaOperationV2};
use super::*;
use agistack_adapters_device::knowledge::project_schema::{
    ProjectSchemaMutation, ProjectSchemaStorageError,
};
use agistack_core::project_schema::{ProjectSchemaDocument, ProjectSchemaError};
use rusqlite::Connection;

#[path = "project_schema_operation_tests/admission.rs"]
mod admission;
#[path = "project_schema_operation_tests/contention.rs"]
mod contention;
#[path = "project_schema_operation_tests/generation.rs"]
mod generation;
#[path = "project_schema_operation_tests/operations.rs"]
mod operations;

struct Fixture {
    directory: TestDirectory,
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
    operation: Arc<ProjectSchemaOperationV2>,
}

impl Fixture {
    async fn new() -> Self {
        let directory = TestDirectory::new();
        let state = test_state(TOKEN);
        publish(&state, &directory, 1, true).await;
        let auth = authenticated(&state);
        let operation = Arc::new(admit(&state, &auth).unwrap());
        Self {
            directory,
            state,
            auth,
            operation,
        }
    }

    fn sql(&self) -> Connection {
        Connection::open(self.directory.0.join("knowledge/memories.db")).unwrap()
    }

    fn counts(&self) -> (u32, u32, u32) {
        self.sql()
            .query_row(
                "SELECT
            (SELECT count(*) FROM knowledge_project_schema_heads),
            (SELECT count(*) FROM knowledge_project_schema_changes),
            (SELECT count(*) FROM knowledge_memories)",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap()
    }

    fn command(&self, revision: u32) -> ProjectSchemaMutation {
        command(&self.auth, revision)
    }

    fn reject_all(&self, first: &ProjectSchemaMutation) {
        assert!(matches!(
            self.operation.read(&self.state, &self.auth),
            Err(ProjectSchemaOperationError::Authority(_))
        ));
        assert!(matches!(
            self.operation
                .receipt(&self.state, &self.auth, &first.change_id),
            Err(ProjectSchemaOperationError::Authority(_))
        ));
        assert!(matches!(
            self.operation.history(&self.state, &self.auth, 0, 100),
            Err(ProjectSchemaOperationError::Authority(_))
        ));
        assert!(matches!(
            self.operation.bootstrap(&self.state, &self.auth, first),
            Err(ProjectSchemaOperationError::Authority(_))
        ));
        assert!(matches!(
            self.operation
                .replace(&self.state, &self.auth, &self.command(2)),
            Err(ProjectSchemaOperationError::Authority(_))
        ));
        assert_eq!(self.counts(), (1, 1, 0));
    }
}

fn admit(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
) -> Result<ProjectSchemaOperationV2, ProjectSchemaOperationError> {
    let lease = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let scope = operation_scope(auth, &lease);
    ProjectSchemaOperationV2::admit(state, lease, auth, &scope)
}

fn command(auth: &AuthenticatedContext, revision: u32) -> ProjectSchemaMutation {
    ProjectSchemaMutation {
        change_id: Uuid::new_v4().to_string(),
        expected_revision: revision - 1,
        document: ProjectSchemaDocument::from_json(
            &json!({
                "format_version":1, "tenant_id":auth.workspace.tenant_id,
                "project_id":auth.workspace.project_id,
                "schema_id":"00000000-0000-4000-8000-000000000001",
                "revision":revision, "deleted":false,
                "entity_types":[], "edge_types":[], "mappings":[], "tombstones":[],
            })
            .to_string(),
        )
        .unwrap(),
    }
}
