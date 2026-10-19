//! Modality dispatch uses typed image attachments and the declared vision route.
use std::sync::Arc;
use agistack_core::{agent::types::{AgentAction,TranscriptEntry},
    model::{Episode,Memory},
    ports::{CoreResult,LlmPort,ToolDefinition,MemoryDraft,RelationshipDraft}};
use async_trait::async_trait;

pub(super) struct VisualInputLlm {
    pub default:Arc<dyn LlmPort>,
    pub vision:Arc<dyn LlmPort>,
}
impl VisualInputLlm {
    fn target(&self,transcript:&[TranscriptEntry])->&dyn LlmPort {
        if transcript.iter().any(|entry|!entry.media.is_empty()) {self.vision.as_ref()}
        else {self.default.as_ref()}
    }
}
#[async_trait]
impl LlmPort for VisualInputLlm {
    async fn extract_memory(&self,episode:&Episode)->CoreResult<MemoryDraft> {self.default.extract_memory(episode).await}
    async fn extract_relationships(&self,memory:&Memory)->CoreResult<Vec<RelationshipDraft>> {self.default.extract_relationships(memory).await}
    async fn decide(&self,goal:&str,round:u64,transcript:&[TranscriptEntry],available_tools:&[String])->CoreResult<AgentAction> {
        self.target(transcript).decide(goal,round,transcript,available_tools).await
    }
    async fn decide_with_tools(&self,goal:&str,round:u64,transcript:&[TranscriptEntry],tools:&[ToolDefinition])->CoreResult<AgentAction> {
        self.target(transcript).decide_with_tools(goal,round,transcript,tools).await
    }
    async fn decide_with_tools_stream(&self,goal:&str,round:u64,transcript:&[TranscriptEntry],tools:&[ToolDefinition],on_text:&(dyn for<'text> Fn(&'text str)+Send+Sync))->CoreResult<AgentAction> {
        self.target(transcript).decide_with_tools_stream(goal,round,transcript,tools,on_text).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_core::agent::types::{MediaAttachment,Role};
    struct Model(&'static str);
    #[async_trait]
    impl LlmPort for Model {
        async fn extract_memory(&self,_:&Episode)->CoreResult<MemoryDraft> {unreachable!()}
        async fn decide(&self,_:&str,_:u64,_:&[TranscriptEntry],_:&[String])->CoreResult<AgentAction> {
            Ok(AgentAction::Finish{answer:self.0.into()})
        }
    }
    #[tokio::test]
    async fn typed_media_uses_vision_and_text_mention_does_not() {
        let model=VisualInputLlm{default:Arc::new(Model("text")),vision:Arc::new(Model("vision"))};
        let mut transcript=vec![TranscriptEntry::new(0,Role::Observation,"image screenshot base64 file://fake.png")];
        assert!(matches!(model.decide("goal",1,&transcript,&[]).await.unwrap(),AgentAction::Finish{answer} if answer=="text"));
        transcript[0].media.push(MediaAttachment{artifact_path:"/owned/image.png".into(),mime_type:"image/png".into()});
        assert!(matches!(model.decide("goal",1,&transcript,&[]).await.unwrap(),AgentAction::Finish{answer} if answer=="vision"));
    }
}
