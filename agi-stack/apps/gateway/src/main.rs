//! `agistack-gateway` binary — the strangler front door.
//!
//! Config via env:
//!   `AGISTACK_GATEWAY_ADDR`   bind address           (default `127.0.0.1:8080`)
//!   `AGISTACK_RUST_UPSTREAM`  Rust server base URL   (default `http://127.0.0.1:8088`)
//!   `AGISTACK_PYTHON_UPSTREAM` Python backend base URL (default `http://127.0.0.1:8000`)

use agistack_gateway::{app, strangled_rule_summary, GatewayState, Upstreams};

#[tokio::main]
async fn main() {
    let addr =
        std::env::var("AGISTACK_GATEWAY_ADDR").unwrap_or_else(|_| "127.0.0.1:8080".to_string());
    let rust = std::env::var("AGISTACK_RUST_UPSTREAM")
        .unwrap_or_else(|_| "http://127.0.0.1:8088".to_string());
    let python = std::env::var("AGISTACK_PYTHON_UPSTREAM")
        .unwrap_or_else(|_| "http://127.0.0.1:8000".to_string());

    let state = GatewayState::new(Upstreams {
        rust: rust.clone(),
        python: python.clone(),
    });

    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    println!("agistack-gateway listening on http://{addr}");
    println!(
        "  strangled -> Rust   {rust}   ({})",
        strangled_rule_summary()
    );
    println!("  fallback  -> Python {python}");
    axum::serve(listener, app(state)).await.unwrap();
}
