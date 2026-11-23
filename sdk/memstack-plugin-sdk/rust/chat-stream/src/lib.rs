//! Structured stream options shared by independently released model adapters.
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub provider: String,
    pub token_limit: u32,
    pub has_tools: bool,
}

#[derive(Serialize)]
pub struct Options {
    pub token_limit: u32,
    pub publish_reasoning: bool,
}

/// Run a JSON adapter against the SDK's two reserved Wasm pages.
///
/// # Safety
/// Only call this with the signed host's initialized object at address zero and a
/// linker configuration that reserves both ABI pages for this invocation.
#[cfg(target_arch = "wasm32")]
pub unsafe fn invoke(length: u32, provider: &str, adapt: fn(Request) -> Options) -> u32 {
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
    let Ok(request) = serde_json::from_slice::<Request>(&input) else {
        return 0;
    };
    if request.provider != provider {
        return 0;
    }
    let Ok(output) = serde_json::to_vec(&adapt(request)) else {
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
