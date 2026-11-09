//! Bounded AT-SPI traversal. Native roles, interfaces and actions only; no name-based inference.
use atspi::{
    proxy::{accessible::ObjectRefExt, proxy_ext::ProxyExt},
    CoordType, Role,
};
use atspi_connection::AccessibilityConnection;
use serde_json::{json, Value};
use sky_cua_platform::model::{CoordinateSpace, ElementNode, RectF};
use std::collections::BTreeSet;

pub struct Snapshot {
    pub elements: Vec<ElementNode>,
    pub nodes: Vec<Value>,
    pub truncated: bool,
}

fn public_node(node: &ElementNode, protected: bool) -> Value {
    json!({"element_index":node.element_index,"parent_index":node.parent_index,"role":node.role,"name":node.name,"description":node.description,"value":if protected {None}else{node.value.as_ref()},"value_redacted":protected,"states":node.state_flags,"actions":node.semantic_actions,"supports_editable_text":node.supports_editable_text,"bounds":node.bounds})
}

fn bounded(value: Option<String>, budget: &mut usize) -> Option<String> {
    value.map(|value| {
        let limit = (*budget).min(16384);
        let mut end = 0;
        for (index, character) in value.char_indices() {
            let next = index + character.len_utf8();
            if next > limit {
                break;
            }
            end = next;
        }
        *budget -= end;
        value[..end].to_owned()
    })
}

fn bounded_snapshot(
    value: Option<String>,
    budget: &mut usize,
    truncated: &mut bool,
) -> Option<String> {
    let original = value.as_ref().map_or(0, String::len);
    let result = bounded(value, budget);
    *truncated |= result.as_ref().map_or(0, String::len) < original;
    result
}

pub async fn snapshot(
    connection: &AccessibilityConnection,
    root: &atspi::ObjectRefOwned,
) -> Snapshot {
    let mut nodes = Vec::new();
    let mut budget = 256 * 1024;
    let mut public = Vec::new();
    let mut truncated = false;
    let mut seen = BTreeSet::new();
    let mut stack = vec![(root.clone(), None, 0usize)];
    while let Some((reference, parent_index, depth)) = stack.pop() {
        if nodes.len() >= 4096 {
            truncated = true;
            break;
        }
        let Ok(accessible) = reference.as_accessible_proxy(connection.connection()).await else {
            truncated = true;
            continue;
        };
        let native_ref = format!(
            "{}:{}",
            accessible.inner().destination(),
            accessible.inner().path()
        );
        if !seen.insert(native_ref.clone()) {
            continue;
        }
        let role = bounded_snapshot(
            Some(
                accessible
                    .get_role_name()
                    .await
                    .unwrap_or_else(|_| "unknown".into()),
            ),
            &mut budget,
            &mut truncated,
        )
        .unwrap_or_default();
        let native_role = accessible.get_role().await.ok();
        let protected = native_role.is_none_or(|role| role == Role::PasswordText);
        let name = bounded_snapshot(accessible.name().await.ok(), &mut budget, &mut truncated);
        let description = bounded_snapshot(
            accessible.description().await.ok(),
            &mut budget,
            &mut truncated,
        );
        let state_flags = accessible
            .get_state()
            .await
            .map(|states| {
                states
                    .into_iter()
                    .filter_map(|state| {
                        bounded_snapshot(Some(state.to_string()), &mut budget, &mut truncated)
                    })
                    .collect()
            })
            .unwrap_or_default();
        let mut bounds = None;
        let mut value = None;
        let mut native_actions = Vec::new();
        let mut supports_editable_text = false;
        if let Ok(proxies) = accessible.proxies().await {
            supports_editable_text = proxies.editable_text().await.is_ok();
            if let Ok(component) = proxies.component().await {
                bounds = component.get_extents(CoordType::Screen).await.ok().map(
                    |(x, y, width, height)| RectF {
                        x: x as f64,
                        y: y as f64,
                        width: width as f64,
                        height: height as f64,
                        space: CoordinateSpace::DesktopLogical,
                    },
                );
            }
            if let Ok(actions) = proxies.action().await {
                native_actions = actions
                    .get_actions()
                    .await
                    .map(|actions| {
                        actions
                            .into_iter()
                            .take(16)
                            .filter_map(|action| {
                                bounded_snapshot(Some(action.name), &mut budget, &mut truncated)
                            })
                            .collect()
                    })
                    .unwrap_or_default();
            }
            if !protected {
                if let Ok(text) = proxies.text().await {
                    if let Ok(length) = text.character_count().await {
                        value = text.get_text(0, length.clamp(0, 16384)).await.ok();
                    }
                } else if let Ok(number) = proxies.value().await {
                    value = number
                        .current_value()
                        .await
                        .ok()
                        .map(|value| value.to_string());
                }
            }
        }
        let index = nodes.len();
        nodes.push(ElementNode {
            element_index: index,
            parent_index,
            role,
            name,
            description,
            value: bounded_snapshot(value, &mut budget, &mut truncated),
            text: None,
            numeric_value: None,
            supports_editable_text,
            state_flags,
            semantic_actions: native_actions,
            bounds,
            backend_ref: Some(native_ref),
        });
        public.push(public_node(&nodes[index], protected));
        if depth < 64 {
            let children = accessible.get_children().await.unwrap_or_else(|_| {
                truncated = true;
                Vec::new()
            });
            let remaining = 4096usize.saturating_sub(nodes.len() + stack.len());
            truncated |= children.len() > remaining;
            for child in children.into_iter().rev().take(remaining) {
                stack.push((child, Some(index), depth + 1));
            }
        } else if accessible.child_count().await.is_ok_and(|count| count > 0) {
            truncated = true;
        }
    }
    Snapshot {
        elements: nodes,
        nodes: public,
        truncated: truncated || budget == 0,
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn native_snapshot_budget_preserves_utf8_and_bounds_aggregate_bytes() {
        let mut budget = 5;
        assert_eq!(
            super::bounded(Some("中🙂abcdef".into()), &mut budget),
            Some("中".into())
        );
        assert_eq!(budget, 2);
        assert_eq!(
            super::bounded(Some("abcd".into()), &mut budget),
            Some("ab".into())
        );
        assert_eq!(budget, 0);
        assert_eq!(
            super::bounded(Some("overflow".into()), &mut budget),
            Some(String::new())
        );
    }
}

#[cfg(test)]
mod public_tests {
    use super::*;
    #[test]
    fn public_native_node_preserves_actual_parent_and_suppresses_protected_value_and_reference() {
        let node = ElementNode {
            element_index: 2,
            parent_index: Some(1),
            role: "password text".into(),
            name: Some("Native label".into()),
            description: None,
            value: Some("SECRET_NATIVE_FIXTURE".into()),
            text: None,
            numeric_value: None,
            supports_editable_text: true,
            state_flags: vec!["focused".into()],
            semantic_actions: vec!["activate".into()],
            bounds: None,
            backend_ref: Some(":1.12:/org/a11y/native/private".into()),
        };
        let public = public_node(&node, true);
        assert_eq!(public["parent_index"], 1);
        assert_eq!(public["value_redacted"], true);
        assert!(public["value"].is_null());
        assert!(!public.to_string().contains("SECRET_NATIVE_FIXTURE"));
        assert!(!public.to_string().contains("backend_ref"));
        assert!(!public.to_string().contains("/org/a11y"));
        assert_eq!(public["states"], serde_json::json!(["focused"]));
    }
}
