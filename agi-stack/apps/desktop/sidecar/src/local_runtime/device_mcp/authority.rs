//! The device's current trusted Cloud account owns its local MCP configuration.
use super::*;
use crate::trusted_session::{TrustedSessionRuntimeMode, TrustedSessionSnapshot};
use sha2::{Digest, Sha256};

pub(in crate::local_runtime) struct CloudOwner {
    broker: TrustedSessionBroker,
    snapshot: TrustedSessionSnapshot,
    installation: String,
    pub(in crate::local_runtime) user_id: String,
    pub(in crate::local_runtime) tenant: String,
    pub(in crate::local_runtime) project: String,
    pub(in crate::local_runtime) scope: McpScope,
    pub(in crate::local_runtime) token: String,
    pub(in crate::local_runtime) manager: bool,
}

fn digest(value: &Value) -> String {
    format!("{:x}", Sha256::digest(value.to_string().as_bytes()))
}

fn identifier(value: &str) -> Result<(), String> {
    if value.is_empty() || value.len() > 200 || value.chars().any(char::is_control) {
        Err("device_mcp_scope_invalid".into())
    } else {
        Ok(())
    }
}

fn normalized_base(value: &str) -> Result<String, String> {
    let value = value.trim_end_matches('/');
    let value = value.strip_suffix("/api/v1").unwrap_or(value);
    let url = url::Url::parse(value).map_err(|_| "device_mcp_cloud_origin_invalid")?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("device_mcp_cloud_origin_invalid".into());
    }
    Ok(url.to_string().trim_end_matches('/').to_owned())
}

fn cloud_base(snapshot: &TrustedSessionSnapshot) -> Result<String, String> {
    let record = snapshot
        .record
        .as_ref()
        .ok_or("device_mcp_trusted_cloud_required")?;
    if record.runtime_mode != TrustedSessionRuntimeMode::Cloud {
        return Err("device_mcp_trusted_cloud_required".into());
    }
    if let Some(expires) = &record.expires_at {
        let expires = chrono::DateTime::parse_from_rfc3339(expires)
            .map_err(|_| "device_mcp_trusted_cloud_required")?;
        if expires <= chrono::Utc::now() {
            return Err("device_mcp_trusted_cloud_required".into());
        }
    }
    normalized_base(&record.api_base_url)
}

/// A structural namespace, never a server id or an authorization supplied by JavaScript.
fn scope(base: &str, user: &str, tenant: &str, project: &str, device: &str) -> McpScope {
    McpScope {
        tenant_id: format!(
            "device-cloud-{}",
            digest(&json!([base, user, tenant, device]))
        ),
        project_id: format!(
            "device-project-{}",
            digest(&json!([base, user, tenant, project, device]))
        ),
    }
}

pub(in crate::local_runtime) fn claim_scope(
    broker: &TrustedSessionBroker,
    epoch: u64,
    user: &str,
    tenant: &str,
    project: &str,
    device: &str,
) -> Result<McpScope, String> {
    for value in [user, tenant, project, device] {
        identifier(value)?;
    }
    broker
        .with_snapshot(|snapshot| {
            if snapshot.epoch != epoch {
                return Err("device_mcp_context_changed".into());
            }
            Ok(scope(
                &cloud_base(&snapshot)?,
                user,
                tenant,
                project,
                device,
            ))
        })
        .map_err(|_| "device_mcp_trusted_cloud_required")?
}

async fn read_json(client: &reqwest::Client, url: &str, credential: &str) -> Result<Value, String> {
    let mut response = client
        .get(url)
        .bearer_auth(credential)
        .send()
        .await
        .map_err(|_| "device_mcp_cloud_authority_unavailable")?
        .error_for_status()
        .map_err(|_| "device_mcp_cloud_authority_rejected")?;
    let mut body = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "device_mcp_cloud_authority_invalid")?
    {
        if body.len().saturating_add(chunk.len()) > 64 * 1024 {
            return Err("device_mcp_cloud_authority_invalid".into());
        }
        body.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&body).map_err(|_| "device_mcp_cloud_authority_invalid".into())
}

impl CloudOwner {
    pub(in crate::local_runtime) async fn resolve(
        broker: &TrustedSessionBroker,
        installation: &str,
        tenant: &str,
        project: &str,
    ) -> Result<Self, String> {
        let snapshot = broker
            .snapshot()
            .map_err(|_| "device_mcp_trusted_cloud_required")?;
        Self::resolve_in_snapshot(broker, installation, tenant, project, snapshot).await
    }

