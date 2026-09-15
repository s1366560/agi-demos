//! Explicit presentation metadata never replaces the model's raw instruction.
use serde::{Deserialize, Deserializer};
use serde_json::Value;

pub(super) fn parse(value: Option<&Value>) -> Result<Option<String>, &'static str> {
    match value {
        None => Ok(None),
        Some(Value::String(text)) if !text.trim().is_empty() && text.len() <= 65_536 => {
            Ok(Some(text.clone()))
        }
        Some(_) => Err("display_content must be non-empty text of at most 65536 UTF-8 bytes"),
    }
}

pub(super) fn deserialize<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let value = Value::deserialize(deserializer)?;
    parse(Some(&value)).map_err(serde::de::Error::custom)
}
