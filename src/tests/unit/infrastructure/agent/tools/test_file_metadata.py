from src.infrastructure.agent.tools.file_metadata import build_sandbox_tool_metadata


def test_build_sandbox_tool_metadata_normalizes_read_file_metadata() -> None:
    metadata = build_sandbox_tool_metadata(
        tool_name="read",
        arguments={"file_path": "src/app.py", "_workspace_dir": "/workspace"},
        raw_result={
            "metadata": {
                "resolved_path": "/workspace/src/app.py",
                "workspace_root": "/workspace",
                "workspace_relative_path": "src/app.py",
                "total_lines": 20,
                "offset": 4,
                "lines_returned": 3,
            }
        },
        output="     5\tprint('hello')",
    )

    assert metadata["fileMetadata"]["operation"] == "read"
    assert metadata["fileMetadata"]["workspaceRoot"] == "/workspace"
    assert metadata["fileMetadata"]["truncated"] is True
    assert metadata["fileMetadata"]["paths"] == [
        {
            "path": "/workspace/src/app.py",
            "relativePath": "src/app.py",
            "language": "py",
            "lineCount": 20,
            "lineStart": 5,
            "lineEnd": 7,
        }
    ]


def test_build_sandbox_tool_metadata_normalizes_grep_matches() -> None:
    metadata = build_sandbox_tool_metadata(
        tool_name="grep",
        arguments={"pattern": "Agent"},
        raw_result={"metadata": {"matches_found": 1, "search_truncated": False}},
        output="src/app.py:12: class Agent:",
    )

    assert metadata["fileMetadata"]["operation"] == "search"
    assert metadata["fileMetadata"]["matchCount"] == 1
    assert metadata["fileMetadata"]["matches"] == [
        {"path": "src/app.py", "lineNumber": 12, "preview": "class Agent:"}
    ]


def test_build_sandbox_tool_metadata_keeps_bash_to_command_metadata_only() -> None:
    metadata = build_sandbox_tool_metadata(
        tool_name="bash",
        arguments={"command": "git status", "working_dir": "/workspace"},
        raw_result={"metadata": {"exit_code": 0, "working_dir": "/workspace"}},
        output="clean",
    )

    assert "fileMetadata" not in metadata
    assert metadata["commandMetadata"] == {
        "command": "git status",
        "cwd": "/workspace",
        "exitCode": 0,
        "status": "success",
        "outputBytes": 5,
    }
