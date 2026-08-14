use serde_json::{Map, Value};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) struct InvalidSubAgentProjectScope;

pub(super) fn normalize_project_scope(
    object: &mut Map<String, Value>,
    active_project_id: &str,
) -> Result<(), InvalidSubAgentProjectScope> {
    match object.get("project_id") {
        None | Some(Value::Null) => {
            object.insert("project_id".to_string(), Value::Null);
            Ok(())
        }
        Some(Value::String(project_id)) if project_id == active_project_id => Ok(()),
        Some(_) => Err(InvalidSubAgentProjectScope),
    }
}

pub(super) fn is_visible_in_project(resource: &Value, active_project_id: &str) -> bool {
    let Some(object) = resource.as_object() else {
        return false;
    };
    match object.get("project_id") {
        None | Some(Value::Null) => true,
        Some(Value::String(project_id)) => project_id == active_project_id,
        Some(_) => false,
    }
}
