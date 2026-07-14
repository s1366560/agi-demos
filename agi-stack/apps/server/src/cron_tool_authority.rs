//! Run-scoped tool authority for durable automation execution.
//!
//! The current production-safe boundary allows only tools declared as pure.
//! Scoped reads need a context-aware adapter, and mutations need a durable grant
//! plus invocation ledger; both remain fail-closed until composed.

#![allow(dead_code)]

use std::sync::Arc;

use agistack_adapters_postgres::AutomationRunLease;
use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use agistack_plugin_host::{HotPlugRegistry, ToolAccessClass};
use async_trait::async_trait;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
struct AutomationRunAuthority {
    surface: &'static str,
    tenant_id: String,
    project_id: String,
    job_id: String,
    run_id: String,
    conversation_id: String,
    actor_user_id: String,
    runtime_revision: i64,
}

impl AutomationRunAuthority {
    fn from_lease(lease: &AutomationRunLease) -> CoreResult<Self> {
        let context = &lease.context;
        let required = [
            context.tenant_id.as_str(),
            context.project_id.as_str(),
            context.job_id.as_str(),
            context.run_id.as_str(),
            context.runtime_execution_id.as_str(),
            context.conversation_id.as_str(),
            context.actor_user_id.as_str(),
            lease.lease_owner.as_str(),
            lease.lease_token.as_str(),
        ];
        if required.iter().any(|value| value.trim().is_empty())
            || context.run_id != context.runtime_execution_id
            || lease.runtime_revision <= 0
        {
            return Err(CoreError::Tool(
                "automation run authority is structurally invalid".to_string(),
            ));
        }
        Ok(Self {
            surface: "automation",
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            job_id: context.job_id.clone(),
            run_id: context.run_id.clone(),
            conversation_id: context.conversation_id.clone(),
            actor_user_id: context.actor_user_id.clone(),
            runtime_revision: lease.runtime_revision,
        })
    }

    fn applicability_context(&self) -> CoreResult<String> {
        serde_json::to_string(self).map_err(|_| {
            CoreError::Tool("automation run authority serialization failed".to_string())
        })
    }
}

pub(crate) trait AutomationToolHostFactory: Send + Sync {
    fn for_run(&self, lease: &AutomationRunLease) -> CoreResult<Arc<dyn ToolHost>>;
}

#[derive(Clone)]
pub(crate) struct RegistryAutomationToolHostFactory {
    registry: HotPlugRegistry,
}

impl RegistryAutomationToolHostFactory {
    pub(crate) fn new(registry: HotPlugRegistry) -> Self {
        Self { registry }
    }
}

impl AutomationToolHostFactory for RegistryAutomationToolHostFactory {
    fn for_run(&self, lease: &AutomationRunLease) -> CoreResult<Arc<dyn ToolHost>> {
        Ok(Arc::new(ScopedAutomationToolHost {
            registry: self.registry.clone(),
            authority: AutomationRunAuthority::from_lease(lease)?,
        }))
    }
}

struct ScopedAutomationToolHost {
    registry: HotPlugRegistry,
    authority: AutomationRunAuthority,
}

impl ScopedAutomationToolHost {
    fn pure_tool(&self, name: &str) -> CoreResult<Arc<dyn agistack_plugin_host::Tool>> {
        let tool = self
            .registry
            .get(name)
            .ok_or_else(|| CoreError::Tool(format!("unknown tool: {name}")))?;
        if tool.access_class() != ToolAccessClass::Pure {
            return Err(CoreError::Tool(
                "tool requires scoped read or mutation authority".to_string(),
            ));
        }
        let context = self.authority.applicability_context()?;
        if !tool.should_run(&context) {
            return Err(CoreError::Tool(
                "tool is not applicable to this automation run".to_string(),
            ));
        }
        Ok(tool)
    }
}

#[async_trait]
impl ToolHost for ScopedAutomationToolHost {
    fn list_tools(&self) -> Vec<String> {
        let context = match self.authority.applicability_context() {
            Ok(context) => context,
            Err(_) => return Vec::new(),
        };
        let snapshot = self.registry.snapshot();
        snapshot
            .names()
            .into_iter()
            .filter(|name| {
                snapshot.get(name).is_some_and(|tool| {
                    tool.access_class() == ToolAccessClass::Pure && tool.should_run(&context)
                })
            })
            .collect()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        self.pure_tool(tool)?.invoke(input_json).await
    }
}

#[cfg(test)]
mod tests;
