//! The close owner outlives an aborted caller future, like the native route generation guard.
use agistack_plugin_host::protocol_v2::wasm_runtime::WasmOperationV2;
use std::{ops::Deref, sync::Arc};

#[must_use]
pub(in crate::local_runtime) struct OperationReleaseGuardV2 {
    operation: Arc<WasmOperationV2>,
    _release: tokio::sync::oneshot::Sender<()>,
}
impl OperationReleaseGuardV2 {
    pub(in crate::local_runtime) fn new(operation: WasmOperationV2) -> Self {
        let operation = Arc::new(operation);
        let owner = operation.clone();
        let (release, ready) = tokio::sync::oneshot::channel();
        tokio::spawn(async move {
            let _ = ready.await;
            if let Err(error) = owner.close().await {
                tracing::error!(
                    error_code = error.code(),
                    "Local plugin operation lease release failed"
                );
            }
        });
        Self {
            operation,
            _release: release,
        }
    }
}
impl Deref for OperationReleaseGuardV2 {
    type Target = Arc<WasmOperationV2>;
    fn deref(&self) -> &Self::Target {
        &self.operation
    }
}
