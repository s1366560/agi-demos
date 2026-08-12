use std::{error::Error, sync::Arc};

use bcs_bot_store::PersistentBotRepo;
use bcs_cache_local::InMemoryCachePlugin;
use bcs_collaboration_store::MySqlCollaborationStore;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use bcs_domain::CollaborationDefinition;
use bcs_friend_store::{DbFriendRequestStore, DbFriendStore};
use bcs_group_store::MySqlGroupStore;
use bcs_message_store::MySqlMessageStore;
use bcs_organization_store::DbOrganizationStore;
use bcs_relation_store::DbRelationStore;
use bcs_service_api::StateMachineDefinitionRepoPort;
use bcs_session_store::MySqlSessionStore;
use bcs_test_support::contract::repo::{
    bot_repo_port_contract_tests, friend_repo_port_contract_tests,
    friend_request_repo_port_contract_tests, group_repo_port_contract_tests,
    message_repo_contract_tests, organization_repo_contract_tests,
    relation_repo_port_contract_tests, session_repo_port_contract_tests,
};

const ENV: &str = "postgres-contract";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_workspace_stores_pass_repository_contracts() -> Result<(), Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    let db: Arc<dyn DbPlugin> = Arc::new(PostgresDbPlugin::connect(&database_url, 4).await?);

    let bot_repo = PersistentBotRepo::with_plugins_flavor(
        Arc::new(InMemoryCachePlugin::new()),
        db.clone(),
        DbSqlFlavor::Postgres,
    );
    bot_repo_port_contract_tests(&bot_repo).await;

    organization_repo_contract_tests(&DbOrganizationStore::postgres(db.clone())).await;
    relation_repo_port_contract_tests(&DbRelationStore::postgres(db.clone())).await;
    group_repo_port_contract_tests(&MySqlGroupStore::postgres(db.clone(), ENV.to_string())).await;
    session_repo_port_contract_tests(&MySqlSessionStore::postgres(db.clone(), ENV.to_string()))
        .await;

    seed_message_contract_session(db.as_ref()).await?;
    message_repo_contract_tests(&MySqlMessageStore::postgres(db.clone(), ENV.to_string())).await;

    friend_repo_port_contract_tests(&DbFriendStore::postgres(db.clone())).await;
    friend_request_repo_port_contract_tests(&DbFriendRequestStore::postgres(db.clone())).await;

    collaboration_definition_roundtrip(db).await?;
    Ok(())
}

async fn seed_message_contract_session(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static(
            "INSERT INTO bcs_group_sessions \
             (session_id, group_id, env, participants, current_msg_seq) VALUES (",
        )
        .bind("contract-group:abcd1234")
        .push_static(", ")
        .bind("contract-group")
        .push_static(", ")
        .bind(ENV)
        .push_static(", ")
        .bind("[]")
        .push_static(", 0) ON CONFLICT(env, session_id) DO UPDATE SET current_msg_seq = 0")
        .build();
    db.execute(statement).await?;
    Ok(())
}

async fn collaboration_definition_roundtrip(db: Arc<dyn DbPlugin>) -> Result<(), Box<dyn Error>> {
    let store = MySqlCollaborationStore::postgres(db, ENV.to_string());
    let definition = test_definition()?;

    StateMachineDefinitionRepoPort::upsert(&store, definition.clone()).await?;
    let loaded = StateMachineDefinitionRepoPort::get(&store, &definition.id, definition.version)
        .await?
        .ok_or_else(|| std::io::Error::other("collaboration definition does not exist"))?;

    assert_eq!(loaded.id, definition.id);
    assert_eq!(loaded.version, definition.version);
    assert_eq!(loaded.name, definition.name);
    Ok(())
}

fn test_definition() -> Result<CollaborationDefinition, serde_yaml::Error> {
    serde_yaml::from_str(
        r#"
api_version: bcs.collaboration/v1
id: sm_postgres_contract
version: 1
name: PostgreSQL Contract
participants:
  driver:
    bot_id: driver-bot
    required: true
runtime:
  kind: state_machine
  state_machine:
    version: 1
    graph_mode: acyclic
    nodes:
      answer:
        kind: bot_task
        display_name: Answer
        assignee:
          type: bot_binding
          binding: driver
        instruction: Say hello.
        final_output: true
"#,
    )
}
