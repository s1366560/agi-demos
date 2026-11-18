use std::error::Error;

use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_postgres::PostgresDbPlugin;
use bcs_test_support::db_plugin_contract_tests_with_flavor;

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL"]
async fn postgres_db_plugin_passes_contract() -> Result<(), Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    let plugin = PostgresDbPlugin::connect(&database_url, 4).await?;
    db_plugin_contract_tests_with_flavor(&plugin, DbSqlFlavor::Postgres).await;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL"]
async fn postgres_calendar_parameters_keep_precision_and_timezone() -> Result<(), Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    let plugin = PostgresDbPlugin::connect(&database_url, 1).await?;
    let rows = plugin.query(DbStatement::with_params(
        "SELECT $1::date AS day, $2::time AS clock, $3::timestamp AS local_ts, $4::timestamptz AS instant",
        vec!["2024-02-29".into(), "00:01:02.010".into(),
             "2024-02-29 01:02:03".into(), "2024-03-01T06:02:03.000004+08:00".into()],
    )).await?;
    let row = rows.first().ok_or("missing timestamp row")?;
    for (column, expected) in [
        ("day", "2024-02-29"),
        ("clock", "00:01:02.010"),
        ("local_ts", "2024-02-29 01:02:03"),
        ("instant", "2024-02-29T22:02:03.000004Z"),
    ] {
        assert_eq!(row.get_string(column)?.as_deref(), Some(expected));
    }
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL"]
async fn postgres_timestamptz_uses_legacy_json_timestamp_format() -> Result<(), Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    let plugin = PostgresDbPlugin::connect(&database_url, 1).await?;

    let rows = plugin
        .query(DbStatement::new(
            "SELECT TIMESTAMPTZ '2026-08-11 01:02:03.456789+00' AS observed_at",
        ))
        .await?;

    assert_eq!(
        rows.first()
            .ok_or("missing timestamp row")?
            .get_string("observed_at")?
            .as_deref(),
        Some("2026-08-11T01:02:03.456789Z")
    );
    Ok(())
}
