use agistack_adapters_postgres::{ConversationMutationAccess, PgAgentConversationRepository};

use super::*;

fn assert_undefined_table(error: sqlx::Error) {
    assert_eq!(
        error
            .as_database_error()
            .and_then(|error| error.code())
            .as_deref(),
        Some("42P01"),
        "fixture queries must fail instead of reaching public tables"
    );
}

#[tokio::test]
async fn postgres_fixture_rejects_queries_to_retired_workspace_tables() {
    let Some((pool, scope)) = standalone_fixture().await else {
        return;
    };
    assert_eq!(shared_reader(&pool, &scope).await, SHARED_READER);
    let conversation_count: i64 = sqlx::query_scalar("SELECT count(*) FROM conversations")
        .fetch_one(&pool)
        .await
        .unwrap();
    assert_eq!(conversation_count, 1);
    for table in RETIRED_WORKSPACE_TABLES {
        let error = sqlx::query(&format!("SELECT 1 FROM {table} LIMIT 0"))
            .fetch_optional(&pool)
            .await
            .expect_err("retired table query must fail even if public still contains that table");
        assert_undefined_table(error);
    }
    pool.close().await;
}

#[tokio::test]
async fn postgres_fixtures_isolate_membership_revocation_between_connections() {
    let (first, second) = tokio::join!(standalone_fixture(), standalone_fixture());
    let (Some((first_pool, first_scope)), Some((second_pool, second_scope))) = (first, second)
    else {
        return;
    };
    // Deliberately identical IDs prove isolation comes from the connection,
    // rather than unique data that would hide an accidental public-table read.
    assert_eq!(first_scope.id, second_scope.id);
    let first = PgAgentConversationRepository::new(first_pool.clone());
    let second = PgAgentConversationRepository::new(second_pool.clone());
    assert_eq!(
        first
            .message_send_access(
                &first_scope.user_id,
                &first_scope.project_id,
                &first_scope.id
            )
            .await
            .unwrap(),
        ConversationMutationAccess::Allowed
    );
    sqlx::query("DELETE FROM pg_temp.user_projects WHERE user_id = $1")
        .bind(&first_scope.user_id)
        .execute(&first_pool)
        .await
        .unwrap();
    assert_eq!(
        first
            .message_send_access(
                &first_scope.user_id,
                &first_scope.project_id,
                &first_scope.id
            )
            .await
            .unwrap(),
        ConversationMutationAccess::Denied
    );
    assert_eq!(
        second
            .message_send_access(
                &second_scope.user_id,
                &second_scope.project_id,
                &second_scope.id
            )
            .await
            .unwrap(),
        ConversationMutationAccess::Allowed
    );
    assert_eq!(
        shared_reader(&first_pool, &first_scope).await,
        SHARED_READER
    );
    assert_eq!(
        shared_reader(&second_pool, &second_scope).await,
        SHARED_READER
    );
    first_pool.close().await;
    second_pool.close().await;
}

#[tokio::test]
async fn postgres_fixture_replacement_connection_cannot_fall_back_to_public() {
    let Some((pool, _scope)) = standalone_fixture().await else {
        return;
    };
    pool.acquire().await.unwrap().close().await.unwrap();
    let error = sqlx::query("SELECT id FROM conversations LIMIT 0")
        .fetch_optional(&pool)
        .await
        .expect_err("a fresh connection has no fixture and must not read public conversations");
    assert_undefined_table(error);
    pool.close().await;
}
