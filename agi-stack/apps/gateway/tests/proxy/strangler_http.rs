use super::*;

#[path = "strangler_http/admin_dlq.rs"]
mod admin_dlq;
#[path = "strangler_http/agent_commands.rs"]
mod agent_commands;
#[path = "strangler_http/artifacts.rs"]
mod artifacts;
#[path = "strangler_http/attachments.rs"]
mod attachments;
#[path = "strangler_http/audit.rs"]
mod audit;
#[path = "strangler_http/base.rs"]
mod base;
#[path = "strangler_http/billing.rs"]
mod billing;
#[path = "strangler_http/channel.rs"]
mod channel;
#[path = "strangler_http/cron.rs"]
mod cron;
#[path = "strangler_http/data.rs"]
mod data;
#[path = "strangler_http/deploy.rs"]
mod deploy;
#[path = "strangler_http/engines.rs"]
mod engines;
#[path = "strangler_http/events.rs"]
mod events;
#[path = "strangler_http/genes.rs"]
mod genes;
#[path = "strangler_http/graph.rs"]
mod graph;
#[path = "strangler_http/graph_stores.rs"]
mod graph_stores;
#[path = "strangler_http/identity.rs"]
mod identity;
#[path = "strangler_http/instances.rs"]
mod instances;
#[path = "strangler_http/llm_providers.rs"]
mod llm_providers;
#[path = "strangler_http/maintenance.rs"]
mod maintenance;
#[path = "strangler_http/notifications.rs"]
mod notifications;
#[path = "strangler_http/projects_sandbox.rs"]
mod projects_sandbox;
#[path = "strangler_http/retrieval_stores.rs"]
mod retrieval_stores;
#[path = "strangler_http/schema.rs"]
mod schema;
#[path = "strangler_http/skill_evolution.rs"]
mod skill_evolution;
#[path = "strangler_http/subagents.rs"]
mod subagents;
#[path = "strangler_http/support.rs"]
mod support;
#[path = "strangler_http/system.rs"]
mod system;
#[path = "strangler_http/tenant_webhooks.rs"]
mod tenant_webhooks;

pub(super) struct StranglerHttpContext {
    pub(super) gateway_url: String,
    pub(super) http: reqwest::Client,
    pub(super) bearer: &'static str,
}

impl StranglerHttpContext {
    async fn new() -> Self {
        let rust_mock = Router::new()
            .route("/api/v1/agent/ws", get(ws_echo))
            .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
            .with_state("rust");
        let python_mock = Router::new()
            .route("/api/v1/redirect", get(redirect))
            .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
            .with_state("python");

        let rust_url = spawn(rust_mock).await;
        let python_url = spawn(python_mock).await;
        let gateway_url = spawn(app(gateway_state(Upstreams {
            rust: rust_url,
            python: python_url,
        })))
        .await;

        Self {
            gateway_url,
            http: client(),
            bearer: "Bearer ms_sk_e2e_testkey",
        }
    }

    pub(super) fn url(&self, path: &str) -> String {
        format!("{}{}", self.gateway_url, path)
    }

    pub(super) fn request(&self, method: &str, path: &str, body: &str) -> reqwest::RequestBuilder {
        match method {
            "GET" => self.http.get(self.url(path)),
            "POST" => self.http.post(self.url(path)).body(body.to_string()),
            "PUT" => self.http.put(self.url(path)).body(body.to_string()),
            "PATCH" => self.http.patch(self.url(path)).body(body.to_string()),
            "DELETE" => self.http.delete(self.url(path)),
            _ => unreachable!("unsupported test method {method}"),
        }
    }

    pub(super) fn authed(&self, request: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        request.header("authorization", self.bearer)
    }

    pub(super) async fn body(&self, request: reqwest::RequestBuilder) -> String {
        request
            .send()
            .await
            .expect("gateway proxy request should complete")
            .text()
            .await
            .expect("gateway proxy response body should be readable")
    }

    pub(super) async fn authed_body(&self, method: &str, path: &str, body: &str) -> String {
        self.body(self.authed(self.request(method, path, body)))
            .await
    }

    pub(super) async fn public_body(&self, method: &str, path: &str, body: &str) -> String {
        self.body(self.request(method, path, body)).await
    }
}

pub(super) fn assert_backend(body: &str, backend: &str, context: &str) {
    assert!(
        body.contains(&format!("\"backend\":\"{backend}\"")),
        "{context}: {body}"
    );
}

#[tokio::test]
async fn gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough() {
    let ctx = StranglerHttpContext::new().await;

    agent_commands::assert_agent_command_routing(&ctx).await;
    admin_dlq::assert_admin_dlq_routing(&ctx).await;
    artifacts::assert_artifact_routing(&ctx).await;
    attachments::assert_attachment_routing(&ctx).await;
    base::assert_base_routing(&ctx).await;
    audit::assert_audit_routing(&ctx).await;
    billing::assert_billing_routing(&ctx).await;
    channel::assert_channel_routing(&ctx).await;
    cron::assert_cron_routing(&ctx).await;
    data::assert_data_routing(&ctx).await;
    deploy::assert_deploy_routing(&ctx).await;
    engines::assert_engine_routing(&ctx).await;
    events::assert_events_routing(&ctx).await;
    genes::assert_gene_routing(&ctx).await;
    identity::assert_identity_and_shares_routing(&ctx).await;
    instances::assert_instance_routing(&ctx).await;
    graph::assert_graph_routing(&ctx).await;
    graph_stores::assert_graph_store_routing(&ctx).await;
    llm_providers::assert_llm_provider_routing(&ctx).await;
    maintenance::assert_maintenance_routing(&ctx).await;
    notifications::assert_notification_routing(&ctx).await;
    projects_sandbox::assert_project_and_sandbox_routing(&ctx).await;
    retrieval_stores::assert_retrieval_store_routing(&ctx).await;
    schema::assert_schema_routing(&ctx).await;
    skill_evolution::assert_skill_evolution_routing(&ctx).await;
    subagents::assert_subagent_routing(&ctx).await;
    support::assert_support_routing(&ctx).await;
    system::assert_system_routing(&ctx).await;
    tenant_webhooks::assert_tenant_webhook_routing(&ctx).await;
}
