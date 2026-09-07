use std::sync::Arc;

use agistack_core::ports::CoreResult;
use agistack_plugin_host::{
    permission_binding::observe_permission_binding, HotPlugRegistry, Tool, ToolAccessClass, Trust,
};
use async_trait::async_trait;
use serde_json::json;

struct Mutation(&'static str);

#[async_trait]
impl Tool for Mutation {
    fn name(&self) -> &str {
        "write"
    }
    fn version(&self) -> &str {
        self.0
    }
    fn trust(&self) -> Trust {
        Trust::Builtin
    }
    fn access_class(&self) -> ToolAccessClass {
        ToolAccessClass::Mutating
    }
    async fn invoke(&self, _: &str) -> CoreResult<String> {
        panic!("binding must never invoke a tool")
    }
}

#[test]
fn observes_host_identity_and_canonical_input_without_execution() {
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(Mutation("1.0")));
    let snapshot = registry.snapshot();
    registry.replace_tool(Arc::new(Mutation("2.0")));
    let a = observe_permission_binding(&snapshot, "host-id".into(), "write", &json!({"b":2,"a":1}))
        .unwrap();
    let b = observe_permission_binding(&snapshot, "host-id".into(), "write", &json!({"a":1,"b":2}))
        .unwrap();
    assert_eq!(a, b);
    assert_eq!(a.tool_name(), "write");
    assert_eq!(a.tool_version(), "1.0");
    let new = observe_permission_binding(
        &registry.snapshot(),
        "host-id".into(),
        "write",
        &json!({"a":1,"b":2}),
    )
    .unwrap();
    assert_eq!(new.tool_version(), "2.0");
    let changed =
        observe_permission_binding(&snapshot, "host-id".into(), "write", &json!({"a":1,"b":3}))
            .unwrap();
    assert_ne!(a.input_sha256(), changed.input_sha256());
    assert!(
        observe_permission_binding(&snapshot, "host-id".into(), "missing", &json!({})).is_none()
    );
    assert!(observe_permission_binding(&snapshot, "".into(), "write", &json!({})).is_none());
}
