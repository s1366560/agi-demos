//! Explicit first-release execution scope, shared by admission and observations.

use agistack_core::agent::{HitlKind, HitlRequest};
use agistack_core::ports::{CoreError, CoreResult};
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CronExecutionContract {
    PureToolsOrdinaryHitlV1,
}

impl CronExecutionContract {
    pub(crate) fn validate_hitl(self, request: &HitlRequest) -> CoreResult<()> {
        match self {
            Self::PureToolsOrdinaryHitlV1
                if matches!(request.kind, HitlKind::Clarification | HitlKind::Decision)
                    && request.permission_invocation.is_none()
                    && request.a2ui_action.is_none() =>
            {
                Ok(())
            }
            _ => Err(CoreError::Tool(
                "HITL kind is outside the automation execution contract".into(),
            )),
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub(crate) struct CronExecutionCapabilities {
    pub(crate) contract: Option<CronExecutionContract>,
    /// Only registered tools declared Pure and applicable to the current lease.
    pub(crate) pure_tools: bool,
    pub(crate) ordinary_hitl_resume: bool,
    pub(crate) supported_hitl: Vec<HitlKind>,
    pub(crate) unsupported_hitl: Vec<HitlKind>,
    pub(crate) scoped_tool_reads: bool,
    pub(crate) mutations: bool,
}

impl CronExecutionCapabilities {
    /// Called only alongside the actual restricted executor and ordinary
    /// coordinator composition. This does not assert model or loop readiness.
    pub(crate) fn pure_tools_ordinary_hitl() -> Self {
        Self {
            contract: Some(CronExecutionContract::PureToolsOrdinaryHitlV1),
            pure_tools: true,
            ordinary_hitl_resume: true,
            supported_hitl: vec![HitlKind::Clarification, HitlKind::Decision],
            unsupported_hitl: vec![HitlKind::Permission, HitlKind::EnvVar, HitlKind::A2uiAction],
            scoped_tool_reads: false,
            mutations: false,
        }
    }
}
