use std::sync::Arc;
use std::time::Duration;

use super::*;
use axum::extract::ws::WebSocketUpgrade;
use axum::extract::{Path, Query, State};
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::{Extension, Json};
use serde::Serialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use sqlx::FromRow;

mod hub;

#[cfg(test)]
use axum::http::HeaderValue;
use hub::{TerminalHub, TerminalHubConnect, TerminalHubManager};

const CONTRACT_VERSION: u8 = 2;
const INPUT_BUFFER_MESSAGES: usize = 256;
const OUTPUT_BUFFER_MESSAGES: usize = 512;
const REPLAY_BUFFER_BYTES: usize = 512 * 1024;
const TERMINAL_FRAME_BYTES: usize = 64 * 1024;
const INPUT_SEND_TIMEOUT_MILLIS: u64 = 250;
const AUTHORITY_RECHECK_SECONDS: u64 = 5;
const AUTHORITY_HEALTH_TIMEOUT_MILLIS: u64 = 500;
const DEFAULT_DISCONNECT_GRACE_SECONDS: i64 = 30;
const TERMINAL_RESUME_SUBPROTOCOL: &str = "memstack.terminal-v2";
const SERVER_REPLICA_COUNT_ENV: &str = "AGISTACK_SERVER_REPLICA_COUNT";
const TERMINAL_INSTANCE_AFFINITY_ENV: &str = "AGISTACK_TERMINAL_INSTANCE_AFFINITY";
const TERMINAL_RUN_AUTHORITY_SQL: &str = "\
SELECT c.tenant_id, c.user_id, apr.project_id, apr.conversation_id, apr.id AS run_id, \
       apr.revision AS run_revision, \
       NULLIF(apr.authorization_snapshot -> 'environment' ->> 'kind', '') AS environment_kind, \
       NULLIF(apr.authorization_snapshot -> 'environment' ->> 'id', '') AS environment_id, \
       NULLIF(apr.authorization_snapshot -> 'environment' ->> 'workspace_path', '') \
         AS workspace_path \
FROM agent_plan_runs apr \
INNER JOIN conversations c ON c.id = apr.conversation_id \
WHERE apr.id = $1 \
  AND apr.project_id = $2 \
  AND apr.revision = $3 \
  AND c.tenant_id = $4 \
  AND c.user_id = $5 \
  AND c.project_id = apr.project_id \
  AND apr.status = 'running' \
  AND apr.permission_profile = 'full_access' \
  AND apr.authorization_snapshot ->> 'conversation_id' = apr.conversation_id \
  AND apr.authorization_snapshot ->> 'project_id' = apr.project_id \
  AND apr.authorization_snapshot ->> 'plan_version_id' = apr.plan_version_id \
  AND apr.authorization_snapshot ->> 'permission_profile' = apr.permission_profile \
  AND apr.authorization_snapshot -> 'environment' ->> 'kind' IN ('local', 'worktree') \
  AND NULLIF(apr.authorization_snapshot -> 'environment' ->> 'id', '') IS NOT NULL \
  AND apr.authorization_snapshot -> 'environment' ->> 'workspace_path' = '/workspace' \
  AND EXISTS (SELECT 1 FROM user_projects up \
              WHERE up.project_id = apr.project_id AND up.user_id = c.user_id) \
  AND EXISTS (SELECT 1 FROM user_tenants ut \
              WHERE ut.tenant_id = c.tenant_id AND ut.user_id = c.user_id)";

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct TerminalSessionV2Record {
    pub(crate) contract_version: u8,
    pub(crate) session_id: String,
    pub(crate) resume_token_hash: String,
    pub(crate) tenant_id: String,
    pub(crate) project_id: String,
    pub(crate) conversation_id: String,
    pub(crate) run_id: String,
    pub(crate) run_revision: i32,
    pub(crate) environment_id: String,
    pub(crate) cwd: String,
    pub(crate) environment_source: String,
    pub(crate) cwd_source: String,
    pub(crate) created_at_ms: i64,
    pub(crate) expires_at_ms: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, FromRow)]
