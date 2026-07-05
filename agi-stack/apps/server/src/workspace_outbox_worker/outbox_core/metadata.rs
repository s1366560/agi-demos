use super::*;

pub(in crate::workspace_outbox_worker) fn merge_metadata_patch(
    target: &mut Map<String, Value>,
    patch: &Map<String, Value>,
) {
    for (key, value) in patch {
        target.insert(key.clone(), value.clone());
    }
}
