use std::env;

fn main() {
    if env::var("TARGET").as_deref() == Ok("wasm32-unknown-unknown") {
        // The signed invoke ABI exclusively owns pages 0 (input) and 1 (output).
        // Place every guest data segment above them, followed by the stack and heap.
        println!("cargo:rustc-link-arg=--no-stack-first");
        println!("cargo:rustc-link-arg=--global-base=131072");
    }
}