struct TerminalRunAuthority {
    tenant_id: String,
    user_id: String,
    project_id: String,
    conversation_id: String,
    run_id: String,
    run_revision: i32,
    environment_kind: String,
    environment_id: String,
    workspace_path: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct TerminalEnvironmentAuthority {
    environment_id: String,
    cwd: String,
    environment_source: String,
    cwd_source: String,
}

#[derive(Debug, Serialize)]
struct TerminalV2ErrorBody {
    code: &'static str,
    message: &'static str,
    refetch: bool,
}

#[derive(Debug)]
pub(super) struct TerminalV2Error {
    status: StatusCode,
    code: &'static str,
    message: &'static str,
    refetch: bool,
}

impl TerminalV2Error {
    fn unavailable() -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            code: "terminal_session_v2_unavailable",
            message: "TerminalSessionV2 authority is unavailable",
            refetch: false,
        }
    }

    fn instance_affinity_unavailable() -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            code: "terminal_session_v2_instance_affinity_unavailable",
            message: "TerminalSessionV2 requires instance affinity in multi-replica deployments",
            refetch: false,
        }
    }

    fn authority() -> Self {
        Self {
            status: StatusCode::CONFLICT,
            code: "terminal_authority_mismatch",
            message: "Canonical run authority no longer matches",
            refetch: true,
        }
    }

    fn invalid_resume_token() -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            code: "terminal_resume_token_invalid",
            message: "Terminal resume token is invalid",
            refetch: false,
        }
    }

    fn lost() -> Self {
        Self {
            status: StatusCode::GONE,
            code: "terminal_session_lost",
            message: "The server-side terminal session no longer exists",
            refetch: true,
        }
    }

    fn internal() -> Self {
        Self {
            status: StatusCode::BAD_GATEWAY,
            code: "terminal_upstream_unavailable",
            message: "The terminal upstream is unavailable",
            refetch: false,
        }
    }
}

impl IntoResponse for TerminalV2Error {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({
                "detail": TerminalV2ErrorBody {
                    code: self.code,
                    message: self.message,
                    refetch: self.refetch,
                }
            })),
        )
            .into_response()
    }
}

pub(super) struct TerminalV2Service {
    authority_pool: agistack_adapters_postgres::PgPool,
    registry: SharedHttpServiceRegistry,
    hubs: Arc<TerminalHubManager>,
}

impl TerminalV2Service {
    pub(super) fn new(
        authority_pool: agistack_adapters_postgres::PgPool,
        registry: SharedHttpServiceRegistry,
    ) -> Self {
        Self {
            authority_pool,
            registry,
            hubs: Arc::new(TerminalHubManager::default()),
        }
    }

    pub(super) fn is_available(&self) -> bool {
        self.registry.is_durable()
    }

    pub(super) async fn registry_is_healthy(&self) -> bool {
        self.registry.is_durable() && self.registry.health_check().await.is_ok()
    }

    pub(super) async fn authority_is_healthy(&self) -> bool {
        matches!(
            tokio::time::timeout(
                Duration::from_millis(AUTHORITY_HEALTH_TIMEOUT_MILLIS),
                sqlx::query_scalar::<_, i32>("SELECT 1").fetch_one(&self.authority_pool),
            )
            .await,
            Ok(Ok(1))
        )
    }

    pub(super) fn instance_affinity_is_ready(&self) -> bool {
        terminal_v2_instance_affinity_ready_from_env()
    }

    async fn authority(
        &self,
        tenant_id: &str,
        project_id: &str,
        run_id: &str,
        run_revision: i32,
        user_id: &str,
    ) -> Result<TerminalRunAuthority, TerminalV2Error> {
        load_terminal_authority(
            &self.authority_pool,
            tenant_id,
            project_id,
            run_id,
            run_revision,
            user_id,
        )
        .await
        .ok_or_else(TerminalV2Error::authority)
    }

