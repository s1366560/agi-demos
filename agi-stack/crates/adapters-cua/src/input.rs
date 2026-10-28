//! Trusted input selection and bounded, non-authoritative input presentation.
use crate::CuaCallContext;
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CuaInputMode {
    #[default]
    Background,
    Foreground,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CuaVirtualCursor {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
    pub window_id: String,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CuaInputTelemetry {
    pub context: CuaCallContext,
    pub input_generation: String,
    pub sequence: u64,
    pub updated_at: f64,
    pub phase: String,
    pub evidence: String,
    pub target_pid: i64,
    pub target_window_id: Option<String>,
    pub virtual_cursor: Option<CuaVirtualCursor>,
    pub held_keys: Vec<u16>,
    pub held_buttons: Vec<u32>,
    pub reason: Option<String>,
}

impl CuaInputTelemetry {
    pub(crate) fn valid(&self) -> bool {
        !self.input_generation.is_empty()
            && self.input_generation.len() <= 128
            && self.sequence <= 9_007_199_254_740_991
            && self.updated_at.is_finite()
            && self.updated_at >= 0.0
            && self.updated_at <= 9_007_199_254_740_991.0
            && self.target_pid >= 0
            && self.target_pid <= i64::from(i32::MAX)
            && self.held_keys.len() <= 256
            && self.held_buttons.len() <= 32
            && self.held_buttons.iter().all(|button| *button <= 31)
            && self
                .held_buttons
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                == self.held_buttons.len()
            && self
                .held_keys
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                == self.held_keys.len()
            && self.reason.as_ref().is_none_or(|value| value.len() <= 256)
            && self
                .target_window_id
                .as_ref()
                .is_none_or(|value| !value.is_empty() && value.len() <= 256)
            && matches!(
                self.phase.as_str(),
                "idle" | "moving" | "holding" | "released" | "paused" | "stopped" | "error"
            )
            && matches!(self.evidence.as_str(), "dispatched" | "observed")
            && self.virtual_cursor.as_ref().is_none_or(|cursor| {
                [cursor.x, cursor.y, cursor.width, cursor.height]
                    .iter()
                    .all(|value| value.is_finite())
                    && cursor.width > 0.0
                    && cursor.height > 0.0
                    && cursor.width <= 1_000_000.0
                    && cursor.height <= 1_000_000.0
                    && cursor.x >= 0.0
                    && cursor.x < cursor.width
                    && cursor.y >= 0.0
                    && cursor.y < cursor.height
                    && self.target_window_id.as_deref() == Some(cursor.window_id.as_str())
            })
    }
}
