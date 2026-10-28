//! The device's current trusted Cloud account owns its local MCP configuration.
use super::*;
use crate::trusted_session::{TrustedSessionRuntimeMode, TrustedSessionSnapshot};
use sha2::{Digest, Sha256};

pub(super) struct CloudOwner {
    broker: TrustedSessionBroker,
    snapshot: TrustedSessionSnapshot,
    installation: String,
    pub(super) tenant: String,
    pub(super) project: String,
    pub(super) scope: McpScope,
    pub(super) token: String,
    pub(super) manager: bool,
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
    pub(super) async fn resolve(
        broker: &TrustedSessionBroker,
        installation: &str,
        tenant: &str,
        project: &str,
    ) -> Result<Self, String> {
        for value in [tenant, project, installation] {
            identifier(value)?;
        }
        let snapshot = broker
            .snapshot()
            .map_err(|_| "device_mcp_trusted_cloud_required")?;
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
        let owner = Self {
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

    pub(super) fn fence<T>(&self, action: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
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

    pub(super) async fn recheck(&self) -> Result<(), String> {
        self.fence(|| Ok(()))?;
        let current = Self::resolve(
            &self.broker,
            &self.installation,
            &self.tenant,
            &self.project,
        )
        .await?;
        if current.token != self.token {
            return Err("device_mcp_context_changed".into());
        }
        self.fence(|| Ok(()))
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