    async fn create(
        &self,
        info: &ProjectSandboxInfo,
        authority: TerminalRunAuthority,
    ) -> Result<TerminalSessionV2Response, TerminalV2Error> {
        if !self.is_available() {
            return Err(TerminalV2Error::unavailable());
        }
        if !self.instance_affinity_is_ready() {
            return Err(TerminalV2Error::instance_affinity_unavailable());
        }
        let environment = resolve_terminal_environment(info, &authority)?;
        let terminal_url = info
            .terminal_url
            .as_deref()
            .ok_or_else(TerminalV2Error::internal)?;
        let runtime_auth_token = info
            .runtime_auth_token
            .as_ref()
            .ok_or_else(TerminalV2Error::internal)?;
        let ws_target = build_terminal_websocket_target(terminal_url)
            .map_err(|_| TerminalV2Error::internal())?;
        let origin = terminal_websocket_origin(terminal_url, &ws_target);
        let auth_header = sandbox_basic_auth_header(runtime_auth_token)
            .map_err(|_| TerminalV2Error::internal())?;
        let session_id = agistack_adapters_secrets::try_generate_uuid_v4()
            .map_err(|_| TerminalV2Error::internal())?;
        let resume_token = agistack_adapters_secrets::try_generate_urlsafe_token(32)
            .map_err(|_| TerminalV2Error::internal())?;
        let created_at_ms = now_ms();
        let ttl_seconds = terminal_session_ttl_seconds();
        let expires_at_ms = created_at_ms + ttl_seconds * 1_000;
        let hub = TerminalHub::connect(TerminalHubConnect {
            session_id: session_id.clone(),
            ws_target,
            origin,
            auth_header,
            authority_pool: self.authority_pool.clone(),
            authority: authority.clone(),
            environment: environment.clone(),
            expires_at_ms,
        })
        .await?;
        let record = TerminalSessionV2Record {
            contract_version: CONTRACT_VERSION,
            session_id: session_id.clone(),
            resume_token_hash: resume_token_hash(&resume_token),
            tenant_id: authority.tenant_id.clone(),
            project_id: authority.project_id.clone(),
            conversation_id: authority.conversation_id.clone(),
            run_id: authority.run_id.clone(),
            run_revision: authority.run_revision,
            environment_id: environment.environment_id,
            cwd: environment.cwd,
            environment_source: environment.environment_source,
            cwd_source: environment.cwd_source,
            created_at_ms,
            expires_at_ms,
        };
        if let Err(error) = self
            .registry
            .upsert_terminal_session_v2(record.clone(), ttl_seconds)
            .await
        {
            hub.mark_lost("terminal_session_lost");
            return Err(TerminalV2Error {
                status: error.status,
                code: "terminal_session_persistence_failed",
                message: "Terminal session persistence failed",
                refetch: false,
            });
        }
        self.hubs.insert(session_id, Arc::clone(&hub)).await;
        hub.install_cleanup(
            Arc::clone(&self.registry),
            authority.project_id,
            Arc::downgrade(&self.hubs),
        )
        .await;
        Ok(response_from_record(record, resume_token))
    }

