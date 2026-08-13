use std::path::PathBuf;
use std::sync::{Arc, OnceLock};
use std::time::Duration;

use anyhow::{Context, Result, bail};
use bcs::{
    BcsConfig, BcsServer, BcsServerExtensions, CachePluginKind, InfrastructurePlugins,
    set_health_version,
};
use clap::{Parser, ValueEnum};
use memstack_workspace_core::agent_registry::HttpAgentRegistryPort;
use memstack_workspace_core::autonomy_judge::HttpWorkspaceAutonomyJudgePort;
use memstack_workspace_core::context_judge::HttpWorkspaceContextJudgePort;
use memstack_workspace_core::message_delivery::{
    WorkspaceMessageRuntime, WorkspaceMessageRuntimeConfig,
};
use memstack_workspace_core::message_delivery_worker::{
    WorkspaceMessageDeliveryWorker, WorkspaceMessageDeliveryWorkerConfig,
};
use memstack_workspace_core::object_store::build_workspace_object_store;
use memstack_workspace_core::outbox::{
    RedisWorkspaceEventPublisher, WorkspaceOutboxConfig, WorkspaceOutboxDispatcher,
};
use memstack_workspace_core::plan_judge::HttpWorkspacePlanJudgePort;
use memstack_workspace_core::plans::{PlanHttpState, plan_routes};
use memstack_workspace_core::provider_registry::HttpProviderRegistryPort;
use memstack_workspace_core::task_dispatch::{WorkspaceTaskRuntime, WorkspaceTaskRuntimeConfig};
use memstack_workspace_core::task_dispatch_worker::{
    WorkspaceTaskDispatchWorker, WorkspaceTaskDispatchWorkerConfig,
};
use memstack_workspace_core::workspace_provider_events::WorkspaceProviderBotEventService;
use memstack_workspace_core::{
    WorkspaceCoreAuthority, WorkspaceCoreState, workspace_router_with_message_runtime,
};
use tokio_util::sync::CancellationToken;
use tracing_subscriber::EnvFilter;

mod desktop_control;
mod plan_dispatch_provider;

use plan_dispatch_provider::HttpWorkspacePlanDispatchPort;

const HEALTH_VERSION: &str = concat!("memstack-workspace-core/", env!("CARGO_PKG_VERSION"));
const DESKTOP_GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, Copy, Default, ValueEnum)]
enum WorkspaceCoreMode {
    #[default]
    Cloud,
    DesktopLocal,
}

/// MemStack Workspace Core backed by Avernet BCS.
#[derive(Parser)]
#[command(name = "memstack-workspace-core", version, about)]
struct Args {
    /// Read the authenticated Desktop Local launch contract from private stdio.
    #[arg(long, default_value_t = false)]
    desktop_control: bool,

    /// Path to the Avernet BCS configuration directory or file.
    #[arg(short, long, value_name = "DIR", env = "BCS_CONFIG_DIR")]
    config_dir: Option<PathBuf>,

