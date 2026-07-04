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

#[path = "pg_integration/hitl.rs"]
mod hitl;
#[path = "pg_integration/identity.rs"]
mod identity;
#[path = "pg_integration/memory.rs"]
mod memory;
#[path = "pg_integration/project_reads.rs"]
mod project_reads;
#[path = "pg_integration/project_store.rs"]
mod project_store;
#[path = "pg_integration/shares.rs"]
mod shares;
#[path = "pg_integration/skill.rs"]
mod skill;
#[path = "pg_integration/stores.rs"]
mod stores;
#[path = "pg_integration/support.rs"]
mod support;
#[path = "pg_integration/tenant_trust.rs"]
mod tenant_trust;
#[path = "pg_integration/workspace.rs"]
mod workspace;