    pub(in crate::local_runtime) async fn resolve_for_plugin(
        broker: &TrustedSessionBroker,
        installation: &str,
        tenant: &str,
        project: &str,
    ) -> Result<Self, String> {
        let snapshot = broker
            .snapshot()
            .map_err(|_| "device_plugin_session_required")?;
        crate::plugin_data_plane_credential_v2::validate_base_url_v2(&cloud_base(&snapshot)?)
            .map_err(|_| "device_plugin_tls_required")?;
        Self::resolve_in_snapshot(broker, installation, tenant, project, snapshot).await
    }

    /// Authenticate the caller against the current vault epoch before any cloud request.
    pub(in crate::local_runtime) async fn resolve_project_http(
        broker: &TrustedSessionBroker,
        installation: &str,
        project: &str,
        bearer: &str,
    ) -> Result<Option<Self>, String> {
        let snapshot = broker
            .snapshot()
            .map_err(|_| "device_plugin_session_required")?;
        let Some(record) = snapshot.record.as_ref() else {
            return Ok(None);
        };
        if record.runtime_mode != TrustedSessionRuntimeMode::Cloud
            || !crate::local_runtime::workspace_core_bridge::secret_matches(
                &record.credential,
                bearer,
            )
        {
            return Ok(None);
        }
        let base = cloud_base(&snapshot)?;
        crate::plugin_data_plane_credential_v2::validate_base_url_v2(&base)
            .map_err(|_| "device_plugin_tls_required")?;
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| "device_mcp_cloud_authority_unavailable")?;
        let context = read_json(
            &client,
            &format!("{base}/api/v1/workspace-context"),
            &record.credential,
        )
        .await?;
        if context["context"]["project_id"] != project {
            return Err("device_mcp_scope_mismatch".into());
        }
        let tenant = context["context"]["tenant_id"]
            .as_str()
            .ok_or("device_mcp_cloud_authority_invalid")?;
        Self::resolve_in_snapshot(broker, installation, tenant, project, snapshot)
            .await
            .map(Some)
    }

    async fn resolve_in_snapshot(
        broker: &TrustedSessionBroker,
        installation: &str,
        tenant: &str,
        project: &str,
        snapshot: TrustedSessionSnapshot,
    ) -> Result<Self, String> {
        for value in [tenant, project, installation] {
            identifier(value)?;
        }
        let base = cloud_base(&snapshot)?;
        let record = snapshot
            .record
            .as_ref()
            .ok_or("device_mcp_trusted_cloud_required")?;
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(15))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| "device_mcp_cloud_authority_unavailable")?;
        let me = read_json(
            &client,
            &format!("{base}/api/v1/auth/me"),
            &record.credential,
        )
        .await?;
        let user = me
            .get("user_id")
            .or_else(|| me.get("id"))
            .and_then(Value::as_str)
            .ok_or("device_mcp_cloud_authority_invalid")?;
        identifier(user)?;
        let mut project_url = url::Url::parse(&format!("{base}/api/v1/projects/"))
            .map_err(|_| "device_mcp_cloud_origin_invalid")?;
        project_url
            .path_segments_mut()
            .map_err(|_| "device_mcp_cloud_origin_invalid")?
            .pop_if_empty()
            .push(project);
        let project_view = read_json(&client, project_url.as_str(), &record.credential).await?;
        if project_view["id"] != project || project_view["tenant_id"] != tenant {
            return Err("device_mcp_scope_mismatch".into());
        }
        // Read the selected context last, after membership and identity checks.
        let context = read_json(
            &client,
            &format!("{base}/api/v1/workspace-context"),
            &record.credential,
        )
        .await?;
        if context["context"]["tenant_id"] != tenant || context["context"]["project_id"] != project
        {
            return Err("device_mcp_scope_mismatch".into());
        }
        let revision = context["context"]["revision"]
            .as_u64()
            .ok_or("device_mcp_cloud_authority_invalid")?;
        let role = context["membership_role"]
            .as_str()
            .ok_or("device_mcp_cloud_authority_invalid")?;
        let scope = scope(&base, user, tenant, project, installation);
        let token = digest(&json!([
            scope.tenant_id,
            scope.project_id,
            snapshot.epoch,
            revision,
            role
        ]));
        let user_id = user.to_owned();
        let owner = Self {
            user_id,
            broker: broker.clone(),
            snapshot,
            installation: installation.into(),
            tenant: tenant.into(),
            project: project.into(),
            scope,
            token,
            manager: matches!(role, "owner" | "admin"),
        };
        owner.fence(|| Ok(()))?;
        Ok(owner)
    }

    pub(in crate::local_runtime) fn fence<T>(
        &self,
        action: impl FnOnce() -> Result<T, String>,
    ) -> Result<T, String> {
        self.broker
            .with_snapshot(|snapshot| {
                if snapshot != self.snapshot {
                    return Err("device_mcp_context_changed".into());
                }
                cloud_base(&snapshot)?;
                action()
            })
            .map_err(|_| "device_mcp_context_changed")?
    }

    pub(in crate::local_runtime) async fn recheck(&self) -> Result<(), String> {
        self.fence(|| Ok(()))?;
        let current = Self::resolve_in_snapshot(
            &self.broker,
            &self.installation,
            &self.tenant,
            &self.project,
            self.snapshot.clone(),
        )
        .await?;
        if current.token != self.token {
            return Err("device_mcp_context_changed".into());
        }
        self.fence(|| Ok(()))
    }

    /// Private P4 admission for the exact conversation selected by this cloud project.
    pub(in crate::local_runtime) async fn local_run_session(
        &self,
        conversation: &str,
    ) -> Result<(String, String), String> {
        self.fence(|| Ok(()))?;
        let base = cloud_base(&self.snapshot)?;
        let record = self
            .snapshot
            .record
            .as_ref()
            .ok_or("device_plugin_session_required")?;
        let mut url = url::Url::parse(&format!("{base}/api/v1/agent/conversations/"))
            .map_err(|_| "device_plugin_origin_invalid")?;
        url.path_segments_mut()
            .map_err(|_| "device_plugin_origin_invalid")?
            .pop_if_empty()
            .push(conversation);
        url.query_pairs_mut()
            .append_pair("project_id", &self.project);
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(std::time::Duration::from_secs(12))
            .build()
            .map_err(|_| "device_plugin_transport_unavailable")?;
        let view = read_json(&client, url.as_str(), &record.credential).await?;
        if view["id"] != conversation
            || view["project_id"] != self.project
            || view["tenant_id"] != self.tenant
            || view["execution_target"] != "local"
        {
            return Err("device_local_conversation_scope_mismatch".into());
        }
        self.fence(|| Ok((base, format!("Bearer {}", record.credential))))
    }

    pub(in crate::local_runtime) fn plugin_grant_request(
        &self,
        method: reqwest::Method,
        suffix: &str,
    ) -> Result<reqwest::RequestBuilder, String> {
        self.fence(|| Ok(()))?;
        let base = cloud_base(&self.snapshot)?;
        crate::plugin_data_plane_credential_v2::validate_base_url_v2(&base)
            .map_err(|_| "device_plugin_tls_required")?;
        let record = self
            .snapshot
            .record
            .as_ref()
            .ok_or("device_plugin_session_required")?;
        let mut url = url::Url::parse(&format!("{base}/api/v1/projects/"))
            .map_err(|_| "device_plugin_origin_invalid")?;
        url.path_segments_mut()
            .map_err(|_| "device_plugin_origin_invalid")?
            .pop_if_empty()
            .push(&self.project)
            .push("device-plugin-grants")
            .push(suffix);
        let client = reqwest::Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(std::time::Duration::from_secs(12))
            .build()
            .map_err(|_| "device_plugin_transport_unavailable")?;
        Ok(client.request(method, url).bearer_auth(&record.credential))
    }

    pub(super) fn response(&self, result: Value) -> Value {
        json!({"context":{"tenant_id":self.tenant,"project_id":self.project,
            "location":"device","token":self.token},"result":result})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalized_cloud_address_and_all_principals_bind_the_private_scope() {
        let base = normalized_base("https://EXAMPLE.com:443/api/v1/").unwrap();
        assert_eq!(base, "https://example.com");
        let expected = scope(&base, "u", "t", "p", "d");
        for candidate in [
            scope("https://other.example", "u", "t", "p", "d"),
            scope(&base, "other", "t", "p", "d"),
            scope(&base, "u", "other", "p", "d"),
            scope(&base, "u", "t", "other", "d"),
            scope(&base, "u", "t", "p", "other"),
        ] {
            assert_ne!(expected, candidate);
        }
        for bad in [
            "file:///tmp/config",
            "https://u:p@example.com",
            "https://example.com?key=x",
            "https://example.com#x",
        ] {
            assert!(normalized_base(bad).is_err());
        }
    }
}
