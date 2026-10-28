//! Trusted native user-control outcomes, independent of arbitrary tool output.
use crate::ports::ToolResult;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ToolControlOutcome {
    UserPaused,
    UserStopped,
}
impl ToolControlOutcome {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::UserPaused => "user_paused",
            Self::UserStopped => "user_stopped",
        }
    }
    pub fn result(self, generation: Option<String>) -> ToolResult {
        ToolResult {
            output_json: serde_json::json!({"type":"computer_use_control","status":self.as_str(),"retry_allowed":false}).to_string(),
            media: Vec::new(), control_outcome: Some(self), control_generation: generation,
            permission_required: None,
        }
    }
    pub fn matches_result(self, result: &ToolResult) -> bool {
        result.media.is_empty() && serde_json::from_str::<serde_json::Value>(&result.output_json).is_ok_and(|value|
            value == serde_json::json!({"type":"computer_use_control","status":self.as_str(),"retry_allowed":false}))
    }
}
