//! Bounded provider diagnostics; never return arbitrary response bodies or credentials.
use serde_json::Value;

pub(super) const MAX_ERROR_BYTES: usize = 4096;

pub(super) fn detail(value: &Value, credential: Option<&str>) -> Option<String> {
    let error = value.get("error").filter(|value| !value.is_null())?;
    let code = error.get("code").and_then(Value::as_str).filter(|code| {
        !code.is_empty()
            && code.len() <= 128
            && code
                .chars()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.'))
    });
    let message = error
        .get("message")
        .and_then(Value::as_str)
        .filter(|message| {
            message.len() <= MAX_ERROR_BYTES
                && !message.contains("data:audio/")
                && !message.contains("data:image/")
        });
    let mut parts = Vec::new();
    if let Some(code) = code {
        parts.push(code.to_owned());
    }
    if let Some(message) = message {
        parts.push(message.to_owned());
    }
    let mut detail = if parts.is_empty() {
        "provider_error".into()
    } else {
        parts.join(": ")
    };
    if let Some(credential) = credential.filter(|value| !value.is_empty()) {
        detail = detail.replace(credential, "[credential withheld]");
    }
    Some(
        detail
            .chars()
            .take(512)
            .map(|c| if c.is_control() { ' ' } else { c })
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn diagnostics_redact_before_truncating_and_ignore_null_error_envelopes() {
        let key = "owned-fixture-credential";
        let value = json!({"error":{"message":format!("{}{key}", "x".repeat(500))}});
        let message = detail(&value, Some(key)).unwrap();
        assert!(!message.contains("owned-fixture"));
        assert!(message.chars().count() <= 512);
        assert_eq!(detail(&json!({"error":null,"choices":[]}), Some(key)), None);
    }
}
