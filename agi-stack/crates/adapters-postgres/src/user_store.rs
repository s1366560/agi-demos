//! Read + minimal-write store over the **Python-owned** `users` and `api_keys`
//! tables — the data source for the **P2 login vertical** (plan.md Section 15.2).
//!
//! The Python `/auth/token` handler (`routers/auth.py::login_for_access_token`)
//! does three things this store backs:
//!   1. look up the user by email for a bcrypt password check
//!      ([`PgUserStore::find_auth_by_email`]);
//!   2. mint a short-lived `ms_sk_` API key and persist its SHA-256
//!      ([`PgUserStore::insert_api_key`]) — the one write the returned token needs
//!      to actually work;
//!   3. (first-login-only) ensure a default project. That side-effect is a
//!      documented P2 follow-up (see `10-production-migration.md`): it is not
//!      reflected in the login *response* bytes, and the seeded/existing users the
//!      cutover serves already have projects, so skipping it keeps the flip safe
//!      while avoiding the `projects` table's client-side-default landmine.
//!
//! The `api_keys` insert supplies every column explicitly except `created_at`
//! (which has a real `server_default now()`), so it does not rely on any
//! SQLAlchemy client-side default. Writes are exercised only under the live
//! integration test; offline the login path uses the dev identity stub.

use serde_json::Value;
use sqlx::{
    types::chrono::{DateTime, Utc},
    Postgres, Transaction,
};

use agistack_core::ports::{CoreError, CoreResult};

use crate::PgPool;

/// The subset of the Python `users` row the login path needs.
#[derive(Debug, Clone)]
pub struct UserAuthRecord {
    pub id: String,
    pub email: String,
    pub full_name: Option<String>,
    /// bcrypt `$2b$` hash — verified with `agistack-adapters-secrets`.
    pub hashed_password: String,
    pub is_active: bool,
    pub is_superuser: bool,
    pub must_change_password: bool,
}

/// The Python `User` response projection used by `GET /auth/me` and
/// `GET /users/me`.
#[derive(Debug, Clone)]
pub struct CurrentUserRecord {
    pub id: String,
    pub email: String,
    pub full_name: Option<String>,
    pub roles: Vec<String>,
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
    pub profile: Value,
    pub preferred_language: Option<String>,
}

/// Read/mint store over the Python `users` + `api_keys` tables.
pub struct PgUserStore {
    pool: PgPool,
}

/// A transaction-scoped, cross-process lock for one device-code grant.
///
/// PostgreSQL releases `pg_advisory_xact_lock` automatically on commit or
/// rollback, including when this value is dropped after an error. Keeping the
/// API-key mutation in the same transaction makes approval rollback atomic.
pub struct PgDeviceGrantTransition {
    transaction: Transaction<'static, Postgres>,
}

