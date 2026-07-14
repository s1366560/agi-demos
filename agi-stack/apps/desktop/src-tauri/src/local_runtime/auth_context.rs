use std::fmt;

use chrono::Utc;
use rusqlite::{params, Connection, OptionalExtension, Transaction};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::session_store::DesktopSessionStore;

const LOCAL_USER_ID: &str = "local-user";
const DEFAULT_TENANT_ID: &str = "local";
const DEFAULT_PROJECT_ID: &str = "local-project";
const LOCAL_SESSION_TTL_MS: i64 = 12 * 60 * 60 * 1_000;
const TRUSTED_LOCAL_SESSION_TTL_MS: i64 = 30 * 24 * 60 * 60 * 1_000;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct DesktopUser {
    pub(super) user_id: String,
    pub(super) email: String,
    pub(super) name: String,
    pub(super) roles: Vec<String>,
    pub(super) is_active: bool,
    pub(super) created_at: String,
    pub(super) profile: Value,
    pub(super) preferred_language: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct DesktopTenant {
    pub(super) id: String,
    pub(super) name: String,
    pub(super) slug: String,
    pub(super) plan: String,
    pub(super) role: String,
    pub(super) created_at: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub(super) struct DesktopProject {
    pub(super) id: String,
    pub(super) tenant_id: String,
    pub(super) name: String,
    pub(super) description: Option<String>,
    pub(super) agent_conversation_mode: String,
    pub(super) created_at: String,
    pub(super) stats: Value,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct DesktopWorkspaceContext {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) revision: u64,
    pub(super) updated_at: String,
}

#[derive(Clone, Debug)]
pub(super) struct AuthenticatedContext {
    pub(super) session_id: String,
    pub(super) user: DesktopUser,
    pub(super) workspace: DesktopWorkspaceContext,
    pub(super) membership_role: String,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct DesktopSessionDescriptor {
    pub(super) session_id: String,
    pub(super) auth_method: String,
    pub(super) expires_at: String,
    pub(super) trusted_device: bool,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct LocalSessionOutcome {
    pub(super) access_token: String,
    pub(super) token_type: String,
    pub(super) must_change_password: bool,
    pub(super) session: DesktopSessionDescriptor,
    pub(super) context: DesktopWorkspaceContext,
}

#[derive(Clone, Debug, Deserialize)]
pub(super) struct LocalSessionRequest {
    #[serde(default = "default_trusted_device")]
    pub(super) trusted_device: bool,
}

#[derive(Clone, Debug, Deserialize)]
pub(super) struct TrustedSessionResumeRequest {
    pub(super) session_id: String,
}

#[derive(Clone, Debug, Deserialize)]
pub(super) struct ContextSwitchRequest {
    pub(super) tenant_id: String,
    pub(super) project_id: String,
    pub(super) expected_revision: u64,
    pub(super) idempotency_key: String,
}

#[derive(Clone, Debug, Serialize)]
pub(super) struct ContextSwitchOutcome {
    pub(super) context: DesktopWorkspaceContext,
    pub(super) changed: bool,
}

#[derive(Debug)]
pub(super) enum AuthContextError {
    MembershipRequired,
    ProjectUnavailable,
    RevisionConflict { expected: u64, actual: u64 },
    IdempotencyConflict,
    Storage(String),
}

impl fmt::Display for AuthContextError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MembershipRequired => formatter.write_str("active tenant membership required"),
            Self::ProjectUnavailable => {
                formatter.write_str("project is not available in the selected tenant")
            }
            Self::RevisionConflict { expected, actual } => write!(
                formatter,
                "workspace context revision conflict: expected {expected}, found {actual}"
            ),
            Self::IdempotencyConflict => {
                formatter.write_str("workspace context idempotency key is already in use")
            }
            Self::Storage(error) => formatter.write_str(error),
        }
    }
}

fn default_trusted_device() -> bool {
    false
}

pub(super) fn initialize_auth_context_schema(connection: &Connection) -> Result<(), String> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS desktop_users (
               id TEXT PRIMARY KEY,
               email TEXT NOT NULL UNIQUE,
               display_name TEXT NOT NULL,
               auth_method TEXT NOT NULL,
               status TEXT NOT NULL CHECK(status IN ('active', 'disabled')),
               created_at_ms INTEGER NOT NULL,
               updated_at_ms INTEGER NOT NULL
             );
             CREATE TABLE IF NOT EXISTS desktop_tenants (
               id TEXT PRIMARY KEY,
               name TEXT NOT NULL,
               slug TEXT NOT NULL UNIQUE,
               plan TEXT NOT NULL,
               status TEXT NOT NULL CHECK(status IN ('active', 'archived')),
               created_at_ms INTEGER NOT NULL,
               updated_at_ms INTEGER NOT NULL
             );
             CREATE TABLE IF NOT EXISTS desktop_projects (
               id TEXT PRIMARY KEY,
               tenant_id TEXT NOT NULL,
               name TEXT NOT NULL,
               description TEXT,
               status TEXT NOT NULL CHECK(status IN ('active', 'archived')),
               created_at_ms INTEGER NOT NULL,
               updated_at_ms INTEGER NOT NULL,
               FOREIGN KEY(tenant_id) REFERENCES desktop_tenants(id),
               UNIQUE(tenant_id, id)
             );
             CREATE TABLE IF NOT EXISTS desktop_tenant_memberships (
               user_id TEXT NOT NULL,
               tenant_id TEXT NOT NULL,
               role TEXT NOT NULL,
               status TEXT NOT NULL CHECK(status IN ('active', 'suspended')),
               created_at_ms INTEGER NOT NULL,
               PRIMARY KEY(user_id, tenant_id),
               FOREIGN KEY(user_id) REFERENCES desktop_users(id),
               FOREIGN KEY(tenant_id) REFERENCES desktop_tenants(id)
             );
             CREATE TABLE IF NOT EXISTS desktop_user_sessions (
               id TEXT PRIMARY KEY,
               user_id TEXT NOT NULL,
               token_digest TEXT NOT NULL UNIQUE,
               status TEXT NOT NULL CHECK(status IN ('active', 'revoked', 'expired')),
               trusted_device INTEGER NOT NULL CHECK(trusted_device IN (0, 1)),
               expires_at_ms INTEGER NOT NULL,
               created_at_ms INTEGER NOT NULL,
               last_seen_at_ms INTEGER NOT NULL,
               revoked_at_ms INTEGER,
               FOREIGN KEY(user_id) REFERENCES desktop_users(id)
             );
             CREATE TABLE IF NOT EXISTS desktop_workspace_contexts (
               user_id TEXT PRIMARY KEY,
               tenant_id TEXT NOT NULL,
               project_id TEXT NOT NULL,
               revision INTEGER NOT NULL CHECK(revision >= 0),
               updated_at_ms INTEGER NOT NULL,
               FOREIGN KEY(user_id) REFERENCES desktop_users(id),
               FOREIGN KEY(tenant_id) REFERENCES desktop_tenants(id),
               FOREIGN KEY(tenant_id, project_id) REFERENCES desktop_projects(tenant_id, id)
             );
             CREATE TABLE IF NOT EXISTS desktop_workspace_context_events (
               id TEXT PRIMARY KEY,
               user_id TEXT NOT NULL,
               session_id TEXT NOT NULL,
               from_tenant_id TEXT,
               from_project_id TEXT,
               to_tenant_id TEXT NOT NULL,
               to_project_id TEXT NOT NULL,
               revision INTEGER NOT NULL,
               idempotency_key TEXT NOT NULL,
               created_at_ms INTEGER NOT NULL,
               value_json TEXT NOT NULL,
               UNIQUE(user_id, revision),
               UNIQUE(user_id, idempotency_key),
               FOREIGN KEY(user_id) REFERENCES desktop_users(id),
               FOREIGN KEY(session_id) REFERENCES desktop_user_sessions(id)
             );
             CREATE INDEX IF NOT EXISTS idx_desktop_projects_tenant
               ON desktop_projects(tenant_id, name);
             CREATE INDEX IF NOT EXISTS idx_desktop_sessions_digest
               ON desktop_user_sessions(token_digest, status, expires_at_ms);
             CREATE INDEX IF NOT EXISTS idx_desktop_context_events_user
               ON desktop_workspace_context_events(user_id, revision DESC);",
        )
        .map_err(|error| error.to_string())?;
    seed_auth_catalog(connection)
}

