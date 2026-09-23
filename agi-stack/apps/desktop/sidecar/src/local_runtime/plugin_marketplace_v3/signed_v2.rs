//! Read the signed authority without copying its install or signature-verification lifecycle.
use super::*;

pub(super) async fn records(
    state: Arc<LocalRuntimeState>,
    auth: AuthenticatedContext,
) -> PackageResult<Vec<Value>> {
    let Json(value) = super::super::local_plugin_routes_v2::marketplace_installations(state, auth)
        .await
        .map_err(|(_, Json(value))| {
            value["detail"]
                .as_str()
                .unwrap_or("signed authority unavailable")
                .to_owned()
        })?;
    Ok(value["installations"]
        .as_array()
        .into_iter()
        .flatten()
        .map(project)
        .collect())
}
fn project(value: &Value) -> Value {
    let reference = &value["reference"];
    let id = reference["bundle_id"].as_str().unwrap_or_default();
    let status = match value["activation_status"].as_str() {
        Some("active") => "enabled",
        Some("inactive") => "disabled",
        Some("failed") => "failed",
        _ => "downloaded",
    };
    json!({
        "id":format!("signed-v2:{id}"),"plugin_id":id,"name":id,
        "description":"", "publisher":"", "category":"", "source_id":"signed-v2",
        "source":reference["source"],"format":"v2","version":reference["version"],
        "capabilities":[],"targets":["desktop"],"permissions":value["approved_permissions"],
        "compatible":true,"reasons":[],"status":status,"error":value["activation_error"],
        "install_strategy":"signed-v2","reference":reference,
        "authorization_status":value["authorization_status"],"required_credentials":[]
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn signed_projection_keeps_reference_permissions_and_activation_authority() {
        let mut value = json!({"reference":{"bundle_id":"signed-example","version":"2.0.0","digest":"sha256:trusted","source":"registry"},"approved_permissions":["filesystem:read"],"activation_status":"active","authorization_status":"approved"});
        let projected = project(&value);
        assert_eq!(projected["reference"], value["reference"]);
        assert_eq!(projected["status"], "enabled");
        assert_eq!(projected["install_strategy"], "signed-v2");
        assert_eq!(projected["permissions"], value["approved_permissions"]);
        assert_eq!(projected["compatible"], true);
        value["activation_status"] = json!("failed");
        value["activation_error"] = json!("signature check failed");
        assert_eq!(project(&value)["status"], "failed");
        assert_eq!(project(&value)["error"], "signature check failed");
    }
}
