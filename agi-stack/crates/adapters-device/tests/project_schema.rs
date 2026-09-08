//! Real SQLite tests for portable schema storage, not API/sync acceptance.
#[path = "project_schema/commands.rs"]
mod commands;
#[path = "project_schema/concurrency.rs"]
mod concurrency;
#[path = "project_schema/guards.rs"]
mod guards;
#[path = "project_schema/migration.rs"]
mod migration;
#[path = "project_schema/support.rs"]
mod support;
