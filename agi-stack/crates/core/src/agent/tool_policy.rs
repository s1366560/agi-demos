//! Typed generation policy around the real tool execution boundary.

use async_trait::async_trait;
use serde_json::Value;

use crate::ports::{CoreResult, ToolHost, ToolResult};
use super::types::{HitlRequest, MediaAttachment};

/// Immutable call identity supplied by the engine, independent of plugin output.
pub struct ToolPolicyContext<'a> {
    pub session_id: &'a str,
    pub round: u64,
    pub tool: &'a str,
}

impl ToolPolicyContext<'_> {
    pub fn call_id(&self) -> String {
        format!("{}:{}:{}", self.session_id, self.round, self.tool)
    }
}

/// Decisions are structured plugin output; the engine only applies their protocol.
pub enum ToolPolicyDecision {
    Allow { input_json: String },
    Deny { reason: String },
    Cancel { reason: String },
    Ask { request: HitlRequest },
}

#[derive(Clone, Debug, PartialEq)]
pub struct ToolPolicyResult {
    pub output: String,
    pub is_error: bool,
    pub metadata: Value,
    pub media: Vec<MediaAttachment>,
}

#[async_trait]
pub trait ToolExecutionPolicy: Send + Sync {
    async fn before_execute(
        &self,
        context: &ToolPolicyContext<'_>,
        input_json: &str,
        input_schema: Option<&Value>,
    ) -> CoreResult<ToolPolicyDecision>;

    /// Scope host-side result events around the authorized concrete invocation.
    async fn execute(
        &self,
        _context: &ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input_json: &str,
    ) -> CoreResult<String> {
        tools.call(_context.tool, input_json).await
    }

    /// Preserve existing authorization wrappers. A media-aware wrapper must
    /// override this method and forward the trusted host's structured result.
    async fn execute_with_content(
        &self,
        context: &ToolPolicyContext<'_>,
        tools: &dyn ToolHost,
        input_json: &str,
    ) -> CoreResult<ToolResult> {
        self.execute(context, tools, input_json).await.map(ToolResult::text)
    }

    async fn transform_result(
        &self,
        context: &ToolPolicyContext<'_>,
        result: ToolPolicyResult,
    ) -> CoreResult<ToolPolicyResult>;
}