    async fn validate_resume(
        &self,
        tenant_id: &str,
        project_id: &str,
        session_id: &str,
        resume_token: &str,
        user_id: &str,
        info: &ProjectSandboxInfo,
    ) -> Result<(TerminalSessionV2Record, Arc<TerminalHub>), TerminalV2Error> {
        if !self.is_available() {
            return Err(TerminalV2Error::unavailable());
        }
        if !self.instance_affinity_is_ready() {
            return Err(TerminalV2Error::instance_affinity_unavailable());
        }
        let record = self
            .registry
            .get_terminal_session_v2(project_id, session_id)
            .await
            .map_err(|_| TerminalV2Error::internal())?
            .ok_or_else(TerminalV2Error::lost)?;
        if record.tenant_id != tenant_id
            || record.project_id != project_id
            || !constant_time_hash_matches(&record.resume_token_hash, resume_token)
        {
            return Err(TerminalV2Error::invalid_resume_token());
        }
        let authority = self
            .authority(
                tenant_id,
                project_id,
                &record.run_id,
                record.run_revision,
                user_id,
            )
            .await?;
        if authority.conversation_id != record.conversation_id {
            return Err(TerminalV2Error::authority());
        }
        let Some(hub) = self.hubs.get(session_id).await else {
            self.registry
                .remove_terminal_session_v2(project_id, session_id)
                .await
                .map_err(|_| TerminalV2Error::internal())?;
            return Err(TerminalV2Error::lost());
        };
        let environment = match resolve_terminal_environment(info, &authority) {
            Ok(environment) => environment,
            Err(error) => {
                hub.finalize_lost("terminal_authority_revoked").await;
                return Err(error);
            }
        };
        if record.environment_id != environment.environment_id
            || record.cwd != environment.cwd
            || record.environment_source != environment.environment_source
            || record.cwd_source != environment.cwd_source
            || hub.environment != environment
        {
            hub.finalize_lost("terminal_authority_revoked").await;
            return Err(TerminalV2Error::authority());
        }
        Ok((record, hub))
    }
}

pub(super) fn terminal_v2_instance_affinity_ready(
    replica_count: Option<&str>,
    affinity_enabled: Option<&str>,
) -> bool {
    let replicas = match replica_count {
        None => 1,
        Some(raw) => match raw.trim().parse::<u32>() {
            Ok(value) if value > 0 => value,
            _ => return false,
        },
    };
    replicas == 1 || matches!(affinity_enabled.map(str::trim), Some("true" | "1"))
}

fn terminal_v2_instance_affinity_ready_from_env() -> bool {
    let replica_count = std::env::var(SERVER_REPLICA_COUNT_ENV).ok();
    let affinity_enabled = std::env::var(TERMINAL_INSTANCE_AFFINITY_ENV).ok();
    terminal_v2_instance_affinity_ready(replica_count.as_deref(), affinity_enabled.as_deref())
}

async fn load_terminal_authority(
    pool: &agistack_adapters_postgres::PgPool,
    tenant_id: &str,
    project_id: &str,
    run_id: &str,
    run_revision: i32,
    user_id: &str,
) -> Option<TerminalRunAuthority> {
    sqlx::query_as::<_, TerminalRunAuthority>(TERMINAL_RUN_AUTHORITY_SQL)
        .bind(run_id)
        .bind(project_id)
        .bind(run_revision)
        .bind(tenant_id)
        .bind(user_id)
        .fetch_optional(pool)
        .await
        .ok()
        .flatten()
}

fn response_from_record(
    record: TerminalSessionV2Record,
    resume_token: String,
) -> TerminalSessionV2Response {
    TerminalSessionV2Response {
        contract_version: record.contract_version,
        session_id: record.session_id,
        resume_token,
        project_id: record.project_id,
        conversation_id: record.conversation_id,
        run_id: record.run_id,
        run_revision: record.run_revision,
        environment_id: record.environment_id,
        cwd: record.cwd,
        created_at: rfc3339(record.created_at_ms),
        expires_at: rfc3339(record.expires_at_ms),
        resumable: true,
    }
}

