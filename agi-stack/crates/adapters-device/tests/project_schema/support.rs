use std::path::PathBuf;

use agistack_adapters_device::knowledge::{
    project_schema::{ProjectSchemaMutation, ProjectSchemaStorageResult},
    SqliteKnowledgeRepository,
};
use agistack_core::{knowledge::KnowledgeScope, project_schema::ProjectSchemaDocument};
use rusqlite::Connection;
use serde_json::{json, Value};

pub const SCHEMA_ID: &str = "00000000-0000-4000-8000-000000000001";
pub const ENTITY_A: &str = "00000000-0000-4000-8000-000000000002";
pub const ENTITY_B: &str = "00000000-0000-4000-8000-000000000003";
pub const EDGE_ID: &str = "00000000-0000-4000-8000-000000000004";
pub const MAP_ID: &str = "00000000-0000-4000-8000-000000000005";

pub fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    }
}

pub fn current() -> ProjectSchemaStorageResult<()> {
    Ok(())
}

pub fn value(scope: &KnowledgeScope, revision: u32) -> Value {
    let member = |id: &str, name: &str| {
        json!({
            "id":id,"name":name,"description":"Original description.",
            "schema":{"opaque":[null,true,"unchanged",0.5,9007199254740991_i64]},
            "status":"ENABLED","source":"user",
        })
    };
    json!({
        "format_version":1,"tenant_id":scope.tenant_id,"project_id":scope.project_id,
        "schema_id":SCHEMA_ID,"revision":revision,"deleted":false,
        "entity_types":[member(ENTITY_B,"Organization"),member(ENTITY_A,"Person")],
        "edge_types":[member(EDGE_ID,"MAINTAINS")],
        "mappings":[{"id":MAP_ID,"source_type_id":ENTITY_A,"target_type_id":ENTITY_B,
            "edge_type_id":EDGE_ID,"status":"ENABLED","source":"user"}],"tombstones":[],
    })
}

pub fn command(scope: &KnowledgeScope, revision: u32) -> ProjectSchemaMutation {
    ProjectSchemaMutation {
        document: ProjectSchemaDocument::from_json(&value(scope, revision).to_string()).unwrap(),
        expected_revision: revision - 1,
        change_id: uuid::Uuid::new_v4().to_string(),
    }
}

pub fn changed(
    command: &ProjectSchemaMutation,
    edit: impl FnOnce(&mut Value),
) -> ProjectSchemaMutation {
    let mut value = command.document.to_value();
    edit(&mut value);
    ProjectSchemaMutation {
        document: ProjectSchemaDocument::from_json(&value.to_string()).unwrap(),
        ..command.clone()
    }
}

pub struct Database(pub PathBuf);
impl Database {
    pub fn new() -> Self {
        Self(std::env::temp_dir().join(format!(
            "project-schema-storage-{}.sqlite",
            uuid::Uuid::new_v4()
        )))
    }
    pub fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
    pub fn sql(&self) -> Connection {
        Connection::open(&self.0).unwrap()
    }
    pub fn counts(&self) -> (u32, u32) {
        self.sql()
            .query_row(
                "SELECT (SELECT count(*) FROM knowledge_project_schema_heads),
            (SELECT count(*) FROM knowledge_project_schema_changes)",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
        for suffix in ["-wal", "-shm"] {
            let _ = std::fs::remove_file(format!("{}{suffix}", self.0.display()));
        }
    }
}