fn seed_auth_catalog(connection: &Connection) -> Result<(), String> {
    let now_ms = Utc::now().timestamp_millis();
    connection
        .execute(
            "INSERT OR IGNORE INTO desktop_users(
               id, email, display_name, auth_method, status, created_at_ms, updated_at_ms
             ) VALUES (?1, ?2, ?3, 'local', 'active', ?4, ?4)",
            params![LOCAL_USER_ID, "local@desktop", "Local Desktop", now_ms],
        )
        .map_err(|error| error.to_string())?;

    let tenants = [
        ("local", "Local Desktop", "local", "Local"),
        ("northstar", "Northstar Labs", "northstar", "Enterprise"),
        ("orbital", "Orbital Research", "orbital", "Team"),
        ("personal", "Local Sandbox", "personal", "Personal"),
    ];
    for (id, name, slug, plan) in tenants {
        connection
            .execute(
                "INSERT OR IGNORE INTO desktop_tenants(
                   id, name, slug, plan, status, created_at_ms, updated_at_ms
                 ) VALUES (?1, ?2, ?3, ?4, 'active', ?5, ?5)",
                params![id, name, slug, plan, now_ms],
            )
            .map_err(|error| error.to_string())?;
        connection
            .execute(
                "INSERT OR IGNORE INTO desktop_tenant_memberships(
                   user_id, tenant_id, role, status, created_at_ms
                 ) VALUES (?1, ?2, ?3, 'active', ?4)",
                params![
                    LOCAL_USER_ID,
                    id,
                    if id == "orbital" { "member" } else { "owner" },
                    now_ms
                ],
            )
            .map_err(|error| error.to_string())?;
    }

    let projects = [
        (
            "local-project",
            "local",
            "Local project",
            "Desktop local runtime project",
        ),
        (
            "product-strategy",
            "northstar",
            "Product Strategy",
            "Research, planning, and leadership artifacts",
        ),
        (
            "desktop-client",
            "northstar",
            "Desktop Client",
            "Application UX, frontend, and Rust runtime",
        ),
        (
            "customer-insights",
            "northstar",
            "Customer Insights",
            "Interviews, feedback, and opportunity signals",
        ),
        (
            "agent-evals",
            "orbital",
            "Agent Evaluations",
            "Benchmark suites and quality reviews",
        ),
        (
            "open-models",
            "orbital",
            "Open Models",
            "Model experiments and inference reports",
        ),
        (
            "prototypes",
            "personal",
            "Prototypes",
            "Private experiments and scratch work",
        ),
    ];
    for (id, tenant_id, name, description) in projects {
        connection
            .execute(
                "INSERT OR IGNORE INTO desktop_projects(
                   id, tenant_id, name, description, status, created_at_ms, updated_at_ms
                 ) VALUES (?1, ?2, ?3, ?4, 'active', ?5, ?5)",
                params![id, tenant_id, name, description, now_ms],
            )
            .map_err(|error| error.to_string())?;
    }

    connection
        .execute(
            "INSERT OR IGNORE INTO desktop_workspace_contexts(
               user_id, tenant_id, project_id, revision, updated_at_ms
             ) VALUES (?1, ?2, ?3, 0, ?4)",
            params![LOCAL_USER_ID, DEFAULT_TENANT_ID, DEFAULT_PROJECT_ID, now_ms],
        )
        .map_err(|error| error.to_string())?;
    Ok(())
}

