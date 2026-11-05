//! Browser selection uses explicit configuration and identities, never URL semantics.
use agistack_core::ports::CoreResult;
use serde_json::Value;

use crate::host::tool_err;

/// Resolve an explicit identity or the configured default from the live inventory.
/// A URL describes the caller's intended destination; it does not grant navigation
/// or authorize heuristics about which account or profile is appropriate.
pub fn select_browser(inventory: &Value, default: &str, options: &Value) -> CoreResult<Value> {
    let options = options
        .as_object()
        .ok_or_else(|| tool_err("browser selection must be an object"))?;
    if options
        .keys()
        .any(|key| !matches!(key.as_str(), "id" | "extensionInstanceId" | "url"))
    {
        return Err(tool_err("unknown browser selection field"));
    }
    if let Some(url) = options.get("url") {
        url.as_str()
            .and_then(|url| url::Url::parse(url).ok())
            .ok_or_else(|| tool_err("browser selection requires an absolute URL"))?;
    }
    let string = |field: &str| -> CoreResult<Option<&str>> {
        options
            .get(field)
            .map(|value| {
                value
                    .as_str()
                    .filter(|value| !value.is_empty())
                    .ok_or_else(|| tool_err(format!("invalid browser selection {field}")))
            })
            .transpose()
    };
    let id = string("id")?;
    let instance = string("extensionInstanceId")?;
    if id.is_some() && instance.is_some() {
        return Err(tool_err("specify either id or extensionInstanceId"));
    }
    let browsers = inventory
        .as_array()
        .ok_or_else(|| tool_err("invalid browser inventory"))?;
    let selector = id.unwrap_or(default);
    let matches: Vec<_> = browsers
        .iter()
        .filter(|browser| {
            if let Some(instance) = instance {
                browser
                    .pointer("/metadata/extensionInstanceId")
                    .and_then(Value::as_str)
                    == Some(instance)
            } else {
                browser["id"].as_str() == Some(selector)
                    || browser
                        .pointer("/metadata/stableId")
                        .and_then(Value::as_str)
                        == Some(selector)
                    || browser["family"]
                        .as_str()
                        .or_else(|| browser["type"].as_str())
                        == Some(selector)
            }
        })
        .collect();
    match matches.as_slice() {
        [browser] => Ok((*browser).clone()),
        [] => Err(tool_err("browser_selection_unavailable: the selected browser is offline")),
        _ => Err(tool_err(serde_json::json!({"error":"browser_selection_required",
            "message":"Select an exact browser identity in a structured tool call", "candidates":matches}).to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn configured_default_does_not_depend_on_destination_words() {
        let inventory = json!([{"id":"iab:live","family":"iab","metadata":{"stableId":"iab"}},
            {"id":"chrome:live","family":"chrome","metadata":{"stableId":"chrome:profile"}}]);
        for url in [
            "https://mail.example.test",
            "https://accounts.example.test",
            "about:blank",
        ] {
            assert_eq!(
                select_browser(&inventory, "iab", &json!({"url":url})).unwrap()["id"],
                "iab:live"
            );
        }
        assert_eq!(
            select_browser(&inventory, "chrome:profile", &json!({})).unwrap()["id"],
            "chrome:live"
        );
        assert!(select_browser(&inventory, "edge", &json!({})).is_err());
    }

    #[test]
    fn exact_profile_and_extension_selection_never_guess_between_instances() {
        let inventory = json!([{"id":"one","family":"chrome","metadata":{"stableId":"chrome:profile","extensionInstanceId":"worker1"}},
            {"id":"two","family":"chrome","metadata":{"stableId":"chrome:other","extensionInstanceId":"worker2"}}]);
        assert_eq!(
            select_browser(&inventory, "iab", &json!({"id":"chrome:profile"})).unwrap()["id"],
            "one"
        );
        assert_eq!(
            select_browser(&inventory, "iab", &json!({"extensionInstanceId":"worker2"})).unwrap()
                ["id"],
            "two"
        );
        let error = select_browser(&inventory, "chrome", &json!({}))
            .unwrap_err()
            .to_string();
        assert!(error.contains("browser_selection_required"));
        for options in [
            json!({"id":"one","extensionInstanceId":"worker1"}),
            json!({"url":"example.test"}),
            json!({"id":null}),
            json!({"default":"one"}),
        ] {
            assert!(select_browser(&inventory, "iab", &options).is_err());
        }
    }
}
