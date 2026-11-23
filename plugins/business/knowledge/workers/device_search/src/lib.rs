//! Literal, case-insensitive search over the documents supplied with this request.
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    query: String,
    documents: Vec<Document>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Document {
    id: String,
    text: String,
}

fn contains_query(line: &str, lowercase_query: &str) -> bool {
    if !line.is_ascii() {
        return line.to_lowercase().contains(lowercase_query);
    }
    let query = lowercase_query.as_bytes();
    let first = query[0]; // Empty queries are rejected before scanning documents.
    let bytes = line.as_bytes();
    memchr::memchr2_iter(first, first.to_ascii_uppercase(), bytes).any(|index| {
        bytes
            .get(index..index + query.len())
            .is_some_and(|candidate| candidate.eq_ignore_ascii_case(query))
    })
}

fn search(input: &[u8]) -> Value {
    let Ok(request) = serde_json::from_slice::<Request>(input) else {
        return json!({"error":"query_and_documents_required"});
    };
    let query = request.query.trim().to_lowercase();
    if query.is_empty() {
        return json!({"error":"empty_query"});
    }
    let hits: Vec<_> = request.documents.iter().filter_map(|document| {
        let (index, line) = document.text.lines().enumerate()
            .find(|(_, line)| contains_query(line, &query))?;
        Some(json!({"id":document.id, "line": index + 1, "excerpt":line.chars().take(160).collect::<String>()}))
    }).take(20).collect();
    json!({"hits":hits})
}

#[cfg(target_arch = "wasm32")]
#[no_mangle]
pub extern "C" fn invoke(length: u32) -> u32 {
    // The host serializes a JSON object starting at offset 0. Read its remaining UTF-8
    // bytes from the external input area. No Rust pointer dereferences address zero.
    if !(2..=65_536).contains(&length) {
        return 0;
    }
    let mut request = Vec::with_capacity(length as usize);
    request.push(b'{');
    // SAFETY: build.rs reserves the entire first page for the copying host. At
    // entry it contains exactly `length` initialized bytes and the guest has no
    // live references to it. Start at 1 because Rust slices require a nonnull pointer.
    let rest = unsafe { std::slice::from_raw_parts(1_usize as *const u8, length as usize - 1) };
    request.extend_from_slice(rest);
    let response = serde_json::to_vec(&search(&request)).expect("JSON value is serializable");
    if response.len() > 65_536 {
        return 0;
    }
    for (offset, byte) in response.iter().copied().enumerate() {
        // SAFETY: the next 64 KiB belong to the host output region for this invocation.
        unsafe { std::ptr::write_volatile((65_536 + offset) as *mut u8, byte) };
    }
    response.len() as u32
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn returns_the_first_matching_line_per_document_in_input_order() {
        let request = json!({"query":"DEVICE", "documents":[{"id":"readme","text":"First line\nDevice grants"},
            {"id":"other","text":"offline"},{"id":"手册","text":"device scope"}]});
        let hits = search(&serde_json::to_vec(&request).unwrap());
        assert_eq!(
            hits["hits"],
            json!([{"id":"readme","line":2,"excerpt":"Device grants"},{"id":"手册","line":1,"excerpt":"device scope"}])
        );
    }
}
