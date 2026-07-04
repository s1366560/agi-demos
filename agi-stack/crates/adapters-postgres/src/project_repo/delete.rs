use sqlx::{Postgres, Row};

use agistack_core::ports::{CoreError, CoreResult};

#[derive(Debug)]
struct ForeignKeyRef {
    table_name: String,
    column_name: String,
}

pub(super) async fn delete_project_dependents(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    project_id: &str,
) -> CoreResult<()> {
    let conversation_ids =
        select_ids_by_eq(tx, "conversations", "id", "project_id", project_id).await?;
    let message_ids =
        select_ids_by_any(tx, "messages", "id", "conversation_id", &conversation_ids).await?;
    let workspace_ids = select_ids_by_eq(tx, "workspaces", "id", "project_id", project_id).await?;

    if table_exists(tx, "messages").await? {
        update_null_by_any(tx, "messages", "reply_to_id", &message_ids).await?;
        delete_rows_referencing(tx, "messages", "id", &message_ids, vec!["messages".into()])
            .await?;
        delete_by_any(tx, "messages", "conversation_id", &conversation_ids).await?;
    }

    if table_exists(tx, "conversations").await? {
        update_null_by_any(
            tx,
            "conversations",
            "parent_conversation_id",
            &conversation_ids,
        )
        .await?;
        update_null_by_any(tx, "conversations", "fork_source_id", &conversation_ids).await?;
        delete_rows_referencing(
            tx,
            "conversations",
            "id",
            &conversation_ids,
            vec!["conversations".into(), "messages".into()],
        )
        .await?;
        delete_by_eq(tx, "conversations", "project_id", project_id).await?;
    }

    delete_rows_referencing(
        tx,
        "workspaces",
        "id",
        &workspace_ids,
        vec!["workspaces".into(), "conversations".into()],
    )
    .await?;
    if table_exists(tx, "workspaces").await? {
        delete_by_eq(tx, "workspaces", "project_id", project_id).await?;
    }

    delete_rows_referencing(
        tx,
        "projects",
        "id",
        &[project_id.to_string()],
        vec![
            "projects".into(),
            "conversations".into(),
            "messages".into(),
            "workspaces".into(),
        ],
    )
    .await
}

async fn delete_rows_referencing(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    target_table: &str,
    target_column: &str,
    target_ids: &[String],
    skip_tables: Vec<String>,
) -> CoreResult<()> {
    if target_ids.is_empty() || !table_exists(tx, target_table).await? {
        return Ok(());
    }

    let mut references = foreign_key_references(tx, target_table, target_column).await?;
    if let Some(fallback_column) = fallback_reference_column(target_table) {
        for reference in tables_with_column(tx, fallback_column).await? {
            if reference.table_name == target_table {
                continue;
            }
            if !references.iter().any(|existing| {
                existing.table_name == reference.table_name
                    && existing.column_name == reference.column_name
            }) {
                references.push(reference);
            }
        }
    }

    for reference in references {
        if skip_tables
            .iter()
            .any(|skip| skip.as_str() == reference.table_name)
        {
            continue;
        }

        if table_has_column(tx, &reference.table_name, "id").await? {
            let source_ids = select_ids_by_any(
                tx,
                &reference.table_name,
                "id",
                &reference.column_name,
                target_ids,
            )
            .await?;
            if !source_ids.is_empty() {
                let mut nested_skip = skip_tables.clone();
                nested_skip.push(reference.table_name.clone());
                Box::pin(delete_rows_referencing(
                    tx,
                    &reference.table_name,
                    "id",
                    &source_ids,
                    nested_skip,
                ))
                .await?;
            }
        }

        delete_by_any(
            tx,
            &reference.table_name,
            &reference.column_name,
            target_ids,
        )
        .await?;
    }

    Ok(())
}

fn fallback_reference_column(target_table: &str) -> Option<&'static str> {
    match target_table {
        "projects" => Some("project_id"),
        "conversations" => Some("conversation_id"),
        "workspaces" => Some("workspace_id"),
        "messages" => Some("message_id"),
        _ => None,
    }
}

