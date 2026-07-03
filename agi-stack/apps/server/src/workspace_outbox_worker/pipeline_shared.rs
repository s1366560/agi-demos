use super::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct GitCommandOutput {
    pub(super) exit_code: i32,
    pub(super) stdout: String,
    pub(super) stderr: String,
}

pub(super) fn merge_object_values(left: &Value, right: &Value) -> Value {
    let mut merged = object_or_empty(left.clone());
    merged.extend(object_or_empty(right.clone()));
    Value::Object(merged)
}

pub(super) fn source_publish_dotenv_value(token_env: &str) -> Option<String> {
    let path = std::env::var("MEMSTACK_DRONE_DOTENV_PATH").unwrap_or_else(|_| ".env".to_string());
    let content = std::fs::read_to_string(path).ok()?;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        let Some((key, value)) = trimmed.split_once('=') else {
            continue;
        };
        if key.trim() == token_env {
            let value = value.trim().trim_matches('"').trim_matches('\'');
            if !value.is_empty() {
                return Some(value.to_string());
            }
        }
    }
    None
}

pub(super) fn bool_from_map_default(map: &Map<String, Value>, key: &str, default: bool) -> bool {
    map.get(key).and_then(Value::as_bool).unwrap_or(default)
}
