//! Plugin-host PoC for the spike's **extensibility axis**.
//!
//! Demonstrates `ToolHost` (a hexagonal port) backed by the pure-Rust `wasmi`
//! interpreter. The point of this slice is NOT speed — it is *portability of the
//! plugin host itself*:
//!
//!   - `wasmi` compiles to every target the core does, **including wasm32**, so
//!     the same untrusted third-party tool (`.wasm`) can be hosted on the
//!     server, desktop, mobile, AND inside the browser build (wasm-in-wasm).
//!   - On server/desktop you would swap this adapter for a Wasmtime-backed one
//!     for JIT speed + fuel/epoch quotas; iOS (no JIT) keeps wasmi/wasmer.
//!     Because the host sits behind the `ToolHost` port, that swap never touches
//!     the core — exactly like the storage/LLM ports.
//!
//! The sandboxed "tool" here is a tiny WAT module (a relevance scorer). It
//! stands in for any untrusted plugin: it runs with no ambient authority, only
//! the numeric capability the host explicitly wires up.

use async_trait::async_trait;
use wasmi::{Engine, Linker, Module, Store};

use memstack_core::ports::{CoreError, CoreResult, ToolHost};

/// A minimal untrusted "tool", shipped as inline WAT and compiled to wasm at
/// construction time. `score(len) = len * 3 + 7`. Numeric in/out keeps the PoC
/// free of linear-memory string marshaling so it stays focused on the host port.
const SCORE_WAT: &str = r#"
(module
  (func (export "score") (param i32) (result i32)
    local.get 0
    i32.const 3
    i32.mul
    i32.const 7
    i32.add))
"#;

/// Universal-portable [`ToolHost`] over the `wasmi` interpreter.
pub struct WasmiToolHost {
    engine: Engine,
    module: Module,
}

impl WasmiToolHost {
    /// Compile the bundled sandboxed tool. In a real system the wasm bytes would
    /// come from a plugin registry / MCP package instead of inline WAT.
    pub fn new() -> CoreResult<Self> {
        let engine = Engine::default();
        let wasm = wat::parse_str(SCORE_WAT).map_err(|e| CoreError::Tool(e.to_string()))?;
        let module = Module::new(&engine, &wasm[..]).map_err(|e| CoreError::Tool(e.to_string()))?;
        Ok(Self { engine, module })
    }
}

#[async_trait]
impl ToolHost for WasmiToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["score".to_string()]
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if tool != "score" {
            return Err(CoreError::Tool(format!("unknown tool: {tool}")));
        }
        let v: serde_json::Value =
            serde_json::from_str(input_json).map_err(|e| CoreError::Tool(e.to_string()))?;
        let len = v.get("len").and_then(|x| x.as_i64()).unwrap_or(0) as i32;

        // Fresh, isolated instance per call: no shared mutable state between
        // invocations, mirroring how an untrusted plugin should be sandboxed.
        let mut store = Store::new(&self.engine, ());
        let linker = <Linker<()>>::new(&self.engine);
        let instance = linker
            .instantiate_and_start(&mut store, &self.module)
            .map_err(|e| CoreError::Tool(e.to_string()))?;
        let score = instance
            .get_typed_func::<i32, i32>(&store, "score")
            .map_err(|e| CoreError::Tool(e.to_string()))?;
        let out = score
            .call(&mut store, len)
            .map_err(|e| CoreError::Tool(e.to_string()))?;

        Ok(serde_json::json!({ "tool": "score", "input_len": len, "score": out }).to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hosts_sandboxed_wasm_tool() {
        let host = WasmiToolHost::new().expect("compile sandboxed tool");
        assert_eq!(host.list_tools(), vec!["score".to_string()]);

        // 10 * 3 + 7 = 37, computed *inside* the wasm sandbox.
        let out = futures::executor::block_on(host.call("score", r#"{"len": 10}"#))
            .expect("invoke sandboxed tool");
        assert!(out.contains("\"score\":37"), "unexpected output: {out}");
    }

    #[test]
    fn rejects_unknown_tool() {
        let host = WasmiToolHost::new().unwrap();
        let err = futures::executor::block_on(host.call("definitely_not_a_tool", "{}"));
        assert!(matches!(err, Err(CoreError::Tool(_))));
    }
}