impl PgUserStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Serialize approve, poll, and cancel for one device code across Rust
    /// server processes. The two-argument advisory key gives this lock its own
    /// namespace so it cannot collide with unrelated advisory-lock users.
    pub async fn begin_device_grant_transition(
        &self,
        device_code: &str,
    ) -> CoreResult<PgDeviceGrantTransition> {
        let mut transaction = self
            .pool
            .begin()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        sqlx::query("SELECT pg_advisory_xact_lock(1296388939, hashtext($1))")
            .bind(device_code)
            .execute(&mut *transaction)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(PgDeviceGrantTransition { transaction })
    }

    /// Look up a user by email (the OAuth2 form `username`) for password
    /// verification. Returns `None` when no such user exists — the caller maps
    /// that to the same 401 as a bad password (Python parity: identical
    /// "Incorrect username or password" for both).
    pub async fn find_auth_by_email(&self, email: &str) -> CoreResult<Option<UserAuthRecord>> {
        let row = sqlx::query_as::<_, (String, String, Option<String>, String, bool, bool, bool)>(
            "SELECT id, email, full_name, hashed_password, is_active, is_superuser, \
             must_change_password FROM users WHERE email = $1",
        )
        .bind(email)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(row.map(
            |(
                id,
                email,
                full_name,
                hashed_password,
                is_active,
                is_superuser,
                must_change_password,
            )| {
                UserAuthRecord {
                    id,
                    email,
                    full_name,
                    hashed_password,
                    is_active,
                    is_superuser,
                    must_change_password,
                }
            },
        ))
    }

    /// Look up the same auth row by user id. Device-code approval is already
    /// authenticated by an API key and only needs the user's active/superuser
    /// flags to mint the CLI key with Python-compatible permissions.
    pub async fn find_auth_by_id(&self, user_id: &str) -> CoreResult<Option<UserAuthRecord>> {
        let row = sqlx::query_as::<_, (String, String, Option<String>, String, bool, bool, bool)>(
            "SELECT id, email, full_name, hashed_password, is_active, is_superuser, \
             must_change_password FROM users WHERE id = $1",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(row.map(
            |(
                id,
                email,
                full_name,
                hashed_password,
                is_active,
                is_superuser,
                must_change_password,
            )| {
                UserAuthRecord {
                    id,
                    email,
                    full_name,
                    hashed_password,
                    is_active,
                    is_superuser,
                    must_change_password,
                }
            },
        ))
    }

    /// Fetch the current-user response projection. Roles are sorted in SQL to
    /// keep response bytes deterministic across Postgres plans.
    pub async fn find_current_user_by_id(
        &self,
        user_id: &str,
    ) -> CoreResult<Option<CurrentUserRecord>> {
        type Row = (
            String,
            String,
            Option<String>,
            bool,
            DateTime<Utc>,
            Value,
            Option<String>,
            Vec<String>,
        );

        let row = sqlx::query_as::<_, Row>(
            "SELECT u.id, u.email, u.full_name, u.is_active, u.created_at, u.profile, \
             u.preferred_language, \
             COALESCE(array_agg(r.name ORDER BY r.name) \
                FILTER (WHERE r.name IS NOT NULL), ARRAY[]::text[]) AS roles \
             FROM users u \
             LEFT JOIN user_roles ur ON ur.user_id = u.id \
             LEFT JOIN roles r ON r.id = ur.role_id \
             WHERE u.id = $1 \
             GROUP BY u.id",
        )
        .bind(user_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;

        Ok(row.map(
            |(id, email, full_name, is_active, created_at, profile, preferred_language, roles)| {
                CurrentUserRecord {
                    id,
                    email,
                    full_name,
                    roles,
                    is_active,
                    created_at,
                    profile,
                    preferred_language,
                }
            },
        ))
    }

    /// Persist a freshly-minted API key, mirroring
    /// `AuthService.create_api_key` -> `api_keys` insert. The **plaintext** key is
    /// hashed here with the same [`crate::sha256_hex`] the authenticator uses on
    /// lookup, so the stored `key_hash` is guaranteed to match on the next
    /// request (single source of truth for the digest). `permissions` is written
    /// as a JSON array via an explicit `::json` cast so it is independent of the
    /// `json` vs `jsonb` column choice.
    #[allow(clippy::too_many_arguments)]
    pub async fn insert_api_key(
        &self,
        id: &str,
        plain_key: &str,
        name: &str,
        user_id: &str,
        expires_at: Option<DateTime<Utc>>,
        permissions: &[String],
    ) -> CoreResult<()> {
        let key_hash = crate::sha256_hex(plain_key);
        let permissions_json =
            serde_json::to_string(permissions).map_err(|e| CoreError::Storage(e.to_string()))?;
        sqlx::query(
            "INSERT INTO api_keys (id, key_hash, name, user_id, expires_at, is_active, permissions) \
             VALUES ($1, $2, $3, $4, $5, true, $6::json)",
        )
        .bind(id)
        .bind(&key_hash)
        .bind(name)
        .bind(user_id)
        .bind(expires_at)
        .bind(&permissions_json)
        .execute(&self.pool)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }

    /// Compensating revocation for a device approval that could not publish its
    /// grant. The raw token is hashed before lookup and is never persisted.
    pub async fn revoke_api_key_by_raw(&self, raw_key: &str) -> CoreResult<bool> {
        let key_hash = crate::sha256_hex(raw_key);
        let result = sqlx::query("DELETE FROM api_keys WHERE key_hash = $1")
            .bind(&key_hash)
            .execute(&self.pool)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }
}

impl PgDeviceGrantTransition {
    /// Persist a newly minted device-login key inside the lock transaction.
    #[allow(clippy::too_many_arguments)]
    pub async fn insert_api_key(
        &mut self,
        id: &str,
        plain_key: &str,
        name: &str,
        user_id: &str,
        expires_at: Option<DateTime<Utc>>,
        permissions: &[String],
    ) -> CoreResult<()> {
        let key_hash = crate::sha256_hex(plain_key);
        let permissions_json =
            serde_json::to_string(permissions).map_err(|e| CoreError::Storage(e.to_string()))?;
        sqlx::query(
            "INSERT INTO api_keys (id, key_hash, name, user_id, expires_at, is_active, permissions) \
             VALUES ($1, $2, $3, $4, $5, true, $6::json)",
        )
        .bind(id)
        .bind(&key_hash)
        .bind(name)
        .bind(user_id)
        .bind(expires_at)
        .bind(&permissions_json)
        .execute(&mut *self.transaction)
        .await
        .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(())
    }

    /// Revoke exactly the server-stored grant token. Missing/already-revoked
    /// keys are a successful no-op, which keeps cancellation idempotent.
    pub async fn revoke_api_key_by_raw(&mut self, raw_key: &str) -> CoreResult<bool> {
        let key_hash = crate::sha256_hex(raw_key);
        let result = sqlx::query("DELETE FROM api_keys WHERE key_hash = $1")
            .bind(&key_hash)
            .execute(&mut *self.transaction)
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))?;
        Ok(result.rows_affected() > 0)
    }

    pub async fn commit(self) -> CoreResult<()> {
        self.transaction
            .commit()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))
    }

    pub async fn rollback(self) -> CoreResult<()> {
        self.transaction
            .rollback()
            .await
            .map_err(|e| CoreError::Storage(e.to_string()))
    }
}
