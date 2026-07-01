//! Standalone `uniffi-bindgen` CLI so we can generate Swift/Kotlin in library
//! mode: `cargo run --bin uniffi-bindgen -- generate --library <dylib> ...`.
fn main() {
    uniffi::uniffi_bindgen_main()
}
