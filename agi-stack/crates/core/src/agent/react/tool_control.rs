use crate::ports::{CoreError, CoreResult, ToolControlOutcome, ToolResult};

/// The trusted host's resolution of one native control generation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolControlResolution {
    /// No live native authority can resolve the pause; retain a paused checkpoint.
    Pending,
    /// The user successfully resumed this exact native pause generation.
    Resumed,
    /// The user stopped desktop control. Other authorized work may continue.
    Stopped,
    /// The parent run has its own Pause/Cancel directive to consume next.
    RunInterrupted,
}

impl ToolControlResolution {
    pub(super) fn guidance(self) -> Option<String> {
        let (state, instruction) = match self {
            Self::Resumed => (
                "resumed",
                "The user resumed computer control. The interrupted action may have had partial effects. Call computer_list_windows again and use a current window_id from that result; the native session may have been recreated while paused and old window IDs may be invalid. Obtain a fresh observation of that window before choosing another desktop action. Do not automatically replay the interrupted action. Resuming control does not restart audio recording.",
            ),
            Self::Stopped => (
                "stopped",
                "The user stopped computer control for this run. Do not retry desktop actions or request permission to bypass this stop. Other authorized work may continue. Report unfinished desktop work honestly; this control handoff does not prove the original goal was achieved.",
            ),
            Self::Pending | Self::RunInterrupted => return None,
        };
        Some(
            serde_json::json!({
                "type": "computer_use_control_resolution",
                "state": state,
                "runtime_guidance": instruction,
            })
            .to_string(),
        )
    }
}

pub(super) fn validate(result: ToolResult) -> CoreResult<ToolResult> {
    let valid = match result.control_outcome {
        Some(outcome) => {
            outcome.matches_result(&result)
                && match outcome {
                    ToolControlOutcome::UserPaused => result
                        .control_generation
                        .as_ref()
                        .is_some_and(|generation| !generation.is_empty()),
                    ToolControlOutcome::UserStopped => result.control_generation.is_none(),
                }
        }
        None => result.control_generation.is_none(),
    };
    if valid {
        Ok(result)
    } else {
        Err(CoreError::Tool("invalid tool control result".into()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resume_requires_window_enumeration_and_observation_without_replay() {
        let value: serde_json::Value =
            serde_json::from_str(&ToolControlResolution::Resumed.guidance().unwrap()).unwrap();
        assert_eq!(value["type"], "computer_use_control_resolution");
        assert_eq!(value["state"], "resumed");
        let instruction = value["runtime_guidance"].as_str().unwrap();
        assert!(instruction.contains("computer_list_windows"));
        assert!(instruction.contains("window_id"));
        assert!(instruction.contains("fresh observation"));
        assert!(instruction.contains("Do not automatically replay"));
    }
}
