//! Trusted, in-process example tools (the `Trust::Builtin` path) plus a native
//! [`ToolFactory`] so the enable/disable lifecycle can be exercised without any
//! WASM dependency. Untrusted/sandboxed tools live behind the `ToolHost` /
//! `WasmTool` path in `memstack-adapters-wasmi`.

use std::sync::Arc;

use async_trait::async_trait;
use memstack_core::ports::{CoreError, CoreResult};

use crate::host::ToolFactory;
use crate::manifest::ToolDecl;
use crate::tool::{Tool, Trust};

/// A trusted built-in: returns the character length of `input.text`.
pub struct LenTool;

#[async_trait]
impl Tool for LenTool {
    fn name(&self) -> &str {
        "len"
    }
    fn version(&self) -> &str {
        "1.0.0"
    }
    fn trust(&self) -> Trust {
        Trust::Builtin
    }
    async fn invoke(&self, input_json: &str) -> CoreResult<String> {
        let v: serde_json::Value =
            serde_json::from_str(input_json).map_err(|e| CoreError::Tool(e.to_string()))?;
        let text = v.get("text").and_then(|t| t.as_str()).unwrap_or("");
        Ok(serde_json::json!({ "tool": "len", "len": text.chars().count() }).to_string())
    }
}

/// A trusted built-in built from a manifest declaration: echoes its input back,
/// tagged with the tool name/version. Stands in for any native capability.
pub struct EchoTool {
    name: String,
    version: String,
}

impl EchoTool {
    pub fn new(name: impl Into<String>, version: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            version: version.into(),
        }
    }
}

#[async_trait]
impl Tool for EchoTool {
    fn name(&self) -> &str {
        &self.name
    }
    fn version(&self) -> &str {
        &self.version
    }
    fn trust(&self) -> Trust {
        Trust::Builtin
    }
    async fn invoke(&self, input_json: &str) -> CoreResult<String> {
        Ok(serde_json::json!({ "tool": self.name, "echo": input_json }).to_string())
    }
}

/// A [`ToolFactory`] that builds trusted native [`EchoTool`]s from a manifest.
/// Useful for testing the lifecycle without a WASM runtime; a real deployment
/// would dispatch on `decl.trust` to a WASM factory for untrusted tools.
pub struct NativeToolFactory;

impl ToolFactory for NativeToolFactory {
    fn build(&self, decl: &ToolDecl) -> CoreResult<Arc<dyn Tool>> {
        Ok(Arc::new(EchoTool::new(decl.name.clone(), decl.version.clone())))
    }
}
