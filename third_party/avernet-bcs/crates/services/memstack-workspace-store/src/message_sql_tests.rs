use super::*;

fn write(mentions_json: &str) -> WorkspaceMessageWrite {
    WorkspaceMessageWrite {
        scope: WorkspaceMessageScope {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
        },
        message_id: "message-1".to_string(),
        session_id: "session-1".to_string(),
        correlation_id: "correlation-1".to_string(),
        outbox_id: "outbox-1".to_string(),
        sender_id: "user-1".to_string(),
        sender_name: "user-1@example.com".to_string(),
        sender_is_superuser: false,
        content_json: "\"hello\"".to_string(),
        mentions_json: mentions_json.to_string(),
        parent_message_id: None,
        metadata_json: "{}".to_string(),
        idempotency_key: "message-key-1".to_string(),
        request_hash: "a".repeat(64),
        created_at_ms: 1_700_000_000_000,
        event_payload_json: "{}".to_string(),
        event_metadata_json: "{}".to_string(),
    }
}

fn statement(step: &DbTransactionStep) -> &DbStatement {
    match step {
        DbTransactionStep::Query(statement)
        | DbTransactionStep::Execute(statement)
        | DbTransactionStep::QueryChecked { statement, .. }
        | DbTransactionStep::ExecuteChecked { statement, .. } => statement,
    }
}

fn postgres_placeholder_positions(sql: &str) -> Result<Vec<usize>, std::num::ParseIntError> {
    let bytes = sql.as_bytes();
    let mut positions = Vec::new();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] != b'$' {
            index += 1;
            continue;
        }
        index += 1;
        let start = index;
        while index < bytes.len() && bytes[index].is_ascii_digit() {
            index += 1;
        }
        if start < index {
            let position = sql[start..index].parse::<usize>()?;
            positions.push(position);
        }
    }
    Ok(positions)
}

#[test]
fn postgres_message_statements_use_ordered_parameters_and_atomic_sequence()
-> Result<(), Box<dyn std::error::Error>> {
    let write = write("[\"agent-1\"]");
    let mentions = vec!["agent-1".to_string()];
    let steps = message_write_steps(DbSqlFlavor::Postgres, &write, &mentions)?;

    assert_eq!(steps.len(), 12);
    for step in &steps {
        let statement = statement(step);
        assert!(!statement.sql().contains('?'));
        assert_eq!(
            postgres_placeholder_positions(statement.sql())?,
            (1..=statement.params().len()).collect::<Vec<_>>()
        );
    }
    assert!(
        statement(&steps[4])
            .sql()
            .contains("ON CONFLICT(env, session_id) DO NOTHING")
    );
    assert!(
        statement(&steps[5])
            .sql()
            .contains("current_msg_seq = current_msg_seq + 1")
    );
    assert!(
        statement(&steps[7])
            .params()
            .contains(&MESSAGE_EVENT_SEQUENCE_BASE.into())
    );
    assert!(
        statement(&steps[9])
            .sql()
            .starts_with("INSERT INTO workspace_message_delivery_outbox")
    );
    Ok(())
}

#[test]
fn empty_mentions_expect_zero_validation_rows() -> Result<(), Box<dyn std::error::Error>> {
    let write = write("[]");
    let steps = message_write_steps(DbSqlFlavor::Sqlite, &write, &[])?;

    let DbTransactionStep::QueryChecked {
        statement,
        expected_rows,
    } = &steps[3]
    else {
        panic!("mention validation must be a checked query");
    };
    assert_eq!(*expected_rows, DbCountExpectation::exactly(0));
    assert!(statement.sql().contains("WHERE 1 = 0"));
    Ok(())
}

#[test]
fn mention_queries_are_dialect_specific_and_parameterized() -> Result<(), Box<dyn std::error::Error>>
{
    let scope = WorkspaceMessageScope {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
    };
    let postgres = mention_messages(DbSqlFlavor::Postgres, &scope, "agent-1", 50);
    assert!(postgres.sql().contains("mentions_json @>"));
    assert!(!postgres.sql().contains('?'));
    assert_eq!(
        postgres_placeholder_positions(postgres.sql())?,
        (1..=postgres.params().len()).collect::<Vec<_>>()
    );

    let sqlite = mention_messages(DbSqlFlavor::Sqlite, &scope, "agent-1", 50);
    assert!(sqlite.sql().contains("json_each(m.mentions_json)"));
    assert!(!sqlite.sql().contains('$'));
    assert_eq!(sqlite.sql().matches('?').count(), sqlite.params().len());
    Ok(())
}

#[test]
fn duplicate_without_a_replayable_receipt_fails_closed() {
    let error = DbError::Backend("postgres [23505] unique violation".to_string());

    assert!(matches!(
        classify_write_error(error),
        WorkspaceMessageStoreError::DomainConflict
    ));
}

#[test]
fn message_rows_preserve_legacy_plain_text_content() -> Result<(), Box<dyn std::error::Error>> {
    let row = DbRow::new(std::collections::BTreeMap::from([
        ("message_id".to_string(), "message-legacy".into()),
        ("group_id".to_string(), "group-1".into()),
        ("workspace_id".to_string(), "workspace-1".into()),
        ("sender_id".to_string(), "user-1".into()),
        ("sender_type".to_string(), "human".into()),
        (
            "content".to_string(),
            "legacy BCS content was stored as plain text".into(),
        ),
        ("mentions_json".to_string(), "[]".into()),
        (
            "parent_message_id".to_string(),
            Option::<String>::None.into(),
        ),
        ("metadata_json".to_string(), "{}".into()),
        ("created_at".to_string(), 1_700_000_000_000_i64.into()),
    ]));

    let message = message_from_row(&row)?;

    assert_eq!(
        message.content,
        "legacy BCS content was stored as plain text"
    );
    Ok(())
}
