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
