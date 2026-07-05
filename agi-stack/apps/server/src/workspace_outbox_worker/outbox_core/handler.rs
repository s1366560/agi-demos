use super::*;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum WorkspacePlanOutboxHandlerOutcome {
    Complete,
    Release {
        reason: Option<String>,
    },
    Park {
        status: String,
        metadata_patch: Value,
    },
    ParkWithPayload {
        status: String,
        metadata_patch: Value,
        payload_patch: Value,
    },
}

#[async_trait]
pub(crate) trait WorkspacePlanOutboxHandler: Send + Sync {
    async fn handle(
        &self,
        item: WorkspacePlanOutboxRecord,
    ) -> CoreResult<WorkspacePlanOutboxHandlerOutcome>;
}

#[async_trait]
pub(crate) trait WorkspacePipelineStageRunner: Send + Sync {
    async fn run_stage(
        &self,
        project_id: &str,
        contract: &PipelineContractFoundation,
        stage: &PipelineStageSpec,
    ) -> PipelineStageResult;
}
