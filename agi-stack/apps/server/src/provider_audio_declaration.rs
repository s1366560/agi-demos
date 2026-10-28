//! Explicit audio input capabilities shared by server environment and provider configuration.
use serde_json::{json, Value};
use std::collections::BTreeSet;

fn identifiers(values: &[String]) -> Result<BTreeSet<String>, &'static str> {
    if values.len() > 2_000
        || values.iter().any(|model| {
            model.trim().is_empty()
                || model.trim() == "*"
                || model.len() > 256
                || model.chars().any(char::is_control)
        })
    {
        return Err("invalid audio input model identifiers");
    }
    Ok(values.iter().map(|model| model.trim().to_owned()).collect())
}

pub(crate) fn parse(value: Option<&str>) -> Result<BTreeSet<String>, &'static str> {
    let Some(value) = value else {
        return Ok(BTreeSet::new());
    };
    let values: Vec<String> = serde_json::from_str(value)
        .map_err(|_| "audio_input_models must be an array of exact model identifiers")?;
    identifiers(&values)
}

pub(crate) fn stored(config: &Value) -> BTreeSet<String> {
    config
        .get("audio_input_models")
        .and_then(|value| serde_json::from_value::<Vec<String>>(value.clone()).ok())
        .and_then(|values| identifiers(&values).ok())
        .unwrap_or_default()
}

pub(crate) fn apply(
    config: &mut Value,
    declaration: Option<Vec<String>>,
    provider: &str,
    operation: &str,
    primary: Option<&str>,
    allowed: &[String],
    blocked: &[String],
) -> Result<(), &'static str> {
    let explicitly_configured = declaration.is_some() || config.get("audio_input_models").is_some();
    let values = match declaration {
        Some(values) => values,
        None => config
            .get("audio_input_models")
            .map(|value| {
                serde_json::from_value::<Vec<String>>(value.clone())
                    .map_err(|_| "audio_input_models must be an array of exact model identifiers")
            })
            .transpose()?
            .unwrap_or_default(),
    };
    let models = identifiers(&values)?;
    if !models.is_empty()
        && (!matches!(provider, "openai" | "openai_compatible") || operation != "llm")
    {
        return Err("audio input requires the OpenAI chat-completions protocol");
    }
    if models.iter().any(|model| {
        (primary != Some(model.as_str()) && !allowed.contains(model)) || blocked.contains(model)
    }) {
        return Err("audio input models must be configured primary or allowed models");
    }
    if explicitly_configured {
        config
            .as_object_mut()
            .ok_or("provider config must be an object")?
            .insert("audio_input_models".into(), json!(models));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn declaration_defaults_closed_and_never_infers_model_names_or_patterns() {
        assert!(parse(None).unwrap().is_empty());
        let models = parse(Some(r#"["opaque-model", "opaque-model"]"#)).unwrap();
        assert_eq!(models.len(), 1);
        assert!(models.contains("opaque-model"));
        assert!(!models.contains("opaque-model-other"));
        assert!(!models.contains("gpt-4o-audio-preview"));
        for invalid in ["*", r#"["*"]"#, r#"[1]"#, r#"[""]"#, r#"["a\nb"]"#, "null"] {
            assert!(parse(Some(invalid)).is_err());
        }
    }

    #[test]
    fn provider_updates_revalidate_protocol_primary_roster_and_blocked_models() {
        let mut config = json!({});
        apply(
            &mut config,
            Some(vec!["audio".into()]),
            "openai",
            "llm",
            Some("audio"),
            &[],
            &[],
        )
        .unwrap();
        assert_eq!(stored(&config), BTreeSet::from(["audio".to_owned()]));
        assert!(apply(
            &mut config,
            None,
            "anthropic",
            "llm",
            Some("audio"),
            &[],
            &[]
        )
        .is_err());
        assert!(apply(
            &mut config,
            None,
            "openai",
            "embedding",
            Some("audio"),
            &[],
            &[]
        )
        .is_err());
        assert!(apply(&mut config, None, "openai", "llm", Some("other"), &[], &[]).is_err());
        assert!(apply(
            &mut config,
            None,
            "openai",
            "llm",
            Some("other"),
            &["audio".into()],
            &["audio".into()]
        )
        .is_err());
        apply(
            &mut config,
            None,
            "openai_compatible",
            "llm",
            Some("other"),
            &["audio".into()],
            &[],
        )
        .unwrap();
        apply(
            &mut config,
            Some(vec![]),
            "anthropic",
            "llm",
            Some("other"),
            &[],
            &[],
        )
        .unwrap();
        assert!(stored(&config).is_empty());
    }
}
