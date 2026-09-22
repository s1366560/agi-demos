//! Structured presentation metadata for local-runtime timeline tool events.

use serde_json::{json, Value};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum TimelineToolKind {
    Search,
    Read,
    Command,
    Edit,
    Check,
    Tool,
}

impl TimelineToolKind {
    pub(super) const fn as_str(self) -> &'static str {
        match self {
            Self::Search => "search",
            Self::Read => "read",
            Self::Command => "command",
            Self::Edit => "edit",
            Self::Check => "check",
            Self::Tool => "tool",
        }
    }
}

pub(super) fn tool_kind(tool: &str) -> TimelineToolKind {
    if SEARCH_TOOLS.contains(&tool) {
        TimelineToolKind::Search
    } else if READ_TOOLS.contains(&tool) {
        TimelineToolKind::Read
    } else if COMMAND_TOOLS.contains(&tool) {
        TimelineToolKind::Command
    } else if EDIT_TOOLS.contains(&tool) {
        TimelineToolKind::Edit
    } else if CHECK_TOOLS.contains(&tool) {
        TimelineToolKind::Check
    } else {
        TimelineToolKind::Tool
    }
}

pub(super) fn display(tool: &str) -> Value {
    json!({ "kind": tool_kind(tool).as_str() })
}

/// Only protocol-level status fields determine failure, never prose in tool content.
pub(super) fn tool_result_is_error(output_json: &str) -> bool {
    let Ok(value) = serde_json::from_str::<Value>(output_json) else {
        return false;
    };
    value.get("isError").and_then(Value::as_bool) == Some(true)
        || value.get("is_error").and_then(Value::as_bool) == Some(true)
        || value.get("success").and_then(Value::as_bool) == Some(false)
        || value.get("error").is_some_and(|error| {
            error.as_str().is_some_and(|text| !text.trim().is_empty()) || error.is_object()
        })
}

/// These first-party tools share adapters-local-tools::input_path's schema.
/// Inspect the already-redacted input; never infer paths from output prose.
pub(super) fn input_file_metadata(tool: &str, input_json: &str) -> Option<Value> {
    if !matches!(tool, "read" | "write" | "edit") {
        return None;
    }
    let input = serde_json::from_str::<Value>(input_json).ok()?;
    let path = ["path", "file_path", "filename", "file"]
        .iter()
        .find_map(|key| {
            input
                .get(*key)
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|path| !path.is_empty())
        })?;
    Some(json!({ "paths": [{ "path": path }] }))
}