    /// Private service token used by the MemStack gateway.
    #[arg(
        long,
        env = "WORKSPACE_CORE_SERVICE_TOKEN",
        hide_env_values = true,
        default_value = ""
    )]
    service_token: String,

    /// Base URL of the external MemStack Agent Registry authority.
    #[arg(long, env = "WORKSPACE_CORE_AGENT_REGISTRY_URL", default_value = "")]
    agent_registry_url: String,

    /// Dedicated bearer token for structured Agent Registry lookups.
    #[arg(
        long,
        env = "WORKSPACE_CORE_AGENT_REGISTRY_TOKEN",
        hide_env_values = true,
        default_value = ""
    )]
    agent_registry_token: String,

    /// Timeout for one external Agent Registry lookup.
    #[arg(
        long,
        env = "WORKSPACE_CORE_AGENT_REGISTRY_TIMEOUT_SECONDS",
        default_value_t = 5.0
    )]
    agent_registry_timeout_seconds: f64,

    /// Exact authenticated Agent Runtime Provider webhook URL.
    #[arg(long, env = "WORKSPACE_CORE_PROVIDER_WEBHOOK_URL", default_value = "")]
    provider_webhook_url: String,

    /// Dedicated BCS-to-Provider bearer token.
    #[arg(
        long,
        env = "WORKSPACE_CORE_PROVIDER_WEBHOOK_TOKEN",
        hide_env_values = true,
        default_value = ""
    )]
    provider_webhook_token: String,

    /// Dedicated Provider-to-BCS `/bot/events` bearer token.
    #[arg(
        long,
        env = "WORKSPACE_CORE_PROVIDER_EVENT_TOKEN",
        hide_env_values = true,
        default_value = ""
    )]
    provider_event_token: String,

    /// Lifetime of one Workspace Agent Runtime callback correlation.
    #[arg(
        long,
        env = "WORKSPACE_CORE_PROVIDER_CALLBACK_TIMEOUT_MS",
        default_value_t = 3_600_000
    )]
    provider_callback_timeout_ms: u64,

    /// Exact authenticated Agent Runtime endpoint for structured Plan actions.
    #[arg(long, env = "WORKSPACE_CORE_PLAN_DISPATCH_URL", default_value = "")]
    plan_dispatch_url: String,

    /// Timeout for Provider acceptance of one Plan action.
    #[arg(
        long,
        env = "WORKSPACE_CORE_PLAN_DISPATCH_TIMEOUT_SECONDS",
        default_value_t = 10.0
    )]
    plan_dispatch_timeout_seconds: f64,

    /// Runtime topology. Cloud requires Redis outbox delivery; Desktop Local does not.
    #[arg(long, env = "WORKSPACE_CORE_MODE", value_enum, default_value_t)]
    mode: WorkspaceCoreMode,

    /// Stable lease identity; defaults to HOSTNAME plus the process id.
    #[arg(long, env = "WORKSPACE_CORE_INSTANCE_ID")]
    instance_id: Option<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let mut args = Args::parse();
    tracing_subscriber::fmt()
        .with_writer(std::io::stderr)
        .with_env_filter(EnvFilter::from_default_env())
        .try_init()
        .ok();

    let (
        mut desktop_control,
        principal_signing_key,
        group_session_ws_signing_key,
        desktop_legacy_import,
    ) = if args.desktop_control {
        let (control, initialize) = desktop_control::DesktopControl::read_initialize().await?;
        args.config_dir = Some(initialize.config_path().clone());
        args.mode = WorkspaceCoreMode::DesktopLocal;
        args.service_token = initialize.service_token().to_string();
        args.agent_registry_url = initialize.agent_registry_url().to_string();
        args.agent_registry_token = initialize.agent_registry_token().to_string();
        args.provider_webhook_url = initialize.provider_webhook_url().to_string();
        args.provider_webhook_token = initialize.provider_webhook_token().to_string();
        args.provider_event_token = initialize.provider_event_token().to_string();
        args.plan_dispatch_url = initialize.plan_dispatch_url().to_string();
        args.instance_id = Some(initialize.instance_id().to_string());
        let signing_key = control.principal_signing_key();
        let group_session_key = control.group_session_ws_signing_key();
        let legacy_import = (
            initialize.legacy_import_path().clone(),
            initialize.legacy_import_sha256().to_string(),
        );
        (
            Some(control),
            Some(signing_key),
            Some(group_session_key),
            Some(legacy_import),
        )
    } else {
        (None, None, None, None)
    };

    if args.service_token.trim().is_empty() {
        bail!("WORKSPACE_CORE_SERVICE_TOKEN must not be blank");
    }
    if !args.agent_registry_timeout_seconds.is_finite()
        || args.agent_registry_timeout_seconds <= 0.0
        || args.agent_registry_timeout_seconds > 60.0
    {
        bail!("WORKSPACE_CORE_AGENT_REGISTRY_TIMEOUT_SECONDS must be between 0 and 60");
    }
    if args.provider_webhook_url.trim().is_empty()
        || args.provider_webhook_token.trim().is_empty()
        || args.provider_event_token.trim().is_empty()
    {
        bail!("Workspace Provider URL and credentials must not be blank");
    }
    if !(1_000..=86_400_000).contains(&args.provider_callback_timeout_ms) {
        bail!("WORKSPACE_CORE_PROVIDER_CALLBACK_TIMEOUT_MS must be between 1000 and 86400000");
    }
    if !args.plan_dispatch_timeout_seconds.is_finite()
        || args.plan_dispatch_timeout_seconds <= 0.0
        || args.plan_dispatch_timeout_seconds > 60.0
    {
        bail!("WORKSPACE_CORE_PLAN_DISPATCH_TIMEOUT_SECONDS must be between 0 and 60");
    }
    require_distinct_credentials(&[
        ("service", args.service_token.as_str()),
        ("agent registry", args.agent_registry_token.as_str()),
        ("Provider webhook", args.provider_webhook_token.as_str()),
        ("Provider event", args.provider_event_token.as_str()),
    ])?;

    let config = BcsConfig::load_with_env(args.config_dir.as_ref());
    let desktop_api_base_url = if desktop_control.is_some() {
        if config.bind != "127.0.0.1" || config.port == 0 {
            bail!("Desktop Workspace Core must use an explicit IPv4 loopback port");
        }
        Some(format!("http://{}:{}", config.bind, config.port))
    } else {
        None
    };
    config.validate_api_keys().map_err(anyhow::Error::msg)?;
    let infrastructure = InfrastructurePlugins::from_config(&config).await?;
    let db = infrastructure
        .db()
        .context("Avernet database plugin is unavailable")?;
    let instance_id = outbox_instance_id(args.instance_id.as_deref());
    let workspace_object_store = build_workspace_object_store(
        &config,
        matches!(args.mode, WorkspaceCoreMode::DesktopLocal),
    )
    .await?;
    let plan_dispatcher = Arc::new(
        HttpWorkspacePlanDispatchPort::new(
            args.plan_dispatch_url,
            args.provider_webhook_token.clone(),
            Duration::from_secs_f64(args.plan_dispatch_timeout_seconds),
        )
        .map_err(anyhow::Error::msg)?,
    );
    let outbox_task = match args.mode {
        WorkspaceCoreMode::Cloud => {
            if !matches!(infrastructure.cache_kind(), CachePluginKind::Redis) {
                bail!("Cloud Workspace Core requires the Avernet Redis cache plugin");
            }
            let publisher = RedisWorkspaceEventPublisher::connect(
                &config.cache.redis.to_runtime_redis_config(),
            )
            .await?;
            let dispatcher = WorkspaceOutboxDispatcher::new(
                Arc::clone(&db),
                publisher,
                WorkspaceOutboxConfig {
                    lease_owner: instance_id.clone(),
                    ..WorkspaceOutboxConfig::default()
                },
            )?;
            Some(tokio::spawn(async move { dispatcher.run().await }))
        }
        WorkspaceCoreMode::DesktopLocal => {
            tracing::info!("Workspace Redis outbox delivery is disabled in Desktop Local mode");
            None
        }
    };
    let agent_registry = Arc::new(HttpAgentRegistryPort::new(
        args.agent_registry_url.clone(),
        args.agent_registry_token.clone(),
        Duration::from_secs_f64(args.agent_registry_timeout_seconds),
    )?);
    let provider_registry = Arc::new(HttpProviderRegistryPort::new(
        args.agent_registry_url.clone(),
        args.agent_registry_token.clone(),
        Duration::from_secs_f64(args.agent_registry_timeout_seconds),
    )?);
    let context_judge = Arc::new(HttpWorkspaceContextJudgePort::new(
        args.agent_registry_url.clone(),
        args.agent_registry_token.clone(),
        Duration::from_secs_f64(args.agent_registry_timeout_seconds),
    )?);
    let plan_judge = Arc::new(HttpWorkspacePlanJudgePort::new(
        args.agent_registry_url.clone(),
        args.agent_registry_token.clone(),
        Duration::from_secs_f64(args.agent_registry_timeout_seconds),
    )?);
    let autonomy_judge = Arc::new(HttpWorkspaceAutonomyJudgePort::new(
        args.agent_registry_url,
        args.agent_registry_token,
        Duration::from_secs_f64(args.agent_registry_timeout_seconds),
    )?);
    let sql_flavor = match args.mode {
        WorkspaceCoreMode::Cloud => bcs_db_api::DbSqlFlavor::Postgres,
        WorkspaceCoreMode::DesktopLocal => bcs_db_api::DbSqlFlavor::Sqlite,
    };
    let workspace_state = Arc::new(
        WorkspaceCoreState::new_with_all_authorities(
            Arc::clone(&db),
            args.service_token.clone(),
            sql_flavor,
            agent_registry,
            provider_registry,
            context_judge,
            autonomy_judge,
        )
        .map_err(anyhow::Error::msg)?
        .with_authority(match args.mode {
            WorkspaceCoreMode::Cloud => WorkspaceCoreAuthority::Cloud,
            WorkspaceCoreMode::DesktopLocal => WorkspaceCoreAuthority::Local,
        })
        .with_object_store(workspace_object_store),
    );
    let router_state = Arc::clone(&workspace_state);
    let plan_state = Arc::new(
        PlanHttpState::new(Arc::clone(&db), args.service_token, sql_flavor, plan_judge)
            .map_err(anyhow::Error::msg)?,
    );
    let message_runtime_config = WorkspaceMessageRuntimeConfig {
        webhook_url: args.provider_webhook_url.clone(),
        webhook_token: args.provider_webhook_token.clone(),
        callback_timeout_ms: args.provider_callback_timeout_ms,
    };
    message_runtime_config
        .validate()
        .map_err(anyhow::Error::msg)?;
    let message_runtime = Arc::new(OnceLock::<Arc<WorkspaceMessageRuntime>>::new());
    let services_message_runtime = Arc::clone(&message_runtime);
    let router_message_runtime = Arc::clone(&message_runtime);
    let task_runtime_config = WorkspaceTaskRuntimeConfig {
        webhook_url: args.provider_webhook_url,
        webhook_token: args.provider_webhook_token,
        callback_timeout_ms: args.provider_callback_timeout_ms,
    };
    task_runtime_config.validate().map_err(anyhow::Error::msg)?;
    let task_runtime = Arc::new(OnceLock::<Arc<WorkspaceTaskRuntime>>::new());
    let services_task_runtime = Arc::clone(&task_runtime);
    let services_db = Arc::clone(&db);
    let provider_event_token = args.provider_event_token;
    let provider_callback_timeout_ms = args.provider_callback_timeout_ms;
    let extensions = BcsServerExtensions {
        services_transform: Some(Arc::new(move |mut services| {
            services_message_runtime.get_or_init(|| {
                #[allow(
                    clippy::expect_used,
                    reason = "startup validated the only constructor invariant before this closure"
                )]
                let runtime = WorkspaceMessageRuntime::with_internal_provider_transport(
                    Arc::clone(&services.bot_run_context),
                    message_runtime_config.clone(),
                )
                .expect("Workspace Provider configuration was validated before BCS startup");
                Arc::new(runtime)
            });
            services_task_runtime.get_or_init(|| {
                #[allow(
                    clippy::expect_used,
                    reason = "startup validated the only constructor invariant before this closure"
                )]
                let runtime = WorkspaceTaskRuntime::with_internal_provider_transport(
                    Arc::clone(&services.bot_run_context),
                    task_runtime_config.clone(),
                )
                .expect("Workspace Task Provider configuration was validated before BCS startup");
                Arc::new(runtime)
            });
            let fallback = Arc::clone(&services.provider_bot_events);
            #[allow(
                clippy::expect_used,
                reason = "startup validated the only constructor invariant before this closure"
            )]
            let provider_events = WorkspaceProviderBotEventService::new(
                fallback,
                provider_event_token.clone(),
                Arc::clone(&services.bot_run_context),
                Arc::clone(&services.message_flow),
                Arc::clone(&services_db),
                sql_flavor,
                provider_callback_timeout_ms,
            )
            .expect("Workspace Provider credentials were validated before BCS startup");
            services.provider_bot_events = Arc::new(provider_events);
            services
        })),
        http_router_factory: Some(Arc::new(move |_bcs_state| {
            #[allow(
                clippy::expect_used,
                reason = "the service transform initializes the runtime before router construction"
            )]
            let message_runtime = router_message_runtime
                .get()
                .expect("Workspace message runtime must exist before router construction");
            workspace_router_with_message_runtime(
                Arc::clone(&router_state),
                Arc::clone(message_runtime),
            )
            .merge(plan_routes(Arc::clone(&plan_state)))
        })),
        gateway_principal_signing_key: principal_signing_key
            .as_ref()
            .map(|value| value.to_string()),
        group_session_ws_signing_key: group_session_ws_signing_key
            .as_ref()
            .map(|value| value.to_string()),
        ..BcsServerExtensions::default()
    };

    set_health_version(HEALTH_VERSION);
    tracing::info!(version = HEALTH_VERSION, "starting MemStack Workspace Core");
    let server = BcsServer::new_with_infrastructure(config, infrastructure, extensions).await?;
    if matches!(args.mode, WorkspaceCoreMode::DesktopLocal) {
        memstack_workspace_core::desktop_schema::run_desktop_workspace_schema_migrations(
            db.as_ref(),
        )
        .await
        .context("initialize Desktop Workspace extension schema")?;
        let (legacy_import_path, legacy_import_sha256) = desktop_legacy_import
            .as_ref()
            .context("Desktop legacy Workspace import contract is unavailable")?;
        memstack_workspace_core::desktop_legacy_import::import_legacy_workspace_snapshot(
            db.as_ref(),
            legacy_import_path,
            legacy_import_sha256,
        )
        .await
        .context("import legacy Desktop Workspace authority")?;
    }
    drop(principal_signing_key);
    drop(group_session_ws_signing_key);
    let runtime = message_runtime
        .get()
        .cloned()
        .context("Workspace message runtime was not initialized")?;
    let task_runtime = task_runtime
        .get()
        .cloned()
        .context("Workspace Task runtime was not initialized")?;
    let delivery_worker = WorkspaceMessageDeliveryWorker::new(
        Arc::clone(&db),
        sql_flavor,
        runtime,
        WorkspaceMessageDeliveryWorkerConfig {
            worker_id: format!("workspace-message-delivery:{instance_id}"),
            ..WorkspaceMessageDeliveryWorkerConfig::default()
        },
    )?;
    let delivery_task = tokio::spawn(async move { delivery_worker.run().await });
    let task_dispatch_worker = WorkspaceTaskDispatchWorker::new(
        Arc::clone(&db),
        sql_flavor,
        task_runtime,
        WorkspaceTaskDispatchWorkerConfig {
            worker_id: format!("workspace-task-dispatch:{instance_id}"),
            ..WorkspaceTaskDispatchWorkerConfig::default()
        },
    )?;
    let task_dispatch_task = tokio::spawn(async move { task_dispatch_worker.run().await });
    let plan_delivery_worker =
        memstack_workspace_core::plan_delivery_worker::WorkspacePlanDeliveryWorker::new(
            Arc::clone(&db),
            sql_flavor,
            plan_dispatcher,
            memstack_workspace_core::plan_delivery_worker::WorkspacePlanDeliveryWorkerConfig {
                worker_id: format!("workspace-plan-delivery:{instance_id}"),
                ..memstack_workspace_core::plan_delivery_worker::WorkspacePlanDeliveryWorkerConfig::default()
            },
        )?;
    let plan_delivery_task = tokio::spawn(async move { plan_delivery_worker.run().await });
    let server_result: Result<()> = if let Some(control) = desktop_control.as_mut() {
        let api_base_url = desktop_api_base_url
            .as_deref()
            .context("Desktop API base URL was not initialized")?;
        let shutdown_token = CancellationToken::new();
        let server_shutdown = shutdown_token.clone();
        let mut server_task = tokio::spawn(server.run_with_shutdown(async move {
            server_shutdown.cancelled().await;
        }));
        let (readiness, server_finished) = tokio::select! {
            result = &mut server_task => {
                let result = match result {
                    Ok(Ok(())) => Err(anyhow::anyhow!("Workspace Core exited before Desktop readiness")),
                    Ok(Err(error)) => Err(anyhow::Error::new(error).context("Workspace Core failed before Desktop readiness")),
                    Err(error) => Err(anyhow::Error::new(error).context("Workspace Core task failed before Desktop readiness")),
                };
                (result, true)
            }
            result = control.wait_until_healthy(api_base_url) => (result, false),
        };
        if let Err(error) = readiness {
            if server_finished {
                Err(error)
            } else {
                shutdown_token.cancel();
                let shutdown_result = finish_desktop_server_shutdown(&mut server_task).await;
                match shutdown_result {
                    Ok(()) => Err(error),
                    Err(shutdown_error) => Err(error.context(format!(
                        "Workspace Core also failed graceful shutdown: {shutdown_error:#}"
                    ))),
                }
            }
        } else {
            match control.emit_ready(api_base_url).await {
                Ok(()) => tokio::select! {
                    result = &mut server_task => {
                        match result {
                            Ok(Ok(())) => Err(anyhow::anyhow!("Workspace Core exited before Desktop shutdown")),
                            Ok(Err(error)) => Err(anyhow::Error::new(error).context("Workspace Core failed during Desktop supervision")),
                            Err(error) => Err(anyhow::Error::new(error).context("Workspace Core task failed during Desktop supervision")),
                        }
                    }
                    shutdown = control.wait_for_shutdown() => {
                        shutdown_token.cancel();
                        let shutdown_result = finish_desktop_server_shutdown(&mut server_task).await;
                        match (shutdown, shutdown_result) {
                            (Ok(()), result) => result,
                            (Err(error), Ok(())) => Err(error),
                            (Err(error), Err(shutdown_error)) => Err(error.context(format!(
                                "Workspace Core also failed graceful shutdown: {shutdown_error:#}"
                            ))),
                        }
                    }
                },
                Err(error) => {
                    shutdown_token.cancel();
                    let shutdown_result = finish_desktop_server_shutdown(&mut server_task).await;
                    match shutdown_result {
                        Ok(()) => Err(error),
                        Err(shutdown_error) => Err(error.context(format!(
                            "Workspace Core also failed graceful shutdown: {shutdown_error:#}"
                        ))),
                    }
                }
            }
        }
    } else {
        server.run().await.map_err(anyhow::Error::new)
    };
    delivery_task.abort();
    let _ = delivery_task.await;
    task_dispatch_task.abort();
    let _ = task_dispatch_task.await;
    plan_delivery_task.abort();
    let _ = plan_delivery_task.await;
    if let Some(task) = outbox_task {
        task.abort();
        let _ = task.await;
    }
    server_result?;
    Ok(())
}

