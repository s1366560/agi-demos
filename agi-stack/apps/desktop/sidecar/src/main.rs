//! MemStack desktop local-runtime sidecar.

mod application_vault;
mod control;
mod data_migration;
mod local_runtime;
mod native_host;
mod oauth_pending_attempt;
mod private_file_permissions;
mod trusted_session;
mod update_recovery;
mod update_recovery_snapshot;
mod workspace_core_cutover;
mod workspace_core_helper;
mod workspace_core_legacy_import;

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_writer(std::io::stderr)
        .without_time()
        .init();

    if matches!(
        std::env::args().nth(1).as_deref(),
        Some("--update-recovery-prepare" | "--update-recovery-helper")
    ) {
        if let Err(error) = update_recovery::run_from_environment() {
            tracing::error!(error = %error, "update recovery helper failed");
            std::process::exit(2);
        }
        return;
    }

    let runtime = match tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            tracing::error!(error = %error, "failed to initialize sidecar runtime");
            std::process::exit(1);
        }
    };
    let result = runtime.block_on(async {
        match std::env::args().nth(1).as_deref() {
            // Chrome native messaging manifests cannot carry arguments: Chrome
            // launches the host with the extension origin as argv[1] instead.
            Some("--native-host") => native_host::run().await,
            Some(arg) if arg.starts_with("chrome-extension://") => native_host::run().await,
            _ => control::run().await,
        }
    });
    if let Err(error) = result {
        tracing::error!(error = %error, "desktop sidecar stopped");
        std::process::exit(1);
    }
}
