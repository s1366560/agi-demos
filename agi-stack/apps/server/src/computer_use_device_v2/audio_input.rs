//! Audio model input belongs to the current cloud run and its socket-owned artifacts.
use super::{authority::RunAuthority, Broker, Owner};
use agistack_core::{
    agent::types::{AgentAction, MediaAttachment, Role, TranscriptEntry},
    model::{Episode, Memory},
    ports::{
        CoreError, CoreResult, LlmPort, MemoryDraft, RelationshipDraft, ToolControlOutcome,
        ToolDefinition,
    },
};
use async_trait::async_trait;
use sha2::{Digest, Sha256};
use std::{
    borrow::Cow,
    future::Future,
    path::Path,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::io::AsyncReadExt;

const MAX_AUDIO_BYTES: u64 = 32 * 1024 * 1024;

fn denied() -> CoreError {
    CoreError::Llm("audio_input_authority_unavailable".into())
}

#[derive(Clone)]
pub(super) struct Scope {
    pub broker: Broker,
    pub owner: Owner,
    pub conversation: String,
    pub session: String,
    pub run: RunAuthority,
}

impl Scope {
    async fn recheck(&self, attachment: &MediaAttachment) -> CoreResult<()> {
        self.broker
            .authority
            .as_ref()
            .ok_or_else(denied)?
            .recheck_running(&self.owner, &self.conversation, &self.run)
            .await?;
        let requests = self.broker.requests.lock().expect("CUA requests");
        let request = requests
            .values()
            .find(|request| {
                request.owner == self.owner
                    && request.run == self.run
                    && request.claim.conversation_id == self.conversation
                    && request.claim.session_id == self.session
                    && request.status == "completed"
                    && !request.failed
                    && !request.cancelled
                    && request
                        .result
                        .as_ref()
                        .is_some_and(|result| result.media.contains(attachment))
            })
            .ok_or_else(denied)?;
        self.broker.validate_request_device(request)?;
        let receipts = self
            .broker
            .control_receipts
            .lock()
            .expect("CUA control receipts");
        for request in requests.values().filter(|request| {
            request.owner == self.owner
                && request.run == self.run
                && request.claim.conversation_id == self.conversation
                && request.claim.session_id == self.session
        }) {
            let Some(result) = &request.result else {
                continue;
            };
            match result.control_outcome {
                Some(ToolControlOutcome::UserStopped) => return Err(denied()),
                Some(ToolControlOutcome::UserPaused) => {
                    let generation = result.control_generation.as_ref().ok_or_else(denied)?;
                    if receipts
                        .get(&(request.claim.request_id.clone(), generation.clone()))
                        .is_none_or(|state| state != "resumed")
                    {
                        return Err(denied());
                    }
                }
                None => {}
            }
        }
        Ok(())
    }

    pub(super) async fn validate(&self, attachment: &MediaAttachment) -> CoreResult<()> {
        self.recheck(attachment).await?;
        let (expected_size, expected_hash) = {
            let requests = self.broker.requests.lock().expect("CUA requests");
            let request = requests
                .values()
                .find(|request| {
                    request.owner == self.owner
                        && request.run == self.run
                        && request.claim.conversation_id == self.conversation
                        && request.claim.session_id == self.session
                        && request.status == "completed"
                        && !request.failed
                        && !request.cancelled
                        && request
                            .result
                            .as_ref()
                            .is_some_and(|result| result.media.contains(attachment))
                })
                .ok_or_else(denied)?;
            self.broker.validate_request_device(request)?;
            let root = self.broker.cache.lock().expect("CUA cache");
            let root = root.as_ref().ok_or_else(denied)?;
            // The private path derives from an opaque object key, never from tool text.
            let artifact = request
                .media
                .iter()
                .find(|artifact| {
                    let key = format!(
                        "computer-use/{}/{}/{}",
                        super::broker::digest(
                            &serde_json::to_string(&request.owner).expect("owner serializes")
                        ),
                        request.claim.request_id,
                        artifact.descriptor.artifact_id
                    );
                    artifact.complete
                        && artifact.descriptor.mime_type == attachment.mime_type
                        && root.join(super::broker::digest(&key))
                            == Path::new(&attachment.artifact_path)
                })
                .ok_or_else(denied)?;
            if attachment.mime_type != "audio/wav"
                || artifact.bytes.is_empty()
                || artifact.bytes.len() as u64 > MAX_AUDIO_BYTES
            {
                return Err(denied());
            }
            (artifact.bytes.len() as u64, Sha256::digest(&artifact.bytes))
        };
        let root = self
            .broker
            .cache
            .lock()
            .expect("CUA cache")
            .clone()
            .ok_or_else(denied)?;
        let path = Path::new(&attachment.artifact_path);
        let metadata = tokio::fs::symlink_metadata(path)
            .await
            .map_err(|_| denied())?;
        if !path.is_absolute() || !metadata.is_file() || metadata.len() != expected_size {
            return Err(denied());
        }
        let canonical = tokio::fs::canonicalize(path).await.map_err(|_| denied())?;
        let root = tokio::fs::canonicalize(root).await.map_err(|_| denied())?;
        if canonical.parent() != Some(root.as_path()) {
            return Err(denied());
        }
        let file = tokio::fs::File::open(path).await.map_err(|_| denied())?;
        let mut bytes = Vec::with_capacity(expected_size as usize);
        file.take(MAX_AUDIO_BYTES + 1)
            .read_to_end(&mut bytes)
            .await
            .map_err(|_| denied())?;
        if bytes.len() as u64 != expected_size || Sha256::digest(&bytes) != expected_hash {
            return Err(denied());
        }
        Ok(())
    }
}

pub(super) struct AudioInputLlm {
    inner: Arc<dyn LlmPort>,
    scope: Option<Scope>,
}

impl AudioInputLlm {
    pub(super) fn new(inner: Arc<dyn LlmPort>, scope: Option<Scope>) -> Self {
        Self { inner, scope }
    }

    async fn validate_audio(&self, transcript: &[TranscriptEntry]) -> CoreResult<()> {
        for audio in transcript
            .iter()
            .flat_map(|entry| &entry.media)
            .filter(|media| is_audio(media))
        {
            self.scope
                .as_ref()
                .ok_or_else(denied)?
                .validate(audio)
                .await?;
        }
        Ok(())
    }

    async fn prepare<'a>(
        &self,
        transcript: &'a [TranscriptEntry],
    ) -> CoreResult<Cow<'a, [TranscriptEntry]>> {
        let mut prepared = Cow::Borrowed(transcript);
        for (index, entry) in transcript.iter().enumerate() {
            let audio: Vec<_> = entry.media.iter().filter(|media| is_audio(media)).collect();
            if audio.is_empty() {
                continue;
            }
            if !matches!(entry.role, Role::Human | Role::Observation) {
                return Err(CoreError::Llm("audio_input_source_invalid".into()));
            }
            let mut reason = None;
            if !self.inner.supports_audio_input() {
                reason = Some("audio_input_unsupported");
            } else if let Some(scope) = &self.scope {
                for attachment in &audio {
                    if scope.validate(attachment).await.is_err() {
                        reason = Some("audio_input_authority_unavailable");
                        break;
                    }
                }
            } else {
                reason = Some("audio_input_authority_unavailable");
            }
            if let Some(reason) = reason {
                if entry.role == Role::Human {
                    return Err(CoreError::Llm(reason.into()));
                }
                let entry = &mut prepared.to_mut()[index];
                entry.media.retain(|media| !is_audio(media));
                entry.content.push_str(&format!(
                    "\n[Host media notice: {} audio output attachment(s) are available in the UI. \
                     Audio bytes were not sent to this model ({reason}); do not claim to have listened.]", audio.len()));
            }
        }
        Ok(prepared)
    }

    async fn settle(
        &self,
        transcript: &[TranscriptEntry],
        result: CoreResult<AgentAction>,
    ) -> CoreResult<AgentAction> {
        self.validate_audio(transcript).await?;
        result
    }

    async fn guarded(
        &self,
        transcript: &[TranscriptEntry],
        operation: impl Future<Output = CoreResult<AgentAction>>,
    ) -> CoreResult<AgentAction> {
        if !transcript
            .iter()
            .flat_map(|entry| &entry.media)
            .any(is_audio)
        {
            return operation.await;
        }
        tokio::pin!(operation);
        let mut check = tokio::time::interval(Duration::from_millis(250));
        check.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        loop {
            tokio::select! {
                biased;
                _ = check.tick() => {
                    for audio in transcript.iter().flat_map(|entry| &entry.media).filter(|media| is_audio(media)) {
                        self.scope.as_ref().ok_or_else(denied)?.recheck(audio).await?;
                    }
                }
                result = &mut operation => return self.settle(transcript, result).await,
            }
        }
    }
}

