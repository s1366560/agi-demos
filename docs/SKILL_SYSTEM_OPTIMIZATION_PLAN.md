# Skill System Optimization Plan: Forced Skill Compliance

**Date**: 2025-02-25
**Status**: Proposed
**Scope**: ReactAgent forced skill execution pipeline

## Problem Statement

When a user activates a skill via slash command (e.g., `/code-review`) from the frontend, the ReactAgent does not strictly follow the skill's instructions. Despite the forced skill name propagating correctly through the entire stack (Frontend -> WebSocket -> API -> Actor -> ReActAgent), the LLM frequently deviates from the skill's workflow by using unrelated tools, ignoring the skill's output format, or abandoning the skill mid-execution.

## Root Cause Analysis

Six root causes were identified, ordered by impact:

### Root Cause #1: No Tool Restriction (HIGH)

**Location**: `src/infrastructure/agent/core/react_agent.py`, lines 1782-1784

**Current Code**:
```python
# When a forced skill is active, remove skill_loader
if is_forced and matched_skill:
    tools_to_use = [t for t in tools_to_use if t.name != "skill_loader"]
```

**Problem**: When a forced skill is active, only `skill_loader` is removed from the available tools. The full set of 20+ tools (terminal, web_search, memory_search, desktop, etc.) remains available to the LLM. Since the LLM sees all tools, it frequently picks tools outside the skill's declared workflow, going off-script.

Each `Skill` has a `tools` field declaring which tools it uses (e.g., `["memory_search", "web_search"]`), but this field is never used to filter the available tool set.

**Impact**: The LLM has maximum freedom to deviate from skill instructions by calling any available tool.

---

### Root Cause #2: System Prompt Can Be Deleted (HIGH)

**Location**: `src/infrastructure/llm/litellm/litellm_client.py`, lines 300-354

**Current Code** (critical section at lines 322-324):
```python
# Last resort: drop system prompt if still above limit.
if token_count > input_limit and keep_system_prompt and len(trimmed) > 1:
    del trimmed[0]
    token_count = self._estimate_effective_input_tokens(model, trimmed)
```

**Problem**: `_trim_messages_to_input_limit()` has a last-resort fallback that deletes the system message entirely (`del trimmed[0]`). The system message contains all `<mandatory-skill>` instructions. If conversation history is long enough to push token count over the input budget, the skill instructions can be silently deleted.

The trimming pipeline:
1. First: remove non-system messages from oldest to newest (line 318-320)
2. Last resort: delete system message (line 322-324)
3. Final fallback: truncate largest message content (lines 328-339)

**Impact**: Complete loss of all skill instructions with no warning to the agent or user.

---

### Root Cause #3: Skill Instructions Diluted in Long Prompt (MEDIUM)

**Location**: `src/infrastructure/agent/prompts/manager.py`, lines 130-175

**Current Assembly Order**:
```
1. Base prompt (subagent override or model-specific default)
2. Memory context
3. Forced skill injection (<mandatory-skill> block)
4. Tools section (descriptions of ALL available tools)
5. Skills listing (skipped when forced - good)
6. SubAgents section
7. Environment context
8. Workspace context
9. Mode reminder
10. Custom rules (.memstack/AGENTS.md)
```

**Problem**: The `<mandatory-skill>` block is one section among many. In a typical prompt, the base prompt alone can be several thousand tokens, tool descriptions add thousands more, environment context adds more, etc. The mandatory skill instructions compete for attention with all this content. LLMs are known to have attention degradation in the middle of long prompts ("lost in the middle" effect).

