//! Live-database integration tests for the production Postgres adapter.
//!
//! These are **gated on `DATABASE_URL`**: when it is unset (the default in CI and
//! most dev shells) every test short-circuits to a pass, so `cargo test
//! --workspace` never needs a database to be green. Point `DATABASE_URL` at a
//! Postgres with the `vector` extension available (e.g. the `pgvector/pgvector`
//! image) to exercise the real read/write path against a schema shaped like the
//! Python backend's.
//!
//! The tests create a **minimal subset** of the Python schema (`users`,
//! `tenants`, `projects`, `api_keys`, `memories`, `user_projects`) — only the
//! columns the Rust adapter touches, with the same names/types — then seed and
//! assert round-trips. This proves shared-DB compatibility without standing up
//! the full 110-table Python schema.

#[path = "pg_integration/admin_access.rs"]
mod admin_access;
#[path = "pg_integration/artifacts.rs"]
mod artifacts;
#[path = "pg_integration/attachments.rs"]
mod attachments;
#[path = "pg_integration/audit.rs"]
mod audit;
#[path = "pg_integration/backend_stores.rs"]
mod backend_stores;
#[path = "pg_integration/billing.rs"]
mod billing;
#[path = "pg_integration/channel.rs"]
mod channel;
#[path = "pg_integration/conversation_events.rs"]
mod conversation_events;
#[path = "pg_integration/cron.rs"]
mod cron;
#[path = "pg_integration/cron_control.rs"]
mod cron_control;
#[path = "pg_integration/cron_operations.rs"]
mod cron_operations;
#[path = "pg_integration/cron_runtime.rs"]
mod cron_runtime;
#[path = "pg_integration/cron_schedule.rs"]
mod cron_schedule;
#[path = "pg_integration/cron_scheduler_owner.rs"]
mod cron_scheduler_owner;
#[path = "pg_integration/data_stats.rs"]
mod data_stats;
#[path = "pg_integration/deploy.rs"]
mod deploy;
#[path = "pg_integration/event_logs.rs"]
mod event_logs;
#[path = "pg_integration/genes.rs"]
mod genes;
#[path = "pg_integration/hitl.rs"]
mod hitl;
#[path = "pg_integration/identity.rs"]
mod identity;
#[path = "pg_integration/instances.rs"]
mod instances;
#[path = "pg_integration/llm_providers.rs"]
mod llm_providers;
#[path = "pg_integration/memory.rs"]
mod memory;
#[path = "pg_integration/notifications.rs"]
mod notifications;
#[path = "pg_integration/project_reads.rs"]
mod project_reads;
#[path = "pg_integration/project_store.rs"]
mod project_store;
#[path = "pg_integration/schema.rs"]
mod schema;
#[path = "pg_integration/shares.rs"]
mod shares;
#[path = "pg_integration/skill.rs"]
mod skill;
#[path = "pg_integration/stores.rs"]
mod stores;
#[path = "pg_integration/subagent_templates.rs"]
mod subagent_templates;
#[path = "pg_integration/support.rs"]
mod support;
#[path = "pg_integration/support_tickets.rs"]
mod support_tickets;
#[path = "pg_integration/tenant_trust.rs"]
mod tenant_trust;
#[path = "pg_integration/tenant_webhooks.rs"]
mod tenant_webhooks;
#[path = "pg_integration/workspace.rs"]
mod workspace;