fn is_audio(media: &MediaAttachment) -> bool {
    media.mime_type.starts_with("audio/")
}

#[async_trait]
impl LlmPort for AudioInputLlm {
    fn supports_audio_input(&self) -> bool {
        self.inner.supports_audio_input()
    }
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.inner.extract_memory(episode).await
    }
    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        self.inner.extract_relationships(memory).await
    }
    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[String],
    ) -> CoreResult<AgentAction> {
        let prepared = self.prepare(transcript).await?;
        self.guarded(&prepared, self.inner.decide(goal, round, &prepared, tools))
            .await
    }
    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
    ) -> CoreResult<AgentAction> {
        let prepared = self.prepare(transcript).await?;
        self.guarded(
            &prepared,
            self.inner.decide_with_tools(goal, round, &prepared, tools),
        )
        .await
    }
    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        let prepared = self.prepare(transcript).await?;
        if !prepared.iter().flat_map(|entry| &entry.media).any(is_audio) {
            return self
                .inner
                .decide_with_tools_stream(goal, round, &prepared, tools, on_text)
                .await;
        }
        // Postgres authority is asynchronous. Hold provisional audio answers until
        // the current run and owned artifacts have passed the final authority read.
        let pending = Mutex::new(String::new());
        let capture = |text: &str| pending.lock().expect("audio answer").push_str(text);
        let result = self
            .guarded(
                &prepared,
                self.inner
                    .decide_with_tools_stream(goal, round, &prepared, tools, &capture),
            )
            .await?;
        on_text(&pending.into_inner().expect("audio answer"));
        Ok(result)
    }
}

pub(crate) fn bind(
    model: Arc<dyn LlmPort>,
    bound: Option<&super::BoundRun>,
    conversation: &str,
    session: &str,
) -> Arc<dyn LlmPort> {
    Arc::new(AudioInputLlm::new(
        model,
        bound.map(|bound| Scope {
            broker: bound.broker.clone(),
            owner: bound.owner.clone(),
            run: bound.run.clone(),
            conversation: conversation.into(),
            session: session.into(),
        }),
    ))
}