fn resolve_terminal_environment(
    info: &ProjectSandboxInfo,
    authority: &TerminalRunAuthority,
) -> Result<TerminalEnvironmentAuthority, TerminalV2Error> {
    if info.project_id != authority.project_id
        || info.tenant_id != authority.tenant_id
        || !info.sandbox_type.eq_ignore_ascii_case("cloud")
        || info.sandbox_id.trim().is_empty()
        || info.sandbox_id != authority.environment_id
        || info.state != agistack_core::ports::ContainerState::Running
        || authority.workspace_path != "/workspace"
    {
        return Err(TerminalV2Error::authority());
    }
    Ok(TerminalEnvironmentAuthority {
        environment_id: authority.environment_id.clone(),
        cwd: authority.workspace_path.clone(),
        environment_source: "agent_plan_runs.authorization_snapshot.environment.id".to_string(),
        cwd_source: "agent_plan_runs.authorization_snapshot.environment.workspace_path".to_string(),
    })
}

fn resume_token_hash(token: &str) -> String {
    format!("{:x}", Sha256::digest(token.as_bytes()))
}

fn constant_time_hash_matches(expected_hash: &str, token: &str) -> bool {
    let actual_hash = resume_token_hash(token);
    if expected_hash.len() != actual_hash.len() {
        return false;
    }
    expected_hash
        .as_bytes()
        .iter()
        .zip(actual_hash.as_bytes())
        .fold(0_u8, |difference, (left, right)| {
            difference | (left ^ right)
        })
        == 0
}

fn terminal_v2_output_message(sequence: u64, data: &str) -> String {
    json!({
        "type": "output",
        "sequence": sequence,
        "data": data,
    })
    .to_string()
}

fn shell_single_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

fn disconnect_grace_seconds() -> i64 {
    std::env::var("WORKSPACE_TERMINAL_DISCONNECT_GRACE_SECONDS")
        .ok()
        .and_then(|raw| raw.parse::<i64>().ok())
        .map(|seconds| seconds.clamp(5, 300))
        .unwrap_or(DEFAULT_DISCONNECT_GRACE_SECONDS)
}

fn terminal_v2_service(app: &AppState) -> Result<Arc<TerminalV2Service>, TerminalV2Error> {
    app.sandboxes
        .terminal_v2
        .as_ref()
        .filter(|service| service.is_available())
        .cloned()
        .ok_or_else(TerminalV2Error::unavailable)
}

fn terminal_resume_token(headers: &HeaderMap) -> Option<String> {
    headers
        .get("sec-websocket-protocol")
        .and_then(|value| value.to_str().ok())
        .and_then(|protocols| {
            let protocols = protocols.split(',').map(str::trim).collect::<Vec<_>>();
            protocols.windows(2).find_map(|pair| {
                (pair[0] == TERMINAL_RESUME_SUBPROTOCOL && !pair[1].is_empty())
                    .then(|| pair[1].to_string())
            })
        })
}

pub(super) async fn create_terminal_session_v2(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(request): Json<CreateTerminalSessionV2Request>,
) -> Result<Json<TerminalSessionV2Response>, TerminalV2Error> {
    ensure_project_access(&app, &identity, &project_id)
        .await
        .map_err(|_| TerminalV2Error::authority())?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id)
        .await
        .map_err(|_| TerminalV2Error::authority())?;
    let service = terminal_v2_service(&app)?;
    let authority = service
        .authority(
            &tenant_id,
            &project_id,
            &request.run_id,
            request.expected_run_revision,
            &identity.user_id,
        )
        .await?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await
        .map_err(|_| TerminalV2Error::internal())?
        .ok_or_else(TerminalV2Error::authority)?;
    service.create(&info, authority).await.map(Json)
}

pub(super) async fn resume_terminal_session_v2(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, session_id)): Path<(String, String)>,
    Json(request): Json<ResumeTerminalSessionV2Request>,
) -> Result<Json<TerminalSessionV2Response>, TerminalV2Error> {
    ensure_project_access(&app, &identity, &project_id)
        .await
        .map_err(|_| TerminalV2Error::authority())?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id)
        .await
        .map_err(|_| TerminalV2Error::authority())?;
    let service = terminal_v2_service(&app)?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await
        .map_err(|_| TerminalV2Error::internal())?
        .ok_or_else(TerminalV2Error::authority)?;
    let (record, _) = service
        .validate_resume(
            &tenant_id,
            &project_id,
            &session_id,
            &request.resume_token,
            &identity.user_id,
            &info,
        )
        .await?;
    Ok(Json(response_from_record(record, request.resume_token)))
}

