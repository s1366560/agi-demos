//! MemStack desktop local-runtime sidecar.

mod application_vault;
mod control;
mod data_migration;
mod local_runtime;
mod trusted_session;

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .with_writer(std::io::stderr)
        .without_time()
        .init();

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
    if let Err(error) = runtime.block_on(control::run()) {
        tracing::error!(error = %error, "desktop sidecar stopped");
        std::process::exit(1);
    }
}
