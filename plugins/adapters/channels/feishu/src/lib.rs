//! Format the status and position of an agent task for a Feishu timeline message.
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum Event {
    TaskStart,
    TaskComplete,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Progress {
    event: Event,
    status: String,
    order_index: u32,
    total_tasks: u32,
}

fn render(input: &[u8]) -> Option<Vec<u8>> {
    let data: Progress = serde_json::from_slice(input).ok()?;
    let (icon, label) = match (data.event, data.status.as_str()) {
        (Event::TaskStart, _) => ("\u{1f504}", "Starting".to_owned()),
        (Event::TaskComplete, "completed") => ("\u{2705}", "Completed".to_owned()),
        (Event::TaskComplete, "failed") => ("\u{274c}", "Failed".to_owned()),
        (Event::TaskComplete, status) => {
            let mut chars = status.chars();
            let first = chars.next().map(char::to_uppercase).into_iter().flatten();
            let tail = chars.flat_map(char::to_lowercase);
            ("\u{274c}", first.chain(tail).collect())
        }
    };
    let position = u64::from(data.order_index) + 1;
    let prefix = format!("{icon} ({position}/{}) **{label}:** ", data.total_tasks);
    serde_json::to_vec(&json!({"prefix": prefix})).ok()
}

#[cfg(target_arch = "wasm32")]
#[no_mangle]
pub extern "C" fn invoke(length: u32) -> u32 {
    if !(2..=65_536).contains(&length) {
        return 0;
    }
    let mut input = Vec::with_capacity(length as usize);
    // The structured ABI always supplies an object. Rust cannot borrow address zero.
    input.push(b'{');
    // SAFETY: build.rs reserves page zero for the host's initialized request.
    let tail = unsafe {
        std::slice::from_raw_parts(std::ptr::without_provenance::<u8>(1), length as usize - 1)
    };
    input.extend_from_slice(tail);
    let Some(output) = render(&input) else {
        return 0;
    };
    if output.len() > 65_536 {
        return 0;
    }
    // SAFETY: page one is the ABI response buffer, disjoint from the guest-owned output.
    unsafe {
        std::ptr::copy_nonoverlapping(
            output.as_ptr(),
            std::ptr::without_provenance_mut::<u8>(65_536),
            output.len(),
        )
    };
    output.len() as u32
}

#[cfg(test)]
mod tests {
    use super::render;
    use serde_json::{json, Value};

    #[test]
    fn formats_protocol_state_without_receiving_message_content() {
        let data =
            json!({"event":"task_complete", "status":"failed", "order_index":2,"total_tasks":5});
        let bytes = render(data.to_string().as_bytes()).unwrap();
        let output: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(output, json!({"prefix":"\u{274c} (3/5) **Failed:** "}));
        let mut invalid = data;
        invalid["content"] = json!("unrelated text");
        assert!(render(invalid.to_string().as_bytes()).is_none());
    }
}
