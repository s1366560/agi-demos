//! Fail-closed public API capability declaration for the MemStack gateway.

use axum::Json;
use serde::Serialize;
use sha2::{Digest, Sha256};

use super::ApiError;

const CAPABILITY_PROTOCOL_VERSION: u32 = 1;
const REQUIRED_MANIFEST_VERSION: u32 = 1;
const REQUIRED_CONTRACT_SHA256: &str =
    "a09965a43986fa5c23cc21a4f876b1e94fab475fefe1f9d679e41bf617660768";
const REQUIRED_ROUTE_COUNT: usize = 92;
const REQUIRED_ROUTE_KEYS_SHA256: &str =
    "e4fea0501bbf438e30f55e0937246fda5709fdf4e3b7831c85147c6303bb3f07";

// Public handlers must only be added here after their method/path, response,
// status, error, pagination, authorization, and event golden contracts pass.
const IMPLEMENTED_PUBLIC_ROUTES: &[PublicRouteCapability] = &[
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/authority",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/capabilities",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents/{workspace_agent_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agents/{workspace_agent_id}",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/members/{user_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agent-policy",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/agent-policy",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/llm-providers/routing-policy",
    },
    PublicRouteCapability {
        method: "PUT",
        path: "/api/v1/llm-providers/routing-policy",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspace-context",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspace-context/switch",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/messages/mentions/{target_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes/{gene_id}",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes/{gene_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/genes/{gene_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/tasks",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/assign-agent",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/unassign-agent",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/claim",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/start",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/block",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/complete",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/experience",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/execution-session",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/tasks/{task_id}/recovery-actions",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/plan",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/recover-stale-attempts",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/outbox/{outbox_id}/retry",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/iteration/pause",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/iteration/resume",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/iteration/trigger-next",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/delivery/run-pipeline",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/delivery/regenerate-contract",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/request-replan",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/reopen",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/plan/nodes/{node_id}/accept-review",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/pin",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/unpin",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies/{reply_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/posts/{post_id}/replies/{reply_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/topology/nodes",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/topology/nodes",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/topology/nodes/{node_id}",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/workspaces/{workspace_id}/topology/nodes/{node_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/workspaces/{workspace_id}/topology/nodes/{node_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/topology/edges",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/topology/edges",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/workspaces/{workspace_id}/topology/edges/{edge_id}",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/workspaces/{workspace_id}/topology/edges/{edge_id}",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/workspaces/{workspace_id}/topology/edges/{edge_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/execution-diagnostics",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/mkdir",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/upload",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/{file_id}",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/{file_id}",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/{file_id}/copy",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/{file_id}/download",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/mutations",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/collaboration/mutations/files/upload",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives",
    },
    PublicRouteCapability {
        method: "DELETE",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives/{objective_id}",
    },
    PublicRouteCapability {
        method: "GET",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives/{objective_id}",
    },
    PublicRouteCapability {
        method: "PATCH",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives/{objective_id}",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/objectives/{objective_id}/project-to-task",
    },
    PublicRouteCapability {
        method: "POST",
        path: "/api/v1/workspaces/{workspace_id}/autonomy/tick",
    },
];
const IMPLEMENTED_CONTRACT_SHA256: Option<&str> = Some(REQUIRED_CONTRACT_SHA256);

#[derive(Debug, Serialize)]
pub(super) struct PublicRouteCapability {
    method: &'static str,
    path: &'static str,
}

#[derive(Debug, Serialize)]
pub(super) struct PublicApiCapabilities {
    protocol_version: u32,
    manifest_version: u32,
    required_contract_sha256: &'static str,
    required_route_count: usize,
    required_route_keys_sha256: &'static str,
    implemented_contract_sha256: Option<&'static str>,
    implemented_route_count: usize,
    implemented_route_keys_sha256: String,
    implemented_routes: &'static [PublicRouteCapability],
    complete: bool,
}

pub(super) async fn read_public_api_capabilities() -> Result<Json<PublicApiCapabilities>, ApiError>
{
    Ok(Json(public_api_capabilities()?))
}

fn public_api_capabilities() -> Result<PublicApiCapabilities, ApiError> {
    let implemented_route_keys_sha256 = route_keys_sha256(IMPLEMENTED_PUBLIC_ROUTES)?;
    let complete = IMPLEMENTED_CONTRACT_SHA256 == Some(REQUIRED_CONTRACT_SHA256)
        && IMPLEMENTED_PUBLIC_ROUTES.len() == REQUIRED_ROUTE_COUNT
        && implemented_route_keys_sha256 == REQUIRED_ROUTE_KEYS_SHA256;

    Ok(PublicApiCapabilities {
        protocol_version: CAPABILITY_PROTOCOL_VERSION,
        manifest_version: REQUIRED_MANIFEST_VERSION,
        required_contract_sha256: REQUIRED_CONTRACT_SHA256,
        required_route_count: REQUIRED_ROUTE_COUNT,
        required_route_keys_sha256: REQUIRED_ROUTE_KEYS_SHA256,
        implemented_contract_sha256: IMPLEMENTED_CONTRACT_SHA256,
        implemented_route_count: IMPLEMENTED_PUBLIC_ROUTES.len(),
        implemented_route_keys_sha256,
        implemented_routes: IMPLEMENTED_PUBLIC_ROUTES,
        complete,
    })
}

fn route_keys_sha256(routes: &[PublicRouteCapability]) -> Result<String, ApiError> {
    let mut canonical_routes = routes.iter().collect::<Vec<_>>();
    canonical_routes
        .sort_unstable_by(|left, right| (left.path, left.method).cmp(&(right.path, right.method)));
    let payload = serde_json::to_vec(&canonical_routes).map_err(ApiError::Json)?;
    Ok(hex::encode(Sha256::digest(payload)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn complete_public_surface_claims_the_frozen_contract() -> Result<(), ApiError> {
        let capabilities = public_api_capabilities()?;

        assert_eq!(capabilities.implemented_route_count, REQUIRED_ROUTE_COUNT);
        assert_eq!(
            capabilities.implemented_route_keys_sha256,
            REQUIRED_ROUTE_KEYS_SHA256
        );
        assert_eq!(
            capabilities.implemented_contract_sha256,
            Some(REQUIRED_CONTRACT_SHA256)
        );
        assert!(capabilities.complete);
        Ok(())
    }
}