pub(super) async fn terminal_session_v2_websocket(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, session_id)): Path<(String, String)>,
    Query(query): Query<TerminalSessionV2WsQuery>,
    headers: HeaderMap,
    ws: WebSocketUpgrade,
) -> Result<Response, TerminalV2Error> {
    ensure_project_access(&app, &identity, &project_id)
        .await
        .map_err(|_| TerminalV2Error::authority())?;
    let tenant_id = project_tenant_id(&app, &identity, &project_id)
        .await
        .map_err(|_| TerminalV2Error::authority())?;
    let service = terminal_v2_service(&app)?;
    let info = app
        .sandboxes
        .get(&project_id)
        .await
        .map_err(|_| TerminalV2Error::internal())?
        .ok_or_else(TerminalV2Error::authority)?;
    let resume_token =
        terminal_resume_token(&headers).ok_or_else(TerminalV2Error::invalid_resume_token)?;
    let (_, hub) = service
        .validate_resume(
            &tenant_id,
            &project_id,
            &session_id,
            &resume_token,
            &identity.user_id,
            &info,
        )
        .await?;
    Ok(websocket_upgrade_with_auth_protocol(ws, &headers)
        .on_upgrade(move |socket| hub.attach(socket, query.after_sequence.unwrap_or(0)))
        .into_response())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn terminal_info() -> ProjectSandboxInfo {
        ProjectSandboxInfo {
            sandbox_id: "s1".to_string(),
            project_id: "p1".to_string(),
            tenant_id: "t1".to_string(),
            sandbox_type: "cloud".to_string(),
            profile: SandboxProfile::Standard,
            state: agistack_core::ports::ContainerState::Running,
            exit_code: None,
            created_at_ms: 0,
            started_at_ms: Some(0),
            last_accessed_at_ms: 0,
            metadata_json: json!({ "profile": "standard" }),
            local_config: json!({}),
            endpoint: None,
            websocket_url: None,
            mcp_port: None,
            desktop_port: None,
            terminal_port: None,
            desktop_url: None,
            terminal_url: None,
            runtime_auth_token: None,
        }
    }

    fn terminal_authority() -> TerminalRunAuthority {
        TerminalRunAuthority {
            tenant_id: "t1".to_string(),
            user_id: "u1".to_string(),
            project_id: "p1".to_string(),
            conversation_id: "c1".to_string(),
            run_id: "r1".to_string(),
            run_revision: 1,
            environment_kind: "worktree".to_string(),
            environment_id: "s1".to_string(),
            workspace_path: "/workspace".to_string(),
        }
    }

    #[test]
    fn resume_token_storage_is_hash_only_and_constant_time_checked() {
        let token = "high-entropy-resume-token";
        let hash = resume_token_hash(token);
        assert_ne!(hash, token);
        assert_eq!(hash.len(), 64);
        assert!(constant_time_hash_matches(&hash, token));
        assert!(!constant_time_hash_matches(&hash, "different-token"));
    }

    #[test]
    fn terminal_v2_response_preserves_exact_run_and_environment_scope() {
        let record = TerminalSessionV2Record {
            contract_version: 2,
            session_id: "session-1".to_string(),
            resume_token_hash: resume_token_hash("resume-1"),
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            conversation_id: "conversation-1".to_string(),
            run_id: "run-1".to_string(),
            run_revision: 7,
            environment_id: "environment-1".to_string(),
            cwd: "/workspace".to_string(),
            environment_source: "agent_plan_runs.authorization_snapshot.environment.id".to_string(),
            cwd_source: "agent_plan_runs.authorization_snapshot.environment.workspace_path"
                .to_string(),
            created_at_ms: 1_700_000_000_000,
            expires_at_ms: 1_700_000_300_000,
        };
        let response = response_from_record(record, "resume-1".to_string());
        assert_eq!(response.contract_version, 2);
        assert_eq!(response.run_id, "run-1");
        assert_eq!(response.run_revision, 7);
        assert_eq!(response.environment_id, "environment-1");
        assert_eq!(response.cwd, "/workspace");
        assert_eq!(response.resume_token, "resume-1");
        assert!(response.resumable);
    }

    #[test]
    fn terminal_cwd_command_quotes_shell_metacharacters() {
        assert_eq!(
            shell_single_quote("/workspace/it's isolated"),
            "'/workspace/it'\"'\"'s isolated'"
        );
    }

    #[test]
    fn terminal_environment_requires_persisted_exact_sandbox_and_canonical_cwd() {
        let mut info = terminal_info();
        let mut run_authority = terminal_authority();
        let environment = resolve_terminal_environment(&info, &run_authority).unwrap();
        assert_eq!(environment.environment_id, "s1");
        assert_eq!(
            environment.environment_source,
            "agent_plan_runs.authorization_snapshot.environment.id"
        );
        assert_eq!(environment.cwd, "/workspace");
        assert_eq!(
            environment.cwd_source,
            "agent_plan_runs.authorization_snapshot.environment.workspace_path"
        );

        info.sandbox_id = "different-live-sandbox".to_string();
        assert_eq!(
            resolve_terminal_environment(&info, &run_authority)
                .unwrap_err()
                .status,
            StatusCode::CONFLICT
        );

        info.sandbox_id = "s1".to_string();
        run_authority.workspace_path = "/workspace/guessed".to_string();
        assert_eq!(
            resolve_terminal_environment(&info, &run_authority)
                .unwrap_err()
                .status,
            StatusCode::CONFLICT
        );
    }

    #[test]
    fn websocket_resume_token_accepts_only_non_url_subprotocol_authority() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "sec-websocket-protocol",
            HeaderValue::from_static(
                "memstack.auth, api-key, memstack.terminal-v2, protocol-resume-token",
            ),
        );
        assert_eq!(
            terminal_resume_token(&headers).as_deref(),
            Some("protocol-resume-token")
        );
        assert!(terminal_resume_token(&HeaderMap::new()).is_none());
    }

    #[test]
    fn canonical_authority_query_requires_exact_scope_and_running_full_access() {
        for clause in [
            "apr.id = $1",
            "apr.project_id = $2",
            "apr.revision = $3",
            "c.tenant_id = $4",
            "c.user_id = $5",
            "c.id = apr.conversation_id",
            "c.project_id = apr.project_id",
            "apr.status = 'running'",
            "apr.permission_profile = 'full_access'",
            "authorization_snapshot -> 'environment' ->> 'kind'",
            "authorization_snapshot -> 'environment' ->> 'id'",
            "authorization_snapshot -> 'environment' ->> 'workspace_path'",
            "EXISTS (SELECT 1 FROM user_projects",
            "EXISTS (SELECT 1 FROM user_tenants",
        ] {
            assert!(
                TERMINAL_RUN_AUTHORITY_SQL.contains(clause),
                "missing authority clause: {clause}"
            );
        }
    }

    #[tokio::test]
    async fn terminal_v2_authority_health_fails_closed_when_postgres_is_unreachable() {
        let service = TerminalV2Service::new(
            sqlx::postgres::PgPoolOptions::new()
                .acquire_timeout(Duration::from_millis(25))
                .connect_lazy("postgres://postgres:postgres@127.0.0.1:1/memstack")
                .expect("test postgres URL is valid"),
            in_memory_http_service_registry(),
        );

        assert!(!service.authority_is_healthy().await);
    }
}