impl DesktopSessionStore {
    pub(super) fn create_local_session(
        &self,
        credential: String,
        trusted_device: bool,
        now_ms: i64,
    ) -> Result<LocalSessionOutcome, AuthContextError> {
        let session_id = format!("local-session-{}", Uuid::new_v4());
        let expires_at_ms = now_ms.saturating_add(if trusted_device {
            TRUSTED_LOCAL_SESSION_TTL_MS
        } else {
            LOCAL_SESSION_TTL_MS
        });
        let digest = credential_digest(&credential);
        let connection = self.connection().map_err(AuthContextError::Storage)?;
        connection
            .execute(
                "INSERT INTO desktop_user_sessions(
                   id, user_id, token_digest, status, trusted_device, expires_at_ms,
                   created_at_ms, last_seen_at_ms
                 ) VALUES (?1, ?2, ?3, 'active', ?4, ?5, ?6, ?6)",
                params![
                    session_id,
                    LOCAL_USER_ID,
                    digest,
                    i64::from(trusted_device),
                    expires_at_ms,
                    now_ms
                ],
            )
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        let context = query_workspace_context(&connection, LOCAL_USER_ID)?;
        Ok(LocalSessionOutcome {
            access_token: credential,
            token_type: "bearer".to_string(),
            must_change_password: false,
            session: DesktopSessionDescriptor {
                session_id,
                auth_method: "local".to_string(),
                expires_at: iso_from_millis(expires_at_ms),
                trusted_device,
            },
            context,
        })
    }

    pub(super) fn resume_trusted_local_session(
        &self,
        session_id: &str,
        credential: String,
        now_ms: i64,
    ) -> Result<Option<LocalSessionOutcome>, AuthContextError> {
        let digest = credential_digest(&credential);
        let mut connection = self.connection().map_err(AuthContextError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        let session = transaction
            .query_row(
                "SELECT s.id, s.user_id, s.expires_at_ms
                 FROM desktop_user_sessions s
                 JOIN desktop_users u ON u.id = s.user_id
                 JOIN desktop_workspace_contexts c ON c.user_id = s.user_id
                 JOIN desktop_tenant_memberships m
                   ON m.user_id = s.user_id AND m.tenant_id = c.tenant_id
                 JOIN desktop_tenants t ON t.id = c.tenant_id
                 JOIN desktop_projects p
                   ON p.id = c.project_id AND p.tenant_id = c.tenant_id
                 WHERE s.id = ?1 AND s.status = 'active' AND s.trusted_device = 1
                   AND s.expires_at_ms > ?2 AND u.status = 'active'
                   AND m.status = 'active' AND t.status = 'active' AND p.status = 'active'",
                params![session_id, now_ms],
                |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, i64>(2)?,
                    ))
                },
            )
            .optional()
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        let Some((session_id, user_id, expires_at_ms)) = session else {
            transaction
                .commit()
                .map_err(|error| AuthContextError::Storage(error.to_string()))?;
            return Ok(None);
        };

        let context = query_workspace_context(&transaction, &user_id)?;
        transaction
            .execute(
                "UPDATE desktop_user_sessions
                 SET token_digest = ?1, last_seen_at_ms = ?2
                 WHERE id = ?3 AND status = 'active' AND trusted_device = 1",
                params![digest, now_ms, session_id],
            )
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;

        Ok(Some(LocalSessionOutcome {
            access_token: credential,
            token_type: "bearer".to_string(),
            must_change_password: false,
            session: DesktopSessionDescriptor {
                session_id,
                auth_method: "local".to_string(),
                expires_at: iso_from_millis(expires_at_ms),
                trusted_device: true,
            },
            context,
        }))
    }

    pub(super) fn validate_session_credential(
        &self,
        credential: &str,
        now_ms: i64,
    ) -> Result<Option<AuthenticatedContext>, String> {
        if credential.trim().is_empty() {
            return Ok(None);
        }
        let connection = self.connection()?;
        let digest = credential_digest(credential);
        let session = connection
            .query_row(
                "SELECT id, user_id FROM desktop_user_sessions
                 WHERE token_digest = ?1 AND status = 'active' AND expires_at_ms > ?2",
                params![digest, now_ms],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        let Some((session_id, user_id)) = session else {
            return Ok(None);
        };
        let workspace =
            query_workspace_context(&connection, &user_id).map_err(|error| error.to_string())?;
        let membership_role = connection
            .query_row(
                "SELECT role FROM desktop_tenant_memberships
                 WHERE user_id = ?1 AND tenant_id = ?2 AND status = 'active'",
                params![user_id, workspace.tenant_id],
                |row| row.get::<_, String>(0),
            )
            .optional()
            .map_err(|error| error.to_string())?;
        let Some(membership_role) = membership_role else {
            return Ok(None);
        };
        let user = query_user(&connection, &user_id, &membership_role)?;
        connection
            .execute(
                "UPDATE desktop_user_sessions SET last_seen_at_ms = ?1 WHERE id = ?2",
                params![now_ms, session_id],
            )
            .map_err(|error| error.to_string())?;
        Ok(Some(AuthenticatedContext {
            session_id,
            user,
            workspace,
            membership_role,
        }))
    }

    pub(super) fn revoke_session(&self, session_id: &str, now_ms: i64) -> Result<(), String> {
        let changed = self
            .connection()?
            .execute(
                "UPDATE desktop_user_sessions
                 SET status = 'revoked', revoked_at_ms = ?1
                 WHERE id = ?2 AND status = 'active'",
                params![now_ms, session_id],
            )
            .map_err(|error| error.to_string())?;
        if changed == 0 {
            return Err("active authenticated session not found".to_string());
        }
        Ok(())
    }

    pub(super) fn session_context_is_current(
        &self,
        authenticated: &AuthenticatedContext,
        now_ms: i64,
    ) -> Result<bool, String> {
        let connection = self.connection()?;
        let session_active = connection
            .query_row(
                "SELECT 1 FROM desktop_user_sessions
                 WHERE id = ?1 AND user_id = ?2 AND status = 'active' AND expires_at_ms > ?3",
                params![authenticated.session_id, authenticated.user.user_id, now_ms],
                |_| Ok(()),
            )
            .optional()
            .map_err(|error| error.to_string())?
            .is_some();
        if !session_active {
            return Ok(false);
        }
        let current = query_workspace_context(&connection, &authenticated.user.user_id)
            .map_err(|error| error.to_string())?;
        Ok(current == authenticated.workspace)
    }

    pub(super) fn list_user_tenants(&self, user_id: &str) -> Result<Vec<DesktopTenant>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT t.id, t.name, t.slug, t.plan, m.role, t.created_at_ms
                 FROM desktop_tenants t
                 JOIN desktop_tenant_memberships m ON m.tenant_id = t.id
                 WHERE m.user_id = ?1 AND m.status = 'active' AND t.status = 'active'
                 ORDER BY CASE t.id WHEN 'local' THEN 0 ELSE 1 END, t.name",
            )
            .map_err(|error| error.to_string())?;
        let rows = statement
            .query_map([user_id], |row| {
                Ok(DesktopTenant {
                    id: row.get(0)?,
                    name: row.get(1)?,
                    slug: row.get(2)?,
                    plan: row.get(3)?,
                    role: row.get(4)?,
                    created_at: iso_from_millis(row.get(5)?),
                })
            })
            .map_err(|error| error.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| error.to_string())
    }

    pub(super) fn list_user_projects(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<Vec<DesktopProject>, AuthContextError> {
        let connection = self.connection().map_err(AuthContextError::Storage)?;
        require_membership(&connection, user_id, tenant_id)?;
        let mut statement = connection
            .prepare(
                "SELECT id, tenant_id, name, description, created_at_ms
                 FROM desktop_projects
                 WHERE tenant_id = ?1 AND status = 'active' ORDER BY name",
            )
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        let rows = statement
            .query_map([tenant_id], |row| {
                Ok(DesktopProject {
                    id: row.get(0)?,
                    tenant_id: row.get(1)?,
                    name: row.get(2)?,
                    description: row.get(3)?,
                    agent_conversation_mode: "workspace".to_string(),
                    created_at: iso_from_millis(row.get(4)?),
                    stats: json!({}),
                })
            })
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|error| AuthContextError::Storage(error.to_string()))
    }

    #[cfg(test)]
    pub(super) fn workspace_context(
        &self,
        user_id: &str,
    ) -> Result<DesktopWorkspaceContext, String> {
        let connection = self.connection()?;
        query_workspace_context(&connection, user_id).map_err(|error| error.to_string())
    }

    pub(super) fn switch_workspace_context(
        &self,
        authenticated: &AuthenticatedContext,
        request: &ContextSwitchRequest,
        now_ms: i64,
    ) -> Result<ContextSwitchOutcome, AuthContextError> {
        let mut connection = self.connection().map_err(AuthContextError::Storage)?;
        let transaction = connection
            .transaction()
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;

        if let Some(existing) = query_context_event(
            &transaction,
            &authenticated.user.user_id,
            &request.idempotency_key,
        )? {
            if existing.tenant_id != request.tenant_id || existing.project_id != request.project_id
            {
                return Err(AuthContextError::IdempotencyConflict);
            }
            transaction
                .commit()
                .map_err(|error| AuthContextError::Storage(error.to_string()))?;
            return Ok(ContextSwitchOutcome {
                context: existing,
                changed: false,
            });
        }

        let current = query_workspace_context(&transaction, &authenticated.user.user_id)?;
        if current.revision != request.expected_revision {
            return Err(AuthContextError::RevisionConflict {
                expected: request.expected_revision,
                actual: current.revision,
            });
        }
        require_membership(
            &transaction,
            &authenticated.user.user_id,
            &request.tenant_id,
        )?;
        let project_exists = transaction
            .query_row(
                "SELECT 1 FROM desktop_projects
                 WHERE id = ?1 AND tenant_id = ?2 AND status = 'active'",
                params![request.project_id, request.tenant_id],
                |_| Ok(()),
            )
            .optional()
            .map_err(|error| AuthContextError::Storage(error.to_string()))?
            .is_some();
        if !project_exists {
            return Err(AuthContextError::ProjectUnavailable);
        }

        let revision = current.revision.saturating_add(1);
        transaction
            .execute(
                "UPDATE desktop_workspace_contexts
                 SET tenant_id = ?1, project_id = ?2, revision = ?3, updated_at_ms = ?4
                 WHERE user_id = ?5",
                params![
                    request.tenant_id,
                    request.project_id,
                    revision,
                    now_ms,
                    authenticated.user.user_id
                ],
            )
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        let context = DesktopWorkspaceContext {
            tenant_id: request.tenant_id.clone(),
            project_id: request.project_id.clone(),
            revision,
            updated_at: iso_from_millis(now_ms),
        };
        let value_json = serde_json::to_string(&context)
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        transaction
            .execute(
                "INSERT INTO desktop_workspace_context_events(
                   id, user_id, session_id, from_tenant_id, from_project_id,
                   to_tenant_id, to_project_id, revision, idempotency_key,
                   created_at_ms, value_json
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
                params![
                    format!("local-context-event-{}", Uuid::new_v4()),
                    authenticated.user.user_id,
                    authenticated.session_id,
                    current.tenant_id,
                    current.project_id,
                    context.tenant_id,
                    context.project_id,
                    context.revision,
                    request.idempotency_key,
                    now_ms,
                    value_json
                ],
            )
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        transaction
            .commit()
            .map_err(|error| AuthContextError::Storage(error.to_string()))?;
        Ok(ContextSwitchOutcome {
            context,
            changed: true,
        })
    }

    #[cfg(test)]
    pub(super) fn seed_test_session(&self, credential: &str) -> Result<(), String> {
        self.create_local_session(credential.to_string(), true, Utc::now().timestamp_millis())
            .map(|_| ())
            .map_err(|error| error.to_string())
    }
}

