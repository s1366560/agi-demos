//! Independently configurable production worker modules. Apply never starts work.

use std::{collections::BTreeMap, sync::Arc};

use agistack_plugin_host::{ContextV2, PluginDefinitionV2, PluginModuleRuntimeV2, RuntimeV2Error};
use async_trait::async_trait;
use serde_json::Value;

use crate::{
    background_worker_control_v2::{BackgroundWorkerControllerV2, WorkerFactoryV2},
    cron_scheduler::{build_pg_cron_scheduler, CronSchedulerConfig},
    AppState,
};

pub(crate) const WORKER_SERVICES_V2: [&str; 3] = [
    "service:rust-server.skill-evolution-worker",
    "service:rust-server.channel-outbox-worker",
    "service:rust-server.cron-scheduler-worker",
];

pub(crate) const WORKER_MODULES_V2: [&str; 3] = [
    "builtin://memstack/rust-server/skill-evolution-worker",
    "builtin://memstack/rust-server/channel-outbox-worker",
    "builtin://memstack/rust-server/cron-scheduler-worker",
];
const WORKER_CONTRACTS_V2: [&str; 3] = [
    "sha256:2507be6512e34c55b3730d1f6d022c186bdcc7f122efbb6a1a1e0f0582215021",
    "sha256:0d1758bbf225811a434022ffae90c4b72ef5bdc6eb538ed0c85c29256bf75984",
    "sha256:86e82e004640593f1d1ce1017fec173af733f249fa3fab8e66ebd1786cf11867",
];

pub(crate) type CronWorkerResourceFactoryV2 = Arc<dyn Fn() -> WorkerFactoryV2 + Send + Sync>;

pub(crate) fn definitions_with_cron_resources_v2(
    skill: WorkerFactoryV2,
    outbox: WorkerFactoryV2,
    cron: CronWorkerResourceFactoryV2,
) -> Vec<PluginDefinitionV2> {
    let modules: [Arc<dyn PluginModuleRuntimeV2>; 3] = [
        Arc::new(SkillEvolutionWorkerModuleV2 { factory: skill }),
        Arc::new(ChannelOutboxWorkerModuleV2 { factory: outbox }),
        Arc::new(CronSchedulerWorkerModuleV2 { factory: cron }),
    ];
    modules
        .into_iter()
        .enumerate()
        .map(|(index, module)| PluginDefinitionV2 {
            module_ref: WORKER_MODULES_V2[index].into(),
            contract_digest: WORKER_CONTRACTS_V2[index].into(),
            module,
        })
        .collect()
}

pub(crate) struct SkillEvolutionWorkerModuleV2 {
    factory: WorkerFactoryV2,
}

#[async_trait]
impl PluginModuleRuntimeV2 for SkillEvolutionWorkerModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let controller = prepare_worker_controller_v2(
            context,
            config,
            &self.factory,
            "service:rust-server.skill-evolution-worker",
        )?;
        context.provide("service:rust-server.skill-evolution-worker", controller)?;
        Ok(())
    }
}

pub(crate) struct ChannelOutboxWorkerModuleV2 {
    factory: WorkerFactoryV2,
}

#[async_trait]
impl PluginModuleRuntimeV2 for ChannelOutboxWorkerModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        let controller = prepare_worker_controller_v2(
            context,
            config,
            &self.factory,
            "service:rust-server.channel-outbox-worker",
        )?;
        context.provide("service:rust-server.channel-outbox-worker", controller)?;
        Ok(())
    }
}

pub(crate) struct CronSchedulerWorkerModuleV2 {
    factory: CronWorkerResourceFactoryV2,
}

#[async_trait]
impl PluginModuleRuntimeV2 for CronSchedulerWorkerModuleV2 {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error> {
        // Construct one scheduler/config snapshot per candidate. This closure only
        // activates after publication, and its controller owns the resources through drain.
        let factory = (self.factory)();
        let controller = prepare_worker_controller_v2(
            context,
            config,
            &factory,
            "service:rust-server.cron-scheduler-worker",
        )?;
        context.provide("service:rust-server.cron-scheduler-worker", controller)?;
        Ok(())
    }
}

fn prepare_worker_controller_v2(
    context: &mut ContextV2,
    config: &BTreeMap<String, Value>,
    factory: &WorkerFactoryV2,
    label: &'static str,
) -> Result<Arc<BackgroundWorkerControllerV2>, RuntimeV2Error> {
    let autostart = config
        .get("autostart")
        .and_then(Value::as_bool)
        .ok_or_else(|| RuntimeV2Error::Module("worker autostart must be a boolean".into()))?;
    let factory = if autostart {
        factory.clone()
    } else {
        Arc::new(|| None)
    };
    let controller = Arc::new(BackgroundWorkerControllerV2::paused(factory));
    let cleanup = controller.clone();
    context.effect(
        label,
        Box::new(move || {
            Box::pin(async move { cleanup.drain().await.map_err(RuntimeV2Error::Module) })
        }),
    )?;
    Ok(controller)
}

pub(crate) fn worker_definitions_v2(state: Option<&AppState>) -> Vec<PluginDefinitionV2> {
    let skill = state.and_then(|state| state.skill_evolution_worker.clone());
    let outbox = state.and_then(|state| state.channel_outbox_delivery_worker.clone());
    let cron_infrastructure = state.and_then(|state| {
        state
            .worker_postgres
            .clone()
            .map(|pool| (pool, Arc::clone(&state.engine), state.registry.clone()))
    });
    definitions_with_cron_resources_v2(
        Arc::new(move || {
            skill
                .as_ref()
                .and_then(|worker| worker.clone().spawn_if_enabled())
        }),
        Arc::new(move || {
            outbox
                .as_ref()
                .and_then(|worker| worker.clone().spawn_if_enabled())
        }),
        Arc::new(move || match &cron_infrastructure {
            Some((pool, engine, registry)) => {
                let scheduler = build_pg_cron_scheduler(
                    pool.clone(),
                    Arc::clone(engine),
                    registry.clone(),
                    CronSchedulerConfig::from_env(),
                );
                Arc::new(move || scheduler.clone().spawn_if_enabled())
            }
            None => Arc::new(|| None),
        }),
    )
}

#[cfg(test)]
pub(crate) fn definitions_from_factories_v2(
    factories: [WorkerFactoryV2; 3],
) -> Vec<PluginDefinitionV2> {
    let [skill, outbox, cron] = factories;
    definitions_with_cron_resources_v2(skill, outbox, Arc::new(move || cron.clone()))
}