pub(super) fn file_metadata(output_json: &str) -> Option<Value> {
    let value = serde_json::from_str::<Value>(output_json).ok()?;
    diff_stat(&value, 0).map(|stat| {
        json!({
            "diffStat": {
                "filesChanged": stat.files_changed,
                "additions": stat.additions,
                "deletions": stat.deletions,
            }
        })
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct DiffStat {
    files_changed: u64,
    additions: u64,
    deletions: u64,
}

fn diff_stat(value: &Value, depth: usize) -> Option<DiffStat> {
    if depth > 3 {
        return None;
    }
    let object = value.as_object()?;
    if let Some(metadata) = object
        .get("fileMetadata")
        .or_else(|| object.get("file_metadata"))
    {
        return diff_stat(metadata, depth + 1);
    }
    if let Some(stat) = object.get("diffStat").or_else(|| object.get("diff_stat")) {
        return diff_stat(stat, depth + 1);
    }
    if let Some(output) = object
        .get("toolOutput")
        .or_else(|| object.get("tool_output"))
    {
        return diff_stat(output, depth + 1);
    }
    if let Some(content) = object.get("content").and_then(Value::as_array) {
        for block in content {
            let Some(text) = block.get("text").and_then(Value::as_str) else {
                continue;
            };
            let Ok(nested) = serde_json::from_str::<Value>(text) else {
                continue;
            };
            if let Some(stat) = diff_stat(&nested, depth + 1) {
                return Some(stat);
            }
        }
    }

    let additions = unsigned(object.get("additions"))?;
    let deletions = unsigned(object.get("deletions"))?;
    let files_changed = unsigned(
        object
            .get("filesChanged")
            .or_else(|| object.get("files_changed")),
    )
    .unwrap_or(0);
    Some(DiffStat {
        files_changed,
        additions,
        deletions,
    })
}

fn unsigned(value: Option<&Value>) -> Option<u64> {
    value.and_then(Value::as_u64)
}

const SEARCH_TOOLS: &[&str] = &[
    "glob",
    "grep",
    "search_files",
    "ast_find_symbols",
    "find_definition",
    "find_references",
    "call_graph",
    "dependency_graph",
];

const READ_TOOLS: &[&str] = &[
    "read",
    "read_file",
    "read_code",
    "batch_read",
    "list",
    "list_artifacts",
    "ast_parse",
    "ast_extract_function",
    "ast_get_imports",
    "git_diff",
    "git_log",
    "get_terminal_status",
    "get_desktop_status",
];

const COMMAND_TOOLS: &[&str] = &[
    "bash",
    "shell_command",
    "start_terminal",
    "stop_terminal",
    "restart_terminal",
    "start_desktop",
    "stop_desktop",
    "change_resolution",
    "restart_desktop",
    "deps_check",
    "deps_install",
];

const EDIT_TOOLS: &[&str] = &[
    "write",
    "edit",
    "patch",
    "apply_patch",
    "export_artifact",
    "batch_export_artifacts",
    "edit_by_ast",
    "batch_edit",
    "generate_tests",
    "generate_commit",
    "import_file",
    "import_files_batch",
];

const CHECK_TOOLS: &[&str] = &["run_tests", "analyze_coverage"];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn input_file_paths_follow_declared_first_party_schema() {
        assert_eq!(
            input_file_metadata("read", r#"{"path":"src/main.rs","file":"other"}"#),
            Some(json!({"paths":[{"path":"src/main.rs"}]}))
        );
        assert_eq!(
            input_file_metadata("edit", r#"{"file":"README.md"}"#),
            Some(json!({"paths":[{"path":"README.md"}]}))
        );
        assert_eq!(
            input_file_metadata("plugin__read", r#"{"path":"private"}"#),
            None
        );
        assert_eq!(
            input_file_metadata("read", r#"{"content":"src/main.rs"}"#),
            None
        );
    }

    #[test]
    fn result_status_preserves_explicit_todowrite_failure() {
        assert!(tool_result_is_error(
            r#"{"success":false,"code":"PLAN_EXECUTION_NOT_APPROVED","error":"Plan mode requires approval"}"#
        ));
        assert!(tool_result_is_error(r#"{"success":false}"#));
        assert!(tool_result_is_error(r#"{"error":{"code":"DENIED"}}"#));
        assert!(tool_result_is_error(r#"{"error":"Denied"}"#));
        assert!(!tool_result_is_error(r#"{"success":"false","error":null}"#));
        assert!(!tool_result_is_error(r#"{"nested":{"success":false}}"#));
    }

    #[test]
    fn result_status_uses_only_envelope_boolean_flags() {
        assert!(tool_result_is_error(r#"{"isError":true}"#));
        assert!(tool_result_is_error(r#"{"is_error":true}"#));
        assert!(tool_result_is_error(r#"{"isError":false,"is_error":true}"#));
        for output in [
            "error",
            r#"{"isError":"true"}"#,
            r#"{"content":[{"text":"error"}],"isError":false}"#,
            r#"{"data":{"isError":true}}"#,
        ] {
            assert!(!tool_result_is_error(output), "{output}");
        }
    }

    #[test]
    fn tool_kind_uses_declared_tool_membership() {
        assert_eq!(tool_kind("grep"), TimelineToolKind::Search);
        assert_eq!(tool_kind("read"), TimelineToolKind::Read);
        assert_eq!(tool_kind("bash"), TimelineToolKind::Command);
        assert_eq!(tool_kind("patch"), TimelineToolKind::Edit);
        assert_eq!(tool_kind("run_tests"), TimelineToolKind::Check);
        assert_eq!(tool_kind("grep-like-unknown-tool"), TimelineToolKind::Tool);
    }

    #[test]
    fn file_metadata_normalizes_snake_case_diff_stats() {
        assert_eq!(
            file_metadata(r#"{"files_changed":4,"additions":138,"deletions":29}"#),
            Some(json!({
                "diffStat": { "filesChanged": 4, "additions": 138, "deletions": 29 }
            }))
        );
    }

    #[test]
    fn file_metadata_reads_structured_text_from_tool_result_envelope() {
        assert_eq!(
            file_metadata(
                r#"{"content":[{"type":"text","text":"{\"files_changed\":2,\"additions\":28,\"deletions\":9}"}]}"#,
            ),
            Some(json!({
                "diffStat": { "filesChanged": 2, "additions": 28, "deletions": 9 }
            }))
        );
    }

    #[test]
    fn file_metadata_ignores_unstructured_output() {
        assert_eq!(file_metadata("patch applied"), None);
        assert_eq!(file_metadata(r#"{"message":"patch applied"}"#), None);
    }
}
