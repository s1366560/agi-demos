#!/usr/bin/env python3
"""Refactor _evaluate_llm_goal() to reduce branches from 13 to <=12.

Extract helpers:
- _extract_llm_response_content() -> str
- _coerce_goal_achieved_bool() -> bool | None
"""

import sys

PROCESSOR_PATH = "src/infrastructure/agent/processor/processor.py"


def main():
    with open(PROCESSOR_PATH, "r") as f:
        content = f.read()
    lines = content.split("\n")

    # Find _evaluate_llm_goal method start and end
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if "async def _evaluate_llm_goal(" in line:
            start_idx = i
        if start_idx is not None and i > start_idx:
            stripped = line.strip()
            # Next method at same indentation level
            if (
                stripped.startswith("def ") or stripped.startswith("async def ")
            ) and i > start_idx + 2:
                end_idx = i
                break

    if start_idx is None or end_idx is None:
        print(
            f"ERROR: Could not find _evaluate_llm_goal() boundaries. start={start_idx}, end={end_idx}"
        )
        sys.exit(1)

    print(f"Found _evaluate_llm_goal() at lines {start_idx + 1}-{end_idx} (0-indexed)")

    replacement = [
        "    async def _evaluate_llm_goal(self, messages: list[dict[str, Any]]) -> GoalCheckResult:",
        '        """Evaluate completion using explicit LLM self-check in no-task mode."""',
        "        fallback = self._evaluate_goal_from_latest_text()",
        "        if self._llm_client is None:",
        "            return fallback",
        "",
        "        context_summary = self._build_goal_check_context(messages)",
        "        if not context_summary:",
        "            return fallback",
        "",
        "        content = await self._call_goal_check_llm(context_summary)",
        "        if content is None:",
        "            return fallback",
        "",
        "        parsed = self._extract_goal_json(content)",
        "        if parsed is None:",
        "            parsed = self._extract_goal_from_plain_text(content)",
        "        if parsed is None:",
        "            logger.debug(",
        '                "[Processor] Goal self-check payload not parseable, using fallback: %s",',
        "                content[:200],",
        "            )",
        "            return fallback",
        "",
        '        achieved = self._coerce_goal_achieved_bool(parsed.get("goal_achieved"))',
        "        if achieved is None:",
        '            logger.debug("[Processor] Goal self-check missing boolean goal_achieved")',
        "            return fallback",
        "",
        '        reason = str(parsed.get("reason", "")).strip()',
        "        return GoalCheckResult(",
        "            achieved=achieved,",
        '            reason=reason or ("Goal achieved" if achieved else "Goal not achieved"),',
        '            source="llm_self_check",',
        "        )",
        "",
        "    async def _call_goal_check_llm(self, context_summary: str) -> str | None:",
        '        """Call LLM for goal check and return content string, or None on failure."""',
        "        try:",
        "            response = await self._llm_client.generate(",
        "                messages=[",
        "                    {",
        '                        "role": "system",',
        '                        "content": (',
        '                            "You are a strict completion checker. "',
        '                            "Return ONLY JSON object: "',
        '                            \'{"goal_achieved": boolean, "reason": string}. \'',
        '                            "Use goal_achieved=true only when user objective is fully satisfied."',
        "                        ),",
        "                    },",
        '                    {"role": "user", "content": context_summary},',
        "                ],",
        "                temperature=0.0,",
        "                max_tokens=120,",
        "            )",
        "        except Exception as exc:",
        '            logger.warning(f"[Processor] LLM goal self-check failed: {exc}")',
        "            return None",
        "",
        "        if isinstance(response, dict):",
        '            return str(response.get("content", "") or "")',
        "        if isinstance(response, str):",
        "            return response",
        "        return str(response)",
        "",
        "    @staticmethod",
        "    def _coerce_goal_achieved_bool(value: Any) -> bool | None:",
        '        """Coerce a goal_achieved value to bool, or return None if not possible."""',
        "        if isinstance(value, bool):",
        "            return value",
        "        if isinstance(value, str):",
        "            lowered = value.strip().lower()",
        '            if lowered in {"true", "yes", "1"}:',
        "                return True",
        '            if lowered in {"false", "no", "0"}:',
        "                return False",
        "        return None",
        "",
    ]

    new_lines = lines[:start_idx] + replacement + lines[end_idx:]

    with open(PROCESSOR_PATH, "w") as f:
        f.write("\n".join(new_lines))

    print(f"Replaced lines {start_idx + 1}-{end_idx} with {len(replacement)} lines")
    print("Done!")


if __name__ == "__main__":
    main()