fn query_user(
    connection: &Connection,
    user_id: &str,
    membership_role: &str,
) -> Result<DesktopUser, String> {
    connection
        .query_row(
            "SELECT id, email, display_name, status, created_at_ms
             FROM desktop_users WHERE id = ?1",
            [user_id],
            |row| {
                Ok(DesktopUser {
                    user_id: row.get(0)?,
                    email: row.get(1)?,
                    name: row.get(2)?,
                    roles: vec![membership_role.to_string()],
                    is_active: row.get::<_, String>(3)? == "active",
                    created_at: iso_from_millis(row.get(4)?),
                    profile: json!({}),
                    preferred_language: None,
                })
            },
        )
        .map_err(|error| error.to_string())
}

fn query_workspace_context(
    connection: &Connection,
    user_id: &str,
) -> Result<DesktopWorkspaceContext, AuthContextError> {
    connection
        .query_row(
            "SELECT tenant_id, project_id, revision, updated_at_ms
             FROM desktop_workspace_contexts WHERE user_id = ?1",
            [user_id],
            |row| {
                Ok(DesktopWorkspaceContext {
                    tenant_id: row.get(0)?,
                    project_id: row.get(1)?,
                    revision: row.get(2)?,
                    updated_at: iso_from_millis(row.get(3)?),
                })
            },
        )
        .map_err(|error| AuthContextError::Storage(error.to_string()))
}

