//! Audio input is a per-model operator declaration, never a model-name inference.
use std::collections::BTreeSet;

use super::{provider_probe_request_error, provider_supports_route_model, Value};

pub(super) fn apply(
    provider: &mut Value,
    declaration: Option<Vec<String>>,
) -> Result<(), (axum::http::StatusCode, axum::Json<Value>)> {
    if let Some(models) = declaration {
        if models.len() > 2_000
            || models.iter().any(|model| {
                model.trim().is_empty() || model.len() > 256 || model.chars().any(char::is_control)
            })
        {
            return Err(provider_probe_request_error(
                "invalid audio input model identifiers",
            ));
        }
        provider["audio_input_models"] = serde_json::json!(models
            .into_iter()
            .map(|model| model.trim().to_owned())
            .collect::<BTreeSet<_>>());
    }
    validated_models(provider)
        .map(|_| ())
        .map_err(provider_probe_request_error)
}

pub(super) fn models(provider: &Value) -> BTreeSet<String> {
    validated_models(provider).unwrap_or_default()
}

fn validated_models(provider: &Value) -> Result<BTreeSet<String>, &'static str> {
    let Some(value) = provider.get("audio_input_models") else {
        return Ok(BTreeSet::new());
    };
    let declared = value
        .as_array()
        .ok_or("audio_input_models must be an array")?;
    if declared.is_empty() {
        return Ok(BTreeSet::new());
    }
    if !matches!(
        provider.get("provider_type").and_then(Value::as_str),
        Some("openai" | "openai_compatible")
    ) {
        return Err("audio input requires the OpenAI chat-completions protocol");
    }
    declared
        .iter()
        .map(|value| {
            value
                .as_str()
                .filter(|model| !model.is_empty() && provider_supports_route_model(provider, model))
                .map(str::to_owned)
                .ok_or("audio input models must be configured primary or allowed models")
        })
        .collect()
}
