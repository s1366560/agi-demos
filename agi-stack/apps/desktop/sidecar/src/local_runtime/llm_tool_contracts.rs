use super::*;

#[async_trait]
impl LlmPort for MeteredLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        let started_at = std::time::Instant::now();
        let result = self.inner.extract_memory(episode).await;
        if result.is_ok() {
            self.record_success(started_at);
        }
        result
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        let started_at = std::time::Instant::now();
        let result = self.inner.extract_relationships(memory).await;
        if result.is_ok() {
            self.record_success(started_at);
        }
        result
    }

    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        let started_at = std::time::Instant::now();
        let result = self
            .inner
            .decide_with_tools_stream(goal, round, transcript, tools, on_text)
            .await;
        if result.is_ok() {
            self.record_success(started_at);
        }
        result
    }

    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
    ) -> CoreResult<AgentAction> {
        let started_at = std::time::Instant::now();
        let result = self
            .inner
            .decide_with_tools(goal, round, transcript, tools)
            .await;
        if result.is_ok() {
            self.record_success(started_at);
        }
        result
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        let started_at = std::time::Instant::now();
        let result = self
            .inner
            .decide(goal, round, transcript, available_tools)
            .await;
        if result.is_ok() {
            self.record_success(started_at);
        }
        result
    }
}

#[async_trait]
impl LlmPort for FailoverLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.attempt(|candidate| async move { candidate.extract_memory(episode).await })
            .await
    }

    async fn extract_relationships(&self, memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        self.attempt(|candidate| async move { candidate.extract_relationships(memory).await })
            .await
    }

    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        let emitted = std::sync::atomic::AtomicBool::new(false);
        let forward = |delta: &str| {
            if !delta.is_empty() {
                emitted.store(true, Ordering::Release);
                on_text(delta);
            }
        };
        let mut last_error = None;
        for candidate in &self.candidates {
            let result = tokio::time::timeout(
                self.candidate_timeout,
                candidate.decide_with_tools_stream(goal, round, transcript, tools, &forward),
            )
            .await
            .unwrap_or_else(|_| {
                Err(CoreError::Llm(format!(
                    "model_timeout: LLM routing candidate exceeded {} ms",
                    self.candidate_timeout.as_millis()
                )))
            });
            match result {
                Ok(action) => return Ok(action),
                // Never join an already visible partial answer to another provider's answer.
                Err(error) if emitted.load(Ordering::Acquire) => return Err(error),
                Err(error) => last_error = Some(error),
            }
        }
        Err(last_error.unwrap_or_else(|| {
            CoreError::Llm("model_unconfigured: no usable LLM routing targets".to_string())
        }))
    }

    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
    ) -> CoreResult<AgentAction> {
        self.attempt(|candidate| async move {
            candidate
                .decide_with_tools(goal, round, transcript, tools)
                .await
        })
        .await
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        self.attempt(|candidate| async move {
            candidate
                .decide(goal, round, transcript, available_tools)
                .await
        })
        .await
    }
}

#[async_trait]
impl LlmPort for AnthropicAgentLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        Ok(MemoryDraft {
            title: "Anthropic local memory".to_string(),
            content: episode.content.clone(),
            tags: Vec::new(),
            entities: Vec::new(),
        })
    }

    async fn decide_with_tools_stream(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
        on_text: &(dyn for<'text> Fn(&'text str) + Send + Sync),
    ) -> CoreResult<AgentAction> {
        let goal = agistack_core::tool_definition::prompt_with_tool_definitions(goal, tools)?;
        let names = tools
            .iter()
            .map(|tool| tool.name.clone())
            .collect::<Vec<_>>();
        let user = json!({
            "goal": goal,
            "round": round,
            "transcript": transcript,
            "available_tools": names,
        })
        .to_string();
        let mut answer = agistack_adapters_http_llm::AgentAnswerStream::default();
        let raw = self.inner.stream_complete(
            "You are a ReAct agent. Respond with ONLY JSON: {\"kind\":\"finish\",\"answer\":string} or {\"kind\":\"call_tool\",\"tool\":string,\"input_json\":string}.",
            user,
            |delta| answer.push(delta, on_text),
        ).await?;
        parse_agent_action(&raw)
    }

    async fn decide_with_tools(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        tools: &[agistack_core::ports::ToolDefinition],
    ) -> CoreResult<AgentAction> {
        let goal = agistack_core::tool_definition::prompt_with_tool_definitions(goal, tools)?;
        let names = tools
            .iter()
            .map(|tool| tool.name.clone())
            .collect::<Vec<_>>();
        self.decide(&goal, round, transcript, &names).await
    }

    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction> {
        let user = json!({
            "goal": goal,
            "round": round,
            "transcript": transcript,
            "available_tools": available_tools,
        })
        .to_string();
        let raw = self
            .inner
            .stream_complete(
                "You are a ReAct agent. Respond with ONLY JSON: {\"kind\":\"finish\",\"answer\":string} or {\"kind\":\"call_tool\",\"tool\":string,\"input_json\":string}.",
                user,
                |_| {},
            )
            .await?;
        parse_agent_action(&raw)
    }
}