fn query_context_event(
    transaction: &Transaction<'_>,
    user_id: &str,
    idempotency_key: &str,
) -> Result<Option<DesktopWorkspaceContext>, AuthContextError> {
    let value = transaction
        .query_row(
            "SELECT value_json FROM desktop_workspace_context_events
             WHERE user_id = ?1 AND idempotency_key = ?2",
            params![user_id, idempotency_key],
            |row| row.get::<_, String>(0),
        )
        .optional()
        .map_err(|error| AuthContextError::Storage(error.to_string()))?;
    value
        .map(|value| {
            serde_json::from_str(&value)
                .map_err(|error| AuthContextError::Storage(error.to_string()))
        })
        .transpose()
}

fn require_membership(
    connection: &Connection,
    user_id: &str,
    tenant_id: &str,
) -> Result<(), AuthContextError> {
    let membership = connection
        .query_row(
            "SELECT 1 FROM desktop_tenant_memberships
             WHERE user_id = ?1 AND tenant_id = ?2 AND status = 'active'",
            params![user_id, tenant_id],
            |_| Ok(()),
        )
        .optional()
        .map_err(|error| AuthContextError::Storage(error.to_string()))?;
    membership.ok_or(AuthContextError::MembershipRequired)
}

fn credential_digest(credential: &str) -> String {
    let digest = Sha256::digest(credential.as_bytes());
    let mut encoded = String::with_capacity(7 + digest.len() * 2);
    encoded.push_str("sha256:");
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(encoded, "{byte:02x}");
    }
    encoded
}

