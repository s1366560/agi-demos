"""Refactor _extract_goal_json to reduce branches from 15 to <=12.

Strategy: Extract the inner brace-scanning logic into _scan_json_object()
which finds the end index of a balanced JSON object starting at start_idx,
and _try_parse_json_object() which attempts to parse the candidate.
"""

import sys

FILE = "src/infrastructure/agent/processor/processor.py"

# The replacement code for _extract_goal_json and two new helpers
NEW_CODE = [
    "    @staticmethod",
    "    def _find_json_object_end(text: str, start_idx: int) -> int | None:",
    '        """Find the end index (inclusive) of a balanced JSON object.',
    "",
    "        Scans from start_idx (which must be a '{') tracking brace depth",
    "        and string escaping. Returns the index of the closing '}' or None.",
    '        """',
    "        depth = 0",
    "        in_string = False",
    "        escape_next = False",
    "        for index in range(start_idx, len(text)):",
    "            char = text[index]",
    "",
    "            if in_string:",
    "                if escape_next:",
    "                    escape_next = False",
    '                elif char == "\\\\":',
    "                    escape_next = True",
    "                elif char == '\"':",
    "                    in_string = False",
    "                continue",
    "",
    "            if char == '\"':",
    "                in_string = True",
    '            elif char == "{":',
    "                depth += 1",
    '            elif char == "}":',
    "                depth -= 1",
    "                if depth == 0:",
    "                    return index",
    "        return None",
    "",
    "    @staticmethod",
    "    def _try_parse_json_dict(text: str) -> dict | None:",
    '        """Try to parse text as a JSON dict. Returns dict or None."""',
    "        try:",
    "            parsed = json.loads(text)",
    "        except json.JSONDecodeError:",
    "            return None",
    "        if isinstance(parsed, dict):",
    "            return parsed",
    "        return None",
    "",
    "    def _extract_goal_json(self, text: str) -> dict[str, Any] | None:",
    '        """Extract goal-check JSON object from model text."""',
    "        stripped = text.strip()",
    "        if not stripped:",
    "            return None",
    "",
    "        result = self._try_parse_json_dict(stripped)",
    "        if result is not None:",
    "            return result",
    "",
    '        start_idx = stripped.find("{")',
    "        while start_idx >= 0:",
    "            end_idx = self._find_json_object_end(stripped, start_idx)",
    "            if end_idx is not None:",
    "                candidate = stripped[start_idx : end_idx + 1]",
    "                result = self._try_parse_json_dict(candidate)",
    "                if result is not None:",
    "                    return result",
    '            start_idx = stripped.find("{", start_idx + 1)',
    "",
    "        return None",
]


def main() -> int:
    with open(FILE, "r") as f:
        lines = f.read().split("\n")

    # Find _extract_goal_json start
    target_sig = "    def _extract_goal_json(self, text: str)"
    start_idx = None
    for i, line in enumerate(lines):
        if target_sig in line:
            start_idx = i
            break

    if start_idx is None:
        print(f"ERROR: Could not find '{target_sig}'")
        return 1

    # Find end: next method at same indentation level (4 spaces)
    end_idx = None
    for i in range(start_idx + 1, len(lines)):
        stripped = lines[i]
        if stripped.startswith("    def ") and not stripped.startswith("        "):
            end_idx = i
            break

    if end_idx is None:
        print("ERROR: Could not find end of _extract_goal_json")
        return 1

    print(f"Found _extract_goal_json at lines {start_idx + 1}-{end_idx}")
    print(f"Original length: {end_idx - start_idx} lines")

    # Replace
    new_lines = lines[:start_idx] + NEW_CODE + [""] + lines[end_idx:]

    with open(FILE, "w") as f:
        f.write("\n".join(new_lines))

    print(f"New length: {len(NEW_CODE)} lines")
    print("Replacement complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