Additionally, when a forced skill is active, the tools section still describes ALL tools (since Root Cause #1 doesn't filter them), adding noise that directly contradicts the skill's focused workflow.

**Impact**: LLM may not give sufficient weight to skill instructions buried in a long system prompt.

---

### Root Cause #4: No Reinforcement in ReAct Loop (MEDIUM)

**Location**: `src/infrastructure/agent/processor/processor.py`, lines 497-581 (`process()`) and 1165-1446 (`_process_step()`)

**Problem**: The `SessionProcessor` has zero awareness of skill context:
- It receives pre-built `messages` and `tools` with no skill metadata
- Between ReAct steps, no skill reminders are injected
- There is no validation that tool calls align with the skill's declared tools
- The processor treats every conversation turn identically, whether a skill is forced or not

When the ReAct loop runs multiple steps (Think -> Act -> Observe -> Think -> Act -> ...), the LLM's attention to the initial system prompt skill instructions degrades with each step as tool results accumulate in the conversation.

**Impact**: Multi-step skill executions drift off-track as the LLM loses focus on skill instructions.

---

### Root Cause #5: DIRECT Mode is Not Truly Direct (REMOVED - Pseudo-Requirement)

**Analysis**: When `find_by_name()` returns `mode=DIRECT`, the code proceeds through the full LLM-driven ReAct loop. Initial analysis suggested bypassing the ReAct loop for deterministic skills via `SkillExecutor`. However, this was determined to be a **pseudo-requirement**: skills are not deterministic scripts -- they require LLM judgment for error handling, adaptive responses, and context-dependent decisions. The massive complexity of implementing a true direct execution path provides negligible benefit over Fixes 1-4 + Fix 6, which address all root causes at the appropriate layers.

**Status**: No fix implemented. Root cause addressed by Fixes 1-4 + 6.

---

### Root Cause #6: Context Compression Can Alter Instructions (LOW)

**Location**: `src/infrastructure/agent/context/compression_engine.py`

**Problem**: The `ContextCompressionEngine` may summarize or rewrite system prompt content when compacting context. The `<mandatory-skill>` block has no protection against being compressed, meaning skill instructions could be lossy-compressed in long conversations.

**Impact**: Skill instructions may be subtly altered or abbreviated by the compression engine.

---

## Proposed Fixes

### Fix 1: Tool Filtering for Forced Skills (HIGH PRIORITY)

**File**: `src/infrastructure/agent/core/react_agent.py`
**Method**: `_stream_prepare_tools()` (line 1705)
**Effort**: Small (15-25 lines)

**Change**: When a forced skill is active, restrict available tools to ONLY the skill's declared tools plus essential system tools (`abort`, `todowrite`, `todoread`).

**Proposed Code** (replace lines 1782-1786):

```python
# When a forced skill is active, restrict tools to skill's declared set
if is_forced and matched_skill:
    skill_tools = set(matched_skill.tools) if matched_skill.tools else set()
    # Always keep essential system tools
    essential_tools = {"abort", "todowrite", "todoread"}
    allowed_tools = skill_tools | essential_tools
    tools_to_use = [t for t in tools_to_use if t.name in allowed_tools]

    if not tools_to_use:
        # Fallback: if skill declares no tools or none match, keep all
        # but still remove skill_loader
        tools_to_use = list(current_tool_definitions)
        tools_to_use = [t for t in tools_to_use if t.name != "skill_loader"]
        logger.warning(
            f"[ReActAgent] Forced skill '{matched_skill.name}' declares no matching tools, "
            f"keeping full tool set minus skill_loader"
        )
    else:
        logger.info(
            f"[ReActAgent] Forced skill tool filter: "
            f"declared={list(skill_tools)}, "
            f"available={[t.name for t in tools_to_use]}, "
            f"filtered_out={len(current_tool_definitions) - len(tools_to_use)}"
        )
```

**Verification**:
- Log output confirms tool filtering when forced skill is active
- Skill with declared tools only sees those tools + essential tools
- Skill with empty tools falls back to full set (safe degradation)

---

### Fix 2: System Prompt Protection (HIGH PRIORITY)

**File**: `src/infrastructure/llm/litellm/litellm_client.py`
**Method**: `_trim_messages_to_input_limit()` (line 300)
**Effort**: Small (10-15 lines)

**Change**: Never delete the system message when it contains `<mandatory-skill>`. Instead, truncate non-skill sections of the system prompt first.

**Proposed Code** (replace lines 322-325):

```python
# Last resort: try to trim system prompt content before deleting it
if token_count > input_limit and keep_system_prompt and len(trimmed) > 1:
    system_content = trimmed[0].get("content", "")
    has_mandatory_skill = "<mandatory-skill" in system_content

    if has_mandatory_skill:
        # Preserve mandatory-skill block, trim other sections
        trimmed[0] = dict(trimmed[0])
        trimmed[0]["content"] = self._trim_system_prompt_preserve_skill(system_content)
        token_count = self._estimate_effective_input_tokens(model, trimmed)
        if token_count <= input_limit:
            logger.info("Trimmed system prompt while preserving mandatory-skill block")
    
    # Only delete system message if still over limit AND no mandatory skill
    if token_count > input_limit:
        if has_mandatory_skill:
            logger.warning(
                "System prompt with mandatory-skill still exceeds limit after trimming. "
                "Keeping it to preserve skill instructions."
            )
        else:
            del trimmed[0]
            token_count = self._estimate_effective_input_tokens(model, trimmed)
```

**New Helper Method** (add to `LiteLLMClient`):

```python
@staticmethod
def _trim_system_prompt_preserve_skill(content: str) -> str:
    """Trim system prompt content while preserving <mandatory-skill> blocks.
    
    Removes sections that are least critical when a forced skill is active:
    - Workspace guidelines
    - Mode reminders
    - SubAgent descriptions
    - General capability descriptions
    
    Preserves:
    - <mandatory-skill> block (highest priority)
    - Environment context (needed for tool execution)
    - Tool descriptions (needed for skill's tools)
    """
    import re
    
    # Extract mandatory-skill block
    skill_match = re.search(
        r'(<mandatory-skill.*?</mandatory-skill>)',
        content,
        re.DOTALL,
    )
    if not skill_match:
        return content
    
    skill_block = skill_match.group(1)
    
    # Remove low-priority sections
    trimmed = content
    # Remove subagent section
    trimmed = re.sub(
        r'## Available SubAgents.*?(?=\n## |\n<|\Z)',
        '',
        trimmed,
        flags=re.DOTALL,
    )
    # Remove workspace section  
    trimmed = re.sub(
        r'## Workspace Guidelines.*?(?=\n## |\n<|\Z)',
        '',
        trimmed,
        flags=re.DOTALL,
    )
    
    # Ensure skill block is still present
    if '<mandatory-skill' not in trimmed:
        trimmed = skill_block + "\n\n" + trimmed
    
    return trimmed.strip()
```

**Verification**:
- System prompt with `<mandatory-skill>` is never deleted
- Non-skill sections are trimmed first
- Logging confirms trimming behavior

---

### Fix 3: Prompt Noise Reduction for Forced Skills (MEDIUM PRIORITY)

**File**: `src/infrastructure/agent/prompts/manager.py`
**Method**: `_build_capability_sections()` (line 194)
**Effort**: Small (10-15 lines)

**Change**: When a forced skill is active, reduce prompt noise by:
1. Only including tool descriptions for the skill's declared tools
2. Skipping the SubAgents section (already partially done - skills listing is skipped)
3. Moving the `<mandatory-skill>` block to the end of the prompt (most LLMs give highest attention to the beginning and end)

**Proposed Code** (modify `_build_capability_sections` at line 194):

```python
def _build_capability_sections(
    self,
    sections: list[str],
    context: PromptContext,
    is_forced_skill: bool,
) -> None:
    """Build tools, skills, and subagent sections."""
    if is_forced_skill and context.matched_skill:
        # For forced skills: only describe the skill's tools to reduce noise
        skill_tools = context.matched_skill.get("tools", [])
        if skill_tools:
            filtered_context = PromptContext(
                **{
                    **context.__dict__,
                    "tools": [t for t in (context.tools or []) if t.get("name") in skill_tools],
                }
            )
            tools_section = self._build_tools_section(filtered_context)
        else:
            tools_section = self._build_tools_section(context)
        if tools_section:
            sections.append(tools_section)
        # Skip skills listing (already done) AND subagents for forced skills
        return

    tools_section = self._build_tools_section(context)
    if tools_section:
        sections.append(tools_section)
    if context.skills and not is_forced_skill:
        skill_section = self._build_skill_section(context)
        if skill_section:
            sections.append(skill_section)
    if context.subagents:
        subagent_section = self._build_subagent_section(context)
        if subagent_section:
            sections.append(subagent_section)
    if context.matched_skill and not is_forced_skill:
        skill_recommendation = self._build_skill_recommendation(context.matched_skill)
        if skill_recommendation:
            sections.append(skill_recommendation)
```

**Additionally** - move forced skill injection to be last in `_build_base_sections` order, or duplicate it as a trailing reminder:

```python
# In build_system_prompt(), after all sections are built:
if is_forced_skill and context.matched_skill:
    # Add skill reminder at the end (recency bias)
    reminder = (
        f'\n<skill-reminder priority="highest">'
        f'\nRemember: You are executing forced skill "/{context.matched_skill.get("name", "")}". '
        f'Follow the <mandatory-skill> instructions above precisely. '
        f'Use ONLY the declared tools: {", ".join(context.matched_skill.get("tools", []))}.'
        f'\n</skill-reminder>'
    )
    sections.append(reminder)
```

**Verification**:
- Tool descriptions in system prompt are limited to skill's tools when forced
- SubAgent section is omitted when forced
- Skill reminder appears at end of system prompt

---

### Fix 4: ReAct Loop Skill Reinforcement (MEDIUM PRIORITY)

**File**: `src/infrastructure/agent/processor/processor.py`
**Classes**: `ProcessorConfig` (line 224) and `SessionProcessor` (line 298)
**Effort**: Medium (30-50 lines across two locations)

**Change**: Add skill awareness to the SessionProcessor so it can inject reminders between ReAct steps.

**Step 4a: Extend ProcessorConfig** (after line 258):

```python
@dataclass
class ProcessorConfig:
    # ... existing fields ...
    
    # Forced skill context (optional)
    forced_skill_name: str | None = None
    forced_skill_tools: list[str] | None = None
```

**Step 4b: Store skill context in SessionProcessor.__init__** (after line 362):

```python
# Forced skill context for loop reinforcement
self._forced_skill_name = config.forced_skill_name
self._forced_skill_tools = set(config.forced_skill_tools) if config.forced_skill_tools else None
```

**Step 4c: Inject skill reminder in _process_step** (before LLM call, around line 1192):

```python
# Inject skill reminder for multi-step forced skill execution
if self._forced_skill_name and self._step_count > 1:
    skill_reminder = {
        "role": "system",
        "content": (
            f'[SKILL REMINDER] You are executing forced skill "/{self._forced_skill_name}". '
            f"Follow the skill instructions from the system prompt precisely. "
            + (
                f"Use ONLY these tools: {', '.join(sorted(self._forced_skill_tools))}."
                if self._forced_skill_tools
                else ""
            )
        ),
    }
    # Insert before the last message to keep it visible
    messages.append(skill_reminder)
```

**Step 4d: Pass skill context when creating processor** in `react_agent.py` (wherever `ProcessorConfig` is constructed for forced skills):

```python
processor_config = ProcessorConfig(
    # ... existing fields ...
    forced_skill_name=matched_skill.name if is_forced and matched_skill else None,
    forced_skill_tools=list(matched_skill.tools) if is_forced and matched_skill and matched_skill.tools else None,
)
```

**Verification**:
- Skill reminder message appears in messages list at step 2+
- Processor logs confirm skill-aware operation
- Multi-step skill executions stay on track

---

### Fix 5: REMOVED (True Direct Execution Path)

**Status**: Removed. Analysis determined this was a pseudo-requirement.

**Rationale**: Skills are not deterministic scripts. They require LLM judgment for error handling, context-dependent decisions, and adaptive tool usage. Bypassing the ReAct loop would require classifying skills as "deterministic" vs "adaptive", adding a `direct_execution` flag, and routing through `SkillExecutor` -- massive complexity for marginal gain. Fixes 1-4 + Fix 6 address all root causes by ensuring the ReAct loop respects skill constraints, making a bypass unnecessary.

---

### Fix 6: Compression Protection (LOW PRIORITY)

**File**: `src/infrastructure/agent/context/compression_engine.py`
**Effort**: Small (5-10 lines)

**Change**: Mark `<mandatory-skill>` blocks as non-compressible by checking for the sentinel tag before compression.

```python
# In compression method:
if "<mandatory-skill" in content:
    # Extract and preserve mandatory-skill block
    import re
    skill_block = re.search(
        r'(<mandatory-skill.*?</mandatory-skill>)',
        content,
        re.DOTALL,
    )
    if skill_block:
        preserved = skill_block.group(1)
        # Compress everything else
        rest = content[:skill_block.start()] + content[skill_block.end():]
        compressed_rest = self._compress(rest)
        return compressed_rest + "\n\n" + preserved
```

**Verification**:
- `<mandatory-skill>` block survives compression unchanged

---

## Implementation Priority

| Phase | Fixes | Expected Impact | Effort |
|-------|-------|----------------|--------|
| **Phase 1** (Immediate) | Fix 1 + Fix 2 | ~70% improvement | 2-3 hours |
| **Phase 2** (Short-term) | Fix 3 + Fix 4 | ~20% improvement | 3-4 hours |
| **Phase 3** (Medium-term) | Fix 6 | ~10% improvement | 2-3 hours |

### Phase 1 Rationale
Fix 1 (tool filtering) eliminates the primary escape route for the LLM. When the LLM can only see the skill's tools, it has no choice but to use them.

Fix 2 (system prompt protection) ensures skill instructions are never silently lost. Together, these two fixes address the two highest-impact root causes.

### Phase 2 Rationale
Fix 3 (prompt noise reduction) reduces the signal-to-noise ratio, making skill instructions more prominent.

Fix 4 (loop reinforcement) addresses the attention decay problem in multi-step executions. These fixes refine the experience.

### Phase 3 Rationale
Fix 6 (compression protection) is a defensive measure for edge cases in long conversations where context compression could alter skill instructions.

## Testing Strategy

### Unit Tests

1. **Tool Filtering Test**: Verify `_stream_prepare_tools()` filters tools correctly for forced skills
   - Skill with declared tools -> only declared + essential tools remain
   - Skill with empty tools -> fallback to full set minus skill_loader
   - Non-forced skill -> no filtering applied

2. **System Prompt Protection Test**: Verify `_trim_messages_to_input_limit()` protects mandatory-skill
   - System prompt with `<mandatory-skill>` is never deleted
   - Non-skill sections are trimmed first
   - System prompt without mandatory-skill follows existing behavior

3. **Prompt Construction Test**: Verify `_build_capability_sections()` reduces noise for forced skills
   - Tool descriptions limited to skill's declared tools
   - SubAgents section omitted
   - Skill reminder appears at prompt end

4. **Loop Reinforcement Test**: Verify skill reminders are injected in multi-step execution
   - No reminder at step 1
   - Reminder injected at step 2+
   - Reminder contains correct skill name and tools

### Integration Tests

1. **End-to-End Forced Skill**: Send a forced skill request and verify:
   - Tools available to LLM match skill's declared tools
   - System prompt contains `<mandatory-skill>` block
   - Multi-step execution stays on track

2. **Long Context Forced Skill**: Send a forced skill request with long conversation history and verify:
   - System prompt is preserved during trimming
   - Skill instructions survive context compression

## Rollback Plan

All fixes are additive and guarded by the `is_forced` condition. If any fix causes issues:

1. **Fix 1**: Revert `_stream_prepare_tools()` to only remove `skill_loader`
2. **Fix 2**: Revert `_trim_messages_to_input_limit()` to delete system message as before
3. **Fix 3**: Revert `_build_capability_sections()` to not filter tools in prompt
4. **Fix 4**: Set `forced_skill_name=None` in ProcessorConfig to disable reinforcement
5. **Fix 6**: Remove `<mandatory-skill>` preservation check in compression engine
No existing behavior for non-forced skills is modified by any of these fixes.

## Files Modified (Summary)

| File | Changes |
|------|---------|
| `src/infrastructure/agent/core/react_agent.py` | Tool filtering in `_stream_prepare_tools()`, pass skill context to ProcessorConfig |
| `src/infrastructure/llm/litellm/litellm_client.py` | Protect system prompt in `_trim_messages_to_input_limit()`, add `_trim_system_prompt_preserve_skill()` |
| `src/infrastructure/agent/prompts/manager.py` | Filter tool descriptions, skip subagents, add trailing skill reminder in `_build_capability_sections()` |
| `src/infrastructure/agent/processor/processor.py` | Add `forced_skill_name`/`forced_skill_tools` to ProcessorConfig, inject skill reminders in `_process_step()` |
| `src/infrastructure/agent/context/compression_engine.py` | Preserve `<mandatory-skill>` blocks during compression |
