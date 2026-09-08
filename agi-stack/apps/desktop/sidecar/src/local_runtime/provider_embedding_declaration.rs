//! Explicit provider configuration supplies an embedding role; model names never do.

use super::{provider_probe_request_error, provider_supports_route_model, Value};

pub(super) fn apply(
    provider: &mut Value,
    declaration: Option<String>,
) -> Result<(), (axum::http::StatusCode, axum::Json<Value>)> {
    if let Some(value) = declaration {
        let model = value.trim();
        if model.len() > 256 || model.chars().any(char::is_control) {
            return Err(provider_probe_request_error(
                "invalid embedding model identifier",
            ));
        }
        provider["embedding_model"] = if model.is_empty() {
            Value::Null
        } else {
            Value::String(model.to_owned())
        };
    }
    match provider.get("embedding_model") {
        None | Some(Value::Null) => Ok(()),
        Some(Value::String(model))
            if !model.is_empty() && provider_supports_route_model(provider, model) =>
        {
            Ok(())
        }
        _ => Err(provider_probe_request_error(
            "embedding model must be a configured primary or allowed model",
        )),
    }
}

pub(super) fn model(provider: &Value) -> Option<&str> {
    let declared = provider.get("embedding_model")?.as_str()?;
    (!declared.is_empty() && provider_supports_route_model(provider, declared)).then_some(declared)
}