async fn foreign_key_references(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    target_table: &str,
    target_column: &str,
) -> CoreResult<Vec<ForeignKeyRef>> {
    let rows = sqlx::query(
        "SELECT source_table.relname AS table_name, source_attr.attname AS column_name \
         FROM pg_constraint c \
         JOIN pg_class source_table ON source_table.oid = c.conrelid \
         JOIN pg_namespace source_ns ON source_ns.oid = source_table.relnamespace \
         JOIN pg_class target_table ON target_table.oid = c.confrelid \
         JOIN pg_namespace target_ns ON target_ns.oid = target_table.relnamespace \
         JOIN unnest(c.conkey) WITH ORDINALITY AS source_key(attnum, ord) ON true \
         JOIN unnest(c.confkey) WITH ORDINALITY AS target_key(attnum, ord) \
              ON source_key.ord = target_key.ord \
         JOIN pg_attribute source_attr \
              ON source_attr.attrelid = source_table.oid AND source_attr.attnum = source_key.attnum \
         JOIN pg_attribute target_attr \
              ON target_attr.attrelid = target_table.oid AND target_attr.attnum = target_key.attnum \
         WHERE c.contype = 'f' \
           AND source_ns.nspname = ANY(current_schemas(false)) \
           AND target_ns.nspname = ANY(current_schemas(false)) \
           AND target_table.relname = $1 \
           AND target_attr.attname = $2 \
         ORDER BY source_table.relname, source_attr.attname",
    )
    .bind(target_table)
    .bind(target_column)
    .fetch_all(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;

    rows.into_iter()
        .map(|row| {
            Ok(ForeignKeyRef {
                table_name: row.try_get("table_name")?,
                column_name: row.try_get("column_name")?,
            })
        })
        .collect::<Result<Vec<_>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn tables_with_column(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    column: &str,
) -> CoreResult<Vec<ForeignKeyRef>> {
    let rows = sqlx::query(
        "SELECT c.table_name, c.column_name \
         FROM information_schema.columns c \
         JOIN information_schema.tables t \
           ON t.table_schema = c.table_schema AND t.table_name = c.table_name \
         WHERE c.table_schema = ANY(current_schemas(false)) \
           AND c.column_name = $1 \
           AND t.table_type = 'BASE TABLE' \
         ORDER BY c.table_name",
    )
    .bind(column)
    .fetch_all(&mut **tx)
    .await
    .map_err(|e| CoreError::Storage(e.to_string()))?;

    rows.into_iter()
        .map(|row| {
            Ok(ForeignKeyRef {
                table_name: row.try_get("table_name")?,
                column_name: row.try_get("column_name")?,
            })
        })
        .collect::<Result<Vec<_>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn table_exists(tx: &mut sqlx::Transaction<'_, Postgres>, table: &str) -> CoreResult<bool> {
    sqlx::query_as::<_, (bool,)>("SELECT to_regclass($1) IS NOT NULL")
        .bind(table)
        .fetch_one(&mut **tx)
        .await
        .map(|row| row.0)
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn table_has_column(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
) -> CoreResult<bool> {
    sqlx::query_as::<_, (bool,)>(
        "SELECT EXISTS ( \
             SELECT 1 FROM information_schema.columns \
             WHERE table_schema = ANY(current_schemas(false)) \
               AND table_name = $1 \
               AND column_name = $2 \
         )",
    )
    .bind(table)
    .bind(column)
    .fetch_one(&mut **tx)
    .await
    .map(|row| row.0)
    .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn select_ids_by_eq(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    id_column: &str,
    filter_column: &str,
    filter_value: &str,
) -> CoreResult<Vec<String>> {
    select_ids_by_any(
        tx,
        table,
        id_column,
        filter_column,
        &[filter_value.to_string()],
    )
    .await
}

async fn select_ids_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    id_column: &str,
    filter_column: &str,
    filter_values: &[String],
) -> CoreResult<Vec<String>> {
    if filter_values.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, id_column).await?
        || !table_has_column(tx, table, filter_column).await?
    {
        return Ok(Vec::new());
    }
    let sql = format!(
        "SELECT {}::text AS id FROM {} WHERE {} IS NOT NULL AND {}::text = ANY($1::text[])",
        quote_ident(id_column),
        quote_ident(table),
        quote_ident(id_column),
        quote_ident(filter_column)
    );
    let rows = sqlx::query(&sql)
        .bind(filter_values.to_vec())
        .fetch_all(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    rows.into_iter()
        .map(|row| row.try_get("id"))
        .collect::<Result<Vec<String>, sqlx::Error>>()
        .map_err(|e| CoreError::Storage(e.to_string()))
}

async fn update_null_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    ids: &[String],
) -> CoreResult<()> {
    if ids.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, column).await?
    {
        return Ok(());
    }
    let sql = format!(
        "UPDATE {} SET {} = NULL WHERE {}::text = ANY($1::text[])",
        quote_ident(table),
        quote_ident(column),
        quote_ident(column)
    );
    sqlx::query(&sql)
        .bind(ids.to_vec())
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    Ok(())
}

async fn delete_by_eq(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    value: &str,
) -> CoreResult<()> {
    delete_by_any(tx, table, column, &[value.to_string()]).await
}

async fn delete_by_any(
    tx: &mut sqlx::Transaction<'_, Postgres>,
    table: &str,
    column: &str,
    ids: &[String],
) -> CoreResult<()> {
    if ids.is_empty()
        || !table_exists(tx, table).await?
        || !table_has_column(tx, table, column).await?
    {
        return Ok(());
    }
    let sql = format!(
        "DELETE FROM {} WHERE {}::text = ANY($1::text[])",
        quote_ident(table),
        quote_ident(column)
    );
    sqlx::query(&sql)
        .bind(ids.to_vec())
        .execute(&mut **tx)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
    Ok(())
}

fn quote_ident(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}
