"""Pure unified diff operations shared by the sandbox filesystem and the signed worker."""

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatchHunkLine:
    """Represents a single parsed line inside a unified diff hunk."""

    operation: str
    text: str
    has_newline: bool = True

    def render(self) -> str:
        """Render the line back into file content."""
        return self.text + ("\n" if self.has_newline else "")


@dataclass(frozen=True)
class PatchHunk:
    """Represents a parsed unified diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[PatchHunkLine]

    def to_dict(self) -> dict[str, Any]:
        """Convert hunk metadata into a JSON-friendly dictionary."""
        diff_lines: list[str] = []
        for line in self.lines:
            diff_lines.append(f"{line.operation}{line.text}")
            if not line.has_newline:
                diff_lines.append("\\ No newline at end of file")
        return {
            "old_start": self.old_start,
            "old_count": self.old_count,
            "new_start": self.new_start,
            "new_count": self.new_count,
            "lines": diff_lines,
        }


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)

def detect_line_ending(sample: str) -> str | None:
    """Return the dominant line ending in existing file text."""
    head = sample[:4096]
    if "\r\n" in head:
        return "\r\n"
    if "\n" in head:
        return "\n"
    return None


def normalize_line_endings(text: str, target: str | None) -> str:
    """Normalize text to the target line ending when one is known."""
    if target not in {"\n", "\r\n"}:
        return text
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if target == "\r\n":
        return normalized.replace("\n", "\r\n")
    return normalized


def _extract_patch_path(header_value: str) -> str | None:
    """Extract the normalized file path from a unified diff header."""
    raw_path = header_value.split("\t", 1)[0].strip()
    if raw_path == "/dev/null":
        return None
    return raw_path.replace("\\", "/")


def parse_unified_diff(patch_content: str, strip: int = 0) -> dict[str, Any]:
    """
    Parse unified diff format patch into hunks.

    Args:
        patch_content: Unified diff patch content
        strip: Number of path components to strip

    Returns:
        Parsed patch metadata
    """
    hunks: list[PatchHunk] = []
    lines = patch_content.splitlines()
    old_path: str | None = None
    new_path: str | None = None
    header_count = 0

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("--- "):
            header_count += 1
            old_path = _extract_patch_path(line[4:])
            i += 1
            if i < len(lines) and lines[i].startswith("+++ "):
                new_path = _extract_patch_path(lines[i][4:])
                i += 1
            continue

        # Look for hunk header: @@ -old_start,old_count +new_start,new_count @@
        match = _HUNK_HEADER_RE.match(line)
        if match:
            old_start = int(match.group("old_start"))
            old_count = int(match.group("old_count") or ("0" if old_start == 0 else "1"))
            new_start = int(match.group("new_start"))
            new_count = int(match.group("new_count") or ("0" if new_start == 0 else "1"))

            i += 1
            hunk_lines: list[PatchHunkLine] = []
            while i < len(lines):
                hunk_line = lines[i]
                if hunk_line.startswith("@@") or hunk_line.startswith("--- "):
                    break

                if hunk_line.startswith("\\ "):
                    if hunk_lines:
                        previous = hunk_lines[-1]
                        hunk_lines[-1] = PatchHunkLine(
                            operation=previous.operation,
                            text=previous.text,
                            has_newline=False,
                        )
                    i += 1
                    continue

                if hunk_line[:1] in {" ", "+", "-"}:
                    hunk_lines.append(
                        PatchHunkLine(
                            operation=hunk_line[0],
                            text=hunk_line[1:],
                        )
                    )
                    i += 1
                    continue

                break

            hunks.append(
                PatchHunk(
                    old_start=old_start - 1,
                    old_count=old_count,
                    new_start=new_start - 1,
                    new_count=new_count,
                    lines=hunk_lines,
                )
            )
            continue

        i += 1

    return {
        "old_path": old_path,
        "new_path": new_path,
        "header_count": header_count,
        "hunks": hunks,
    }


def apply_hunks(
    original_lines: list[str],
    hunks: list[PatchHunk],
) -> tuple[list[str], list[PatchHunk]]:
    """
    Apply hunks to file content.

    Args:
        original_lines: Original file lines
        hunks: List of parsed hunks

    Returns:
        Tuple of (new_lines, failed_hunks)
    """
    # Sort hunks by old_start (apply from bottom to top to avoid line number shifts)
    sorted_hunks = sorted(hunks, key=lambda h: h.old_start, reverse=True)

    result_lines = original_lines.copy()
    failed_hunks: list[PatchHunk] = []

    for hunk in sorted_hunks:
        old_lines_from_hunk = [line.render() for line in hunk.lines if line.operation in {" ", "-"}]
        replacement_start = _find_hunk_start(result_lines, hunk, old_lines_from_hunk)
        if replacement_start is None:
            failed_hunks.append(hunk)
            continue

        new_lines = [line.render() for line in hunk.lines if line.operation in {" ", "+"}]
        replacement_end = replacement_start + len(old_lines_from_hunk)
        result_lines[replacement_start:replacement_end] = new_lines

    return result_lines, failed_hunks


def _find_hunk_start(
    current_lines: list[str],
    hunk: PatchHunk,
    old_lines_from_hunk: list[str],
) -> int | None:
    """Find the line index where a hunk should apply."""
    expected_start = max(hunk.old_start, 0)
    expected_end = expected_start + len(old_lines_from_hunk)
    if current_lines[expected_start:expected_end] == old_lines_from_hunk:
        return expected_start

    if not old_lines_from_hunk:
        return min(expected_start, len(current_lines))

    search_starts = [expected_start]
    window = max(len(old_lines_from_hunk) + 3, 8)
    low = max(0, expected_start - window)
    high = min(len(current_lines) - len(old_lines_from_hunk), expected_start + window)
    search_starts.extend(range(low, high + 1))
    search_starts.extend(range(len(current_lines) - len(old_lines_from_hunk) + 1))

    seen: set[int] = set()
    for start in search_starts:
        if start in seen or start < 0:
            continue
        seen.add(start)
        end = start + len(old_lines_from_hunk)
        if current_lines[start:end] == old_lines_from_hunk:
            return start
    return None


def patch_text(content: str, patch: str) -> dict[str, str]:
    """Apply the same single-file patch to an explicit text snapshot."""
    parsed = parse_unified_diff(patch)
    if parsed["header_count"] != 1 or not parsed["hunks"]:
        raise ValueError("Expected one unified diff target with hunks")
    ending = detect_line_ending(content)
    lines = normalize_line_endings(content, "\n").splitlines(keepends=True)
    output, failed = apply_hunks(lines, parsed["hunks"])
    if failed:
        raise ValueError("Patch does not apply to the supplied content")
    return {"content": normalize_line_endings("".join(output), ending)}
