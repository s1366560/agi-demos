use super::{failure, host::ScoreHost};
use crate::protocol_v2::{
    scope_contains, BundleReferenceV2, GenerationLeaseV2, RuntimeV2Error, ScopeV2,
};
use agistack_core::ports::ToolDefinition;
use async_trait::async_trait;
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};

#[derive(Clone, Debug, PartialEq)]
pub struct WasmToolAttributionV2 {
    pub bundle: BundleReferenceV2,
    pub plugin_id: String,
    pub plugin_version: String,
    pub module_ref: String,
    pub artifact_digest: String,
    pub artifact_source: String,
    pub entry_id: String,
    pub tool_name: String,
    pub entry_scope: ScopeV2,
    pub profile_id: String,
    pub generation: u64,
    pub snapshot_digest: String,
}

/// The application must check current installation, revocation, grants, and scope for every call.
#[async_trait]
pub trait WasmOperationAuthorityV2: Send + Sync {
    async fn authorize(&self, operation: &WasmOperationV2, tool: &WasmToolAttributionV2) -> bool;
}

pub struct WasmOperationV2 {
    lease: Mutex<Option<GenerationLeaseV2>>,
    scope: ScopeV2,
    id: String,
    authority: Option<Arc<dyn WasmOperationAuthorityV2>>,
}

impl WasmOperationV2 {
    /// Ownership of the real generation lease moves into this operation; close after use.
    pub fn new(
        lease: GenerationLeaseV2,
        scope: ScopeV2,
        id: String,
        authority: Option<Arc<dyn WasmOperationAuthorityV2>>,
    ) -> Self {
        Self {
            lease: Mutex::new(Some(lease)),
            scope,
            id,
            authority,
        }
    }
    pub fn scope(&self) -> &ScopeV2 {
        &self.scope
    }
    pub fn id(&self) -> &str {
        &self.id
    }
    pub async fn close(&self) -> Result<(), RuntimeV2Error> {
        let lease = self
            .lease
            .lock()
            .map_err(|_| failure("WASM operation lock unavailable"))?
            .take();
        if let Some(lease) = lease {
            lease.release().await?;
        }
        Ok(())
    }
    fn matches(&self, tool: &WasmToolAttributionV2) -> bool {
        let Ok(lease) = self.lease.lock() else {
            return false;
        };
        let Some(lease) = lease.as_ref() else {
            return false;
        };
        let Ok(generation) = lease.generation() else {
            return false;
        };
        !self.id.is_empty()
            && crate::protocol_v2::validate_scope(&self.id, &self.scope).is_ok()
            && scope_contains(&tool.entry_scope, &self.scope)
            && generation.snapshot.profile_id == tool.profile_id
            && generation.snapshot.generation == tool.generation
            && generation.snapshot.digest == tool.snapshot_digest
    }
}

struct ToolSource {
    host: Arc<ScoreHost>,
    active: Arc<AtomicBool>,
    attribution: WasmToolAttributionV2,
}

pub struct WasmToolSetV2 {
    source: Arc<ToolSource>,
}
impl WasmToolSetV2 {
    pub(super) fn new(
        host: Arc<ScoreHost>,
        active: Arc<AtomicBool>,
        attribution: WasmToolAttributionV2,
    ) -> Self {
        Self {
            source: Arc::new(ToolSource {
                host,
                active,
                attribution,
            }),
        }
    }
    /// No authority means no model-visible tool. The same authority is checked again at invoke.
    pub async fn prepare(&self, operation: &Arc<WasmOperationV2>) -> Vec<AuthorizedWasmToolV2> {
        let Some(authority) = &operation.authority else {
            return vec![];
        };
        if !self.source.active.load(Ordering::Acquire)
            || !operation.matches(&self.source.attribution)
            || !authority
                .authorize(operation, &self.source.attribution)
                .await
            || !operation.matches(&self.source.attribution)
            || !self.source.active.load(Ordering::Acquire)
        {
            return vec![];
        }
        vec![AuthorizedWasmToolV2 {
            source: Arc::clone(&self.source),
            operation: Arc::clone(operation),
        }]
    }
}

pub struct AuthorizedWasmToolV2 {
    source: Arc<ToolSource>,
    operation: Arc<WasmOperationV2>,
}
impl AuthorizedWasmToolV2 {
    pub fn attribution(&self) -> &WasmToolAttributionV2 {
        &self.source.attribution
    }
    pub fn definition(&self) -> ToolDefinition {
        ToolDefinition::new(
            &self.source.attribution.tool_name,
            "Runs an isolated WASM score on the UTF-8 byte length of the input JSON.",
            json!({"type":"object","properties":{"input":{"type":"string","maxLength":65536}},"required":["input"],"additionalProperties":false}),
        )
    }
    pub async fn invoke(&self, input: Value) -> Result<Value, RuntimeV2Error> {
        let valid = || {
            self.source.active.load(Ordering::Acquire)
                && self.operation.matches(&self.source.attribution)
        };
        if !valid() {
            return Err(failure(
                "WASM operation is disposed or does not own this generation",
            ));
        }
        let authority = self
            .operation
            .authority
            .as_ref()
            .ok_or_else(|| failure("WASM operation authority required"))?;
        if !authority
            .authorize(&self.operation, &self.source.attribution)
            .await
            || !valid()
        {
            return Err(failure("WASM operation permission denied"));
        }
        let object = input
            .as_object()
            .ok_or_else(|| failure("WASM input object required"))?;
        let text = object
            .get("input")
            .and_then(Value::as_str)
            .ok_or_else(|| failure("WASM input string required"))?;
        if object.len() != 1 || text.chars().count() > 65536 {
            return Err(failure("WASM input exceeds ABI contract"));
        }
        let encoded = serde_json::to_vec(&json!({"input":text}))
            .map_err(|_| failure("WASM input cannot serialize"))?;
        let count =
            i32::try_from(encoded.len()).map_err(|_| failure("WASM input size overflow"))?;
        let score = self.source.host.invoke(count).await?;
        if !valid() {
            return Err(failure("WASM operation disposed during execution"));
        }
        let output = json!({"score":score,"input_bytes":count});
        if serde_json::to_vec(&output)
            .map_err(|_| failure("WASM output cannot serialize"))?
            .len() as u64
            > self.source.host.output_limit()
        {
            return Err(failure("WASM output quota exceeded"));
        }
        Ok(output)
    }
}
