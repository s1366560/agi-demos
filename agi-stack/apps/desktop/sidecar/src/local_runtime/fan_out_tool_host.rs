//! Composite [`ToolHost`] that fans out across several inner hosts.
//!
//! Used to place the browser bridge's [`BrowserToolHost`] next to the local
//! tool host behind a single boundary, so the Plan/Authorized wrappers (and
//! the ReAct engine above them) see one merged tool surface.
//!
//! [`BrowserToolHost`]: agistack_adapters_browser::BrowserToolHost

use std::sync::Arc;

use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;

/// Tools are the ordered union of the inner hosts' advertised tools (first host
/// wins on duplicates); a call dispatches to the first host that explicitly
/// reports it can route the exact identity.
pub(super) struct FanOutToolHost {
    hosts: Vec<Arc<dyn ToolHost>>,
}

impl FanOutToolHost {
    pub(super) fn new(hosts: Vec<Arc<dyn ToolHost>>) -> Self {
        Self { hosts }
    }
}

#[async_trait]
impl ToolHost for FanOutToolHost {
    fn list_tools(&self) -> Vec<String> {
        let mut tools = Vec::new();
        for host in &self.hosts {
            for tool in host.list_tools() {
                if !tools.contains(&tool) {
                    tools.push(tool);
                }
            }
        }
        tools
    }

    fn can_dispatch(&self, tool: &str) -> bool {
        self.hosts.iter().any(|host| host.can_dispatch(tool))
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        for host in &self.hosts {
            if host.can_dispatch(tool) {
                return host.call(tool, input_json).await;
            }
        }
        Err(CoreError::Tool(format!("unknown tool: {tool}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct StubHost {
        tools: Vec<String>,
        prefix: String,
    }

    #[async_trait]
    impl ToolHost for StubHost {
        fn list_tools(&self) -> Vec<String> {
            self.tools.clone()
        }

        fn can_dispatch(&self, tool: &str) -> bool {
            self.tools.iter().any(|name| name == tool) || tool == "legacy_hidden"
        }

        async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
            Ok(format!("{}:{tool}:{input_json}", self.prefix))
        }
    }

    fn stub(prefix: &str, tools: &[&str]) -> Arc<dyn ToolHost> {
        Arc::new(StubHost {
            tools: tools.iter().map(|tool| (*tool).to_string()).collect(),
            prefix: prefix.to_string(),
        })
    }

    #[test]
    fn list_tools_concatenates_and_deduplicates_in_order() {
        let host = FanOutToolHost::new(vec![
            stub("a", &["read", "write", "shared"]),
            stub("b", &["browser_list_tabs", "shared"]),
        ]);
        assert_eq!(
            host.list_tools(),
            ["read", "write", "shared", "browser_list_tabs"]
        );
    }

    #[tokio::test]
    async fn call_dispatches_to_the_first_host_listing_the_tool() {
        let host = FanOutToolHost::new(vec![
            stub("a", &["read", "shared"]),
            stub("b", &["browser_list_tabs", "shared"]),
        ]);
        assert_eq!(
            host.call("browser_list_tabs", "{}").await.unwrap(),
            "b:browser_list_tabs:{}"
        );
        // Duplicated names resolve to the first host.
        assert_eq!(host.call("shared", "{}").await.unwrap(), "a:shared:{}");
    }

    #[tokio::test]
    async fn hidden_alias_dispatches_without_being_advertised() {
        let host = FanOutToolHost::new(vec![stub("mcp", &["mcp__readable"])]);

        assert_eq!(host.list_tools(), ["mcp__readable"]);
        assert_eq!(
            host.call("legacy_hidden", "{}").await.unwrap(),
            "mcp:legacy_hidden:{}"
        );
    }

    #[tokio::test]
    async fn unknown_tool_is_a_tool_error() {
        let host = FanOutToolHost::new(vec![stub("a", &["read"])]);
        let error = host.call("browser_snapshot", "{}").await.unwrap_err();
        assert!(matches!(error, CoreError::Tool(_)));
        assert!(error.to_string().contains("unknown tool"));
    }
}
