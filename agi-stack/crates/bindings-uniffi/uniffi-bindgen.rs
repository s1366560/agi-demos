//! Standalone `uniffi-bindgen` CLI so Swift/Kotlin can be generated in library
//! mode: `cargo run --bin uniffi-bindgen -- generate --library <dylib> ...`.
fn main() {
    uniffi::uniffi_bindgen_main()
}
