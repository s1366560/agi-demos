//! Chat stream policy for deepseek.
use memstack_chat_stream_sdk::{Options, Request};

fn adapt(request: Request) -> Options {
    let cap = if request.has_tools { 4096 } else { 2048 };
    Options {
        token_limit: request.token_limit.min(cap),
        publish_reasoning: true,
    }
}

#[cfg(target_arch = "wasm32")]
#[no_mangle]
pub extern "C" fn invoke(length: u32) -> u32 {
    // SAFETY: the SDK host writes the request into the pages reserved by build.rs.
    unsafe { memstack_chat_stream_sdk::invoke(length, "deepseek", adapt) }
}
