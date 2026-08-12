use bcs_config_api::mysql::{MysqlConnectionConfig, MysqlDbConfig};
use bcs_db_api::DbSqlFlavor;
use bcs_db_mysql::{MysqlDbManager, MysqlDbPlugin};
use bcs_test_support::db_plugin_contract_tests_with_flavor;

#[tokio::test]
#[ignore = "requires BCS_TEST_MYSQL_* connection settings"]
async fn mysql_db_plugin_passes_contract() {
    let database = std::env::var("BCS_TEST_MYSQL_DATABASE")
        .expect("BCS_TEST_MYSQL_DATABASE must be set for the MySQL contract");
    let user = std::env::var("BCS_TEST_MYSQL_USER")
        .expect("BCS_TEST_MYSQL_USER must be set for the MySQL contract");
    let password = std::env::var("BCS_TEST_MYSQL_PASSWORD").unwrap_or_default();
    let host = std::env::var("BCS_TEST_MYSQL_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let port = std::env::var("BCS_TEST_MYSQL_PORT")
        .ok()
        .and_then(|value| value.parse::<u16>().ok())
        .unwrap_or(3306);
    let config = MysqlDbConfig::new()
        .with_database(database)
        .with_connection(MysqlConnectionConfig {
            connection_type: "direct".to_string(),
            host: Some(host),
            port: Some(port),
            user: Some(user),
            password: Some(password),
            extra: Default::default(),
        });
    let datasource = config.datasource_name();
    let manager = MysqlDbManager::new(config)
        .await
        .expect("connect MySQL contract database");
    let plugin = MysqlDbPlugin::new(manager, datasource);
    db_plugin_contract_tests_with_flavor(&plugin, DbSqlFlavor::Mysql).await;
}