async fn finish_desktop_server_shutdown(
    server_task: &mut tokio::task::JoinHandle<bcs::Result<()>>,
) -> Result<()> {
    match tokio::time::timeout(DESKTOP_GRACEFUL_SHUTDOWN_TIMEOUT, &mut *server_task).await {
        Ok(Ok(result)) => result.map_err(anyhow::Error::new),
        Ok(Err(error)) => {
            Err(anyhow::Error::new(error).context("Workspace Core shutdown task failed"))
        }
        Err(_) => {
            server_task.abort();
            let _ = server_task.await;
            bail!("Workspace Core graceful shutdown exceeded 30 seconds")
        }
    }
}

fn require_distinct_credentials(credentials: &[(&str, &str)]) -> Result<()> {
    for (index, (left_name, left_value)) in credentials.iter().enumerate() {
        if left_value.trim().is_empty() {
            bail!("{left_name} credential must not be blank");
        }
        for (right_name, right_value) in credentials.iter().skip(index + 1) {
            if left_value == right_value {
                bail!("{left_name} and {right_name} credentials must be distinct");
            }
        }
    }
    Ok(())
}

fn outbox_instance_id(explicit: Option<&str>) -> String {
    explicit
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| {
            let hostname = std::env::var("HOSTNAME").unwrap_or_else(|_| "localhost".to_string());
            format!("{hostname}:{}", std::process::id())
        })
}
