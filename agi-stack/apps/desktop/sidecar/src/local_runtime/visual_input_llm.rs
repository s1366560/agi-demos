//! Typed images select vision; audio input requires declared support and native authority.
use std::{
    borrow::Cow,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

use agistack_core::{
    agent::types::{AgentAction, Role, TranscriptEntry},
    model::{Episode, Memory},
    ports::{CoreError, CoreResult, LlmPort, MemoryDraft, RelationshipDraft, ToolDefinition},
};
use async_trait::async_trait;

#[path = "audio_input_authority.rs"]
mod audio_authority;

use super::{agent_boundary_v2::AgentBoundaryV2, DesktopRun, LocalConversation, LocalRuntimeState};

pub(super) struct VisualInputLlm {
    default: Arc<dyn LlmPort>,
    vision: Arc<dyn LlmPort>,
    audio_authority: Option<audio_authority::AudioInputAuthority>,
}

impl VisualInputLlm {
    pub(super) fn new(
        state: &Arc<LocalRuntimeState>,
        conversation: &LocalConversation,
        run: Option<&DesktopRun>,
        boundary: Option<Arc<AgentBoundaryV2>>,
        default: Arc<dyn LlmPort>,
        vision: Arc<dyn LlmPort>,
    ) -> Self {
        Self {
            default,
            vision,
            audio_authority: audio_authority::AudioInputAuthority::capture(
                state,
                conversation,
                run,
                boundary,
            ),
        }
    }

    fn target(&self, transcript: &[TranscriptEntry]) -> &dyn LlmPort {
        if transcript
            .iter()
            .flat_map(|entry| &entry.media)
            .any(|media| media.mime_type.starts_with("image/"))
        {
            self.vision.as_ref()
        } else {
            self.default.as_ref()
        }
    }

    fn validate_attached_audio(&self, transcript: &[TranscriptEntry]) -> CoreResult<()> {
        for attachment in transcript
            .iter()
            .flat_map(|entry| &entry.media)
            .filter(|media| media.mime_type.starts_with("audio/"))
        {
            self.audio_authority
                .as_ref()
                .ok_or_else(|| CoreError::Llm("audio_input_authority_required".into()))?
                .validate(attachment)?;
        }
        Ok(())
    }

    fn settle(
        &self,
        transcript: &[TranscriptEntry],
        result: CoreResult<AgentAction>,
    ) -> CoreResult<AgentAction> {
        self.validate_attached_audio(transcript)?;
        result
    }

    fn prepare<'a>(
        &self,
        transcript: &'a [TranscriptEntry],
    ) -> CoreResult<Cow<'a, [TranscriptEntry]>> {
        let mut prepared = Cow::Borrowed(transcript);
        let supports_audio = self.target(transcript).supports_audio_input();
        for (index, entry) in transcript.iter().enumerate() {
            let audio = entry
                .media
                .iter()
                .filter(|media| media.mime_type.starts_with("audio/"))
                .collect::<Vec<_>>();
            if audio.is_empty() {
                continue;
            }
            if entry.role == Role::Observation {
                let authorized = self.audio_authority.as_ref().is_some_and(|authority| {
                    audio
                        .iter()
                        .all(|attachment| authority.validate(attachment).is_ok())
                });
                if supports_audio && authorized {
                    continue;
                }
                // Keep the persisted UI result. The model copy omits bytes whenever
                // the selected model or native artifact authority is unavailable.
                let entry = &mut prepared.to_mut()[index];
                entry
                    .media
                    .retain(|media| !media.mime_type.starts_with("audio/"));
                entry.content.push_str(&format!(
                    "\n[Host media notice: {} audio output attachment(s) are available in the UI. \
                     Audio bytes were not sent to this model ({}); do not claim to have listened.]",
                    audio.len(),
                    if supports_audio {
                        "audio_input_authority_unavailable"
                    } else {
                        "audio_input_unsupported"
                    }
                ));
            } else if entry.role == Role::Human {
                let authority = self
                    .audio_authority
                    .as_ref()
                    .ok_or_else(|| CoreError::Llm("audio_input_authority_required".into()))?;
                for attachment in audio {
                    authority.validate(attachment)?;
                }
            } else {
                return Err(CoreError::Llm("audio_input_source_invalid".into()));
            }
        }
        Ok(prepared)
    }
}

#[async_trait]
impl LlmPort for VisualInputLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.default.extract_memory(episode).await
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        self.default.extract_relationships(memory).await
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        let prepared = self.prepare(transcript)?;
        let result = self
            .target(&prepared)
            .decide(goal, round, &prepared, available_tools)
            .await;
        self.settle(&prepared, result)
    }

    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        let prepared = self.prepare(transcript)?;
        let result = self
            .target(&prepared)
            .decide_with_tools(goal, round, &prepared, tools)
            .await;
        self.settle(&prepared, result)
    }

    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        let prepared = self.prepare(transcript)?;
        let revoked = AtomicBool::new(false);
        let authorized_text = |text: &str| {
            if revoked.load(Ordering::Acquire) {
                return;
            }
            if self.validate_attached_audio(&prepared).is_err() {
                revoked.store(true, Ordering::Release);
                return;
            }
            on_text(text);
        };
        let result = self
            .target(&prepared)
            .decide_with_tools_stream(goal, round, &prepared, tools, &authorized_text)
            .await;
        if revoked.load(Ordering::Acquire) {
            return Err(CoreError::Llm("audio_input_authority_revoked".into()));
        }
        self.settle(&prepared, result)
    }
}

#[cfg(test)]
#[path = "visual_input_llm_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "macos"))]
#[path = "audio_input_authority_tests.rs"]
mod authority_tests;
