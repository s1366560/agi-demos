use super::{Arc, PermissionSuspensionPort, ReActEngine};

impl ReActEngine {
    pub fn with_permission_suspension(mut self, port: Arc<dyn PermissionSuspensionPort>) -> Self {
        self.permission_suspension = Some(port);
        self
    }

    /// Remove inherited permission authority and its advertised model capability
    /// when composing a restricted host from an existing engine configuration.
    pub fn without_permission_suspension(mut self) -> Self {
        self.permission_suspension = None;
        self
    }
}
