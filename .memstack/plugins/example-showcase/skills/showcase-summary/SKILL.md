---
name: showcase-summary
description: A summary skill that teaches the agent how to produce concise summaries.
trigger_patterns:
  - "summarize"
  - "summary"
  - "tldr"
  - "brief"
tools:
  - memory_search
user_invocable: true
---

# Summary Skill

Produce a concise summary of the provided content.

## Guidelines

- Keep summaries under 3 sentences unless the user requests more detail
- Preserve key facts, names, and numbers
- Use bullet points for multi-topic content
- Start with the most important information

## Output Format

**Summary:** <1-3 sentence summary>

**Key Points:**
- Point 1
- Point 2