fn iso_from_millis(value: i64) -> String {
    chrono::DateTime::from_timestamp_millis(value)
        .unwrap_or_else(Utc::now)
        .to_rfc3339()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn session_credentials_are_hashed_and_revocation_is_immediate() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let now_ms = Utc::now().timestamp_millis();
        let outcome = store
            .create_local_session("raw-session-secret".to_string(), true, now_ms)
            .expect("create session");

        let connection = store.connection().expect("connection");
        let persisted: String = connection
            .query_row(
                "SELECT token_digest FROM desktop_user_sessions WHERE id = ?1",
                [outcome.session.session_id.as_str()],
                |row| row.get(0),
            )
            .expect("persisted digest");
        drop(connection);
        assert!(persisted.starts_with("sha256:"));
        assert!(!persisted.contains("raw-session-secret"));
        let authenticated = store
            .validate_session_credential("raw-session-secret", now_ms)
            .expect("validate")
            .expect("authenticated");
        store
            .revoke_session(&authenticated.session_id, now_ms + 1)
            .expect("revoke");
        assert!(store
            .validate_session_credential("raw-session-secret", now_ms + 2)
            .expect("validate revoked")
            .is_none());
    }

    #[test]
    fn trusted_session_resume_rotates_the_credential_and_skips_untrusted_sessions() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let now_ms = Utc::now().timestamp_millis();
        let original = store
            .create_local_session("trusted-original".to_string(), true, now_ms)
            .expect("create trusted session");

        let resumed = store
            .resume_trusted_local_session(
                &original.session.session_id,
                "trusted-rotated".to_string(),
                now_ms + 1,
            )
            .expect("resume trusted session")
            .expect("trusted session available");
        assert_eq!(resumed.session.session_id, original.session.session_id);
        assert!(resumed.session.trusted_device);
        assert!(store
            .validate_session_credential("trusted-original", now_ms + 2)
            .expect("validate rotated credential")
            .is_none());
        assert!(store
            .validate_session_credential("trusted-rotated", now_ms + 2)
            .expect("validate resumed credential")
            .is_some());

        store
            .revoke_session(&resumed.session.session_id, now_ms + 3)
            .expect("revoke trusted session");
        let untrusted = store
            .create_local_session("untrusted".to_string(), false, now_ms + 4)
            .expect("create untrusted session");
        assert!(store
            .resume_trusted_local_session(
                &untrusted.session.session_id,
                "should-not-resume".to_string(),
                now_ms + 5,
            )
            .expect("resume lookup")
            .is_none());
    }

    #[test]
    fn trusted_session_reference_survives_store_reopen_without_persisting_the_bearer() {
        let path = std::env::temp_dir().join(format!(
            "agistack-trusted-session-{}.sqlite3",
            Uuid::new_v4()
        ));
        let now_ms = Utc::now().timestamp_millis();
        let original = {
            let store = DesktopSessionStore::open(&path).expect("open session store");
            store
                .create_local_session("restart-original".to_string(), true, now_ms)
                .expect("create trusted session")
        };

        let reopened = DesktopSessionStore::open(&path).expect("reopen session store");
        let resumed = reopened
            .resume_trusted_local_session(
                &original.session.session_id,
                "restart-rotated".to_string(),
                now_ms + 1,
            )
            .expect("resume after reopen")
            .expect("trusted session available");
        assert_eq!(resumed.session.expires_at, original.session.expires_at);
        assert!(reopened
            .validate_session_credential("restart-original", now_ms + 2)
            .expect("validate old bearer")
            .is_none());
        assert!(reopened
            .validate_session_credential("restart-rotated", now_ms + 2)
            .expect("validate rotated bearer")
            .is_some());
        drop(reopened);
        let _ = std::fs::remove_file(path);
    }

    #[test]
    fn local_session_request_defaults_to_untrusted() {
        let request: LocalSessionRequest = serde_json::from_str("{}").expect("request");
        assert!(!request.trusted_device);
    }

    #[test]
    fn context_switch_is_revision_guarded_idempotent_and_tenant_scoped() {
        let store = DesktopSessionStore::in_memory().expect("session store");
        let now_ms = Utc::now().timestamp_millis();
        store
            .create_local_session("context-secret".to_string(), true, now_ms)
            .expect("create session");
        let authenticated = store
            .validate_session_credential("context-secret", now_ms)
            .expect("validate")
            .expect("authenticated");
        let request = ContextSwitchRequest {
            tenant_id: "northstar".to_string(),
            project_id: "desktop-client".to_string(),
            expected_revision: 0,
            idempotency_key: "switch-northstar-desktop".to_string(),
        };

        let first = store
            .switch_workspace_context(&authenticated, &request, now_ms + 1)
            .expect("switch");
        assert!(first.changed);
        assert_eq!(first.context.revision, 1);
        assert!(!store
            .session_context_is_current(&authenticated, now_ms + 1)
            .expect("stale context"));
        let refreshed = store
            .validate_session_credential("context-secret", now_ms + 1)
            .expect("validate refreshed")
            .expect("refreshed context");
        assert!(store
            .session_context_is_current(&refreshed, now_ms + 1)
            .expect("current context"));
        let replay = store
            .switch_workspace_context(&authenticated, &request, now_ms + 2)
            .expect("replay");
        assert!(!replay.changed);
        assert_eq!(replay.context, first.context);

        let stale = store
            .switch_workspace_context(
                &authenticated,
                &ContextSwitchRequest {
                    tenant_id: "orbital".to_string(),
                    project_id: "agent-evals".to_string(),
                    expected_revision: 0,
                    idempotency_key: "stale-switch".to_string(),
                },
                now_ms + 3,
            )
            .expect_err("stale revision");
        assert!(matches!(stale, AuthContextError::RevisionConflict { .. }));

        let mismatched = store
            .switch_workspace_context(
                &authenticated,
                &ContextSwitchRequest {
                    tenant_id: "northstar".to_string(),
                    project_id: "agent-evals".to_string(),
                    expected_revision: 1,
                    idempotency_key: "mismatched-project".to_string(),
                },
                now_ms + 4,
            )
            .expect_err("tenant project mismatch");
        assert!(matches!(mismatched, AuthContextError::ProjectUnavailable));
        assert_eq!(
            store.workspace_context(LOCAL_USER_ID).expect("context"),
            first.context
        );
    }
}
