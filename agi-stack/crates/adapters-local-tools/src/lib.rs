//! Native local tools for the desktop Agent runtime.
//!
//! This crate is intentionally adapter-only: it depends on Tokio/process/FS
//! APIs and implements the existing runtime-agnostic [`ToolHost`] port without
//! leaking those dependencies into `agistack-core`.

use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    path::{Component, Path, PathBuf},
    process::Stdio,
    sync::{Arc, Mutex},
    time::Duration,
};

use agistack_core::ports::{CoreError, CoreResult, ToolHost};
use async_trait::async_trait;
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::{
    fs,
    io::{AsyncRead, AsyncReadExt, AsyncWriteExt},
    process::Command,
    time::{self, Instant},
};
use uuid::Uuid;
use walkdir::WalkDir;

const MAX_TEXT_BYTES: usize = 64 * 1024;
const DEFAULT_TIMEOUT_MS: u64 = 30_000;

/// Python `sandbox-mcp-server` tool registry names, kept as the desktop parity
/// gate. The legacy plan text said 48 tools; the registry and docs contain 52.
pub const PYTHON_TOOL_NAMES: &[&str] = &[
    "read",
    "batch_read",
    "write",
    "edit",
    "glob",
    "grep",
    "list",
    "patch",
    "export_artifact",
    "list_artifacts",
    "batch_export_artifacts",
    "bash",
    "ast_parse",
    "ast_find_symbols",
    "ast_extract_function",
    "ast_get_imports",
    "code_index_build",
    "find_definition",
    "find_references",
    "call_graph",
    "dependency_graph",
    "edit_by_ast",
    "batch_edit",
    "preview_edit",
    "generate_tests",
    "run_tests",
    "analyze_coverage",
    "git_diff",
    "git_log",
    "generate_commit",
    "start_terminal",
    "stop_terminal",
    "get_terminal_status",
    "restart_terminal",
    "start_desktop",
    "stop_desktop",
    "get_desktop_status",
    "change_resolution",
    "restart_desktop",
    "import_file",
    "import_files_batch",
    "mcp_server_install",
    "mcp_server_start",
    "mcp_server_stop",
    "mcp_server_list",
    "mcp_server_discover_tools",
    "mcp_server_call_tool",
    "mcp_server_list_prompts",
    "mcp_server_set_log_level",
    "deps_install",
    "deps_check",
    "plugin_tool_exec",
];

fn is_agent_tool_name(name: &str) -> bool {
    !name.starts_with("mcp_server_") && name != "plugin_tool_exec"
}

/// Tool metadata exposed through MCP `tools/list`.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LocalToolMetadata {
    pub name: String,
    pub description: String,
    #[serde(rename = "inputSchema")]
    pub input_schema: Value,
}

/// MCP-compatible tool result shape.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct McpToolResult {
    pub content: Vec<McpContent>,
    #[serde(rename = "isError")]
    pub is_error: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct McpContent {
    #[serde(rename = "type")]
    pub kind: String,
    pub text: String,
}

/// Local tool execution trait. The host registers one implementation per
/// metadata entry, so `ToolHost` and MCP `tools/call` share the same dispatch.
#[async_trait]
pub trait LocalTool: Send + Sync {
    fn metadata(&self) -> &LocalToolMetadata;
    async fn call(&self, input: Value, runtime: Arc<LocalToolRuntime>) -> McpToolResult;
}

/// Native local runtime state shared by all local tools.
#[derive(Debug)]
pub struct LocalToolRuntime {
    workspace_root: PathBuf,
    artifacts_root: PathBuf,
    terminals: Mutex<HashMap<String, TerminalSession>>,
    desktop: Mutex<DesktopState>,
    mcp_servers: Mutex<HashMap<String, McpServerRecord>>,
}

impl LocalToolRuntime {
    pub fn new(workspace_root: impl Into<PathBuf>) -> CoreResult<Self> {
        let workspace_root = workspace_root.into();
        std::fs::create_dir_all(&workspace_root).map_err(to_tool)?;
        let workspace_root = workspace_root.canonicalize().map_err(to_tool)?;
        let artifacts_root = workspace_root.join(".agistack").join("artifacts");
        std::fs::create_dir_all(&artifacts_root).map_err(to_tool)?;
        Ok(Self {
            workspace_root,
            artifacts_root,
            terminals: Mutex::new(HashMap::new()),
            desktop: Mutex::new(DesktopState::default()),
            mcp_servers: Mutex::new(HashMap::new()),
        })
    }

    pub fn workspace_root(&self) -> &Path {
        &self.workspace_root
    }

    pub fn artifacts_root(&self) -> &Path {
        &self.artifacts_root
    }

    fn resolve_existing_path(&self, raw: &str) -> Result<PathBuf, String> {
        let path = self.resolve_lexical_path(raw)?;
        self.reject_symlink_components(&path, raw)?;
        let canonical = path.canonicalize().map_err(|error| {
            format!(
                "path '{}' is not readable inside workspace '{}': {error}",
                raw,
                self.workspace_root.display()
            )
        })?;
        if canonical.starts_with(&self.workspace_root) {
            Ok(canonical)
        } else {
            Err(format!("path escape rejected: {raw}"))
        }
    }

    fn resolve_write_path(&self, raw: &str) -> Result<PathBuf, String> {
        let path = self.resolve_lexical_path(raw)?;
        self.reject_symlink_components(&path, raw)?;
        let parent = path
            .parent()
            .ok_or_else(|| format!("path has no parent: {raw}"))?;
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        self.reject_symlink_components(&path, raw)?;
        let parent = parent
            .canonicalize()
            .map_err(|error| format!("cannot resolve parent for '{raw}': {error}"))?;
        if !parent.starts_with(&self.workspace_root) {
            return Err(format!("path escape rejected: {raw}"));
        }
        let name = path
            .file_name()
            .ok_or_else(|| format!("path has no file name: {raw}"))?;
        Ok(parent.join(name))
    }

    fn resolve_dir_path(&self, raw: Option<&str>) -> Result<PathBuf, String> {
        let raw = raw.unwrap_or(".");
        let path = self.resolve_lexical_path(raw)?;
        if !path.exists() {
            return Err(format!("directory does not exist: {raw}"));
        }
        self.reject_symlink_components(&path, raw)?;
        let canonical = path
            .canonicalize()
            .map_err(|error| format!("cannot resolve directory '{raw}': {error}"))?;
        if canonical.starts_with(&self.workspace_root) {
            Ok(canonical)
        } else {
            Err(format!("path escape rejected: {raw}"))
        }
    }

    fn resolve_cwd_path(&self, raw: Option<&str>) -> Result<PathBuf, String> {
        self.resolve_dir_path(raw)
    }

    fn resolve_lexical_path(&self, raw: &str) -> Result<PathBuf, String> {
        let input = Path::new(raw);
        let relative = if input.is_absolute() {
            input
                .strip_prefix(&self.workspace_root)
                .map_err(|_| format!("path escape rejected: {raw}"))?
        } else {
            input
        };
        let mut normalized = PathBuf::new();
        for component in relative.components() {
            match component {
                Component::CurDir => {}
                Component::Normal(part) => normalized.push(part),
                Component::ParentDir => {
                    if !normalized.pop() {
                        return Err(format!("path escape rejected: {raw}"));
                    }
                }
                Component::RootDir | Component::Prefix(_) => {
                    return Err(format!("path escape rejected: {raw}"));
                }
            }
        }
        Ok(self.workspace_root.join(normalized))
    }

    fn reject_symlink_components(&self, path: &Path, raw: &str) -> Result<(), String> {
        let relative = path
            .strip_prefix(&self.workspace_root)
            .map_err(|_| format!("path escape rejected: {raw}"))?;
        let mut current = self.workspace_root.clone();
        for component in relative.components() {
            let Component::Normal(part) = component else {
                return Err(format!("path escape rejected: {raw}"));
            };
            current.push(part);
            match std::fs::symlink_metadata(&current) {
                Ok(metadata) if metadata.file_type().is_symlink() => {
                    return Err(format!("symlink path rejected: {raw}"));
                }
                Ok(_) => {}
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => break,
                Err(error) => return Err(error.to_string()),
            }
        }
        Ok(())
    }
}

/// ToolHost implementation used by the desktop ReAct engine and MCP wrappers.
#[derive(Clone)]
pub struct LocalToolHost {
    runtime: Arc<LocalToolRuntime>,
    tools: Arc<BTreeMap<String, Arc<dyn LocalTool>>>,
}

impl LocalToolHost {
    pub fn new(workspace_root: impl Into<PathBuf>) -> CoreResult<Self> {
        Self::with_runtime(Arc::new(LocalToolRuntime::new(workspace_root)?))
    }

    pub fn with_runtime(runtime: Arc<LocalToolRuntime>) -> CoreResult<Self> {
        let mut tools: BTreeMap<String, Arc<dyn LocalTool>> = BTreeMap::new();
        for name in PYTHON_TOOL_NAMES {
            let tool: Arc<dyn LocalTool> = Arc::new(DispatchTool::new(name));
            tools.insert((*name).to_string(), tool);
        }
        Ok(Self {
            runtime,
            tools: Arc::new(tools),
        })
    }

    pub fn runtime(&self) -> Arc<LocalToolRuntime> {
        Arc::clone(&self.runtime)
    }

    pub fn list_tool_metadata(&self) -> Vec<LocalToolMetadata> {
        PYTHON_TOOL_NAMES
            .iter()
            .filter_map(|name| self.tools.get(*name))
            .map(|tool| tool.metadata().clone())
            .collect()
    }

    pub fn mcp_tools_list_result(&self) -> Value {
        json!({ "tools": self.list_tool_metadata() })
    }

    pub async fn mcp_tools_call_result(&self, name: &str, arguments: Value) -> McpToolResult {
        match self.tools.get(name) {
            Some(tool) => tool.call(arguments, self.runtime()).await,
            None => mcp_error(format!("unknown tool: {name}")),
        }
    }
}

#[async_trait]
impl ToolHost for LocalToolHost {
    fn list_tools(&self) -> Vec<String> {
        PYTHON_TOOL_NAMES
            .iter()
            .filter(|name| is_agent_tool_name(name))
            .map(|name| (*name).to_string())
            .collect()
    }

    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String> {
        if !is_agent_tool_name(tool) {
            return Err(CoreError::Tool(format!(
                "tool '{tool}' is not available to local agents"
            )));
        }
        let input = serde_json::from_str(input_json).map_err(to_tool)?;
        let result = self.mcp_tools_call_result(tool, input).await;
        if result.is_error {
            let message = result
                .content
                .first()
                .map(|content| content.text.clone())
                .unwrap_or_else(|| "local tool failed".to_string());
            return Err(CoreError::Tool(message));
        }
        serde_json::to_string(&result).map_err(to_tool)
    }
}

struct DispatchTool {
    metadata: LocalToolMetadata,
}

impl DispatchTool {
    fn new(name: &str) -> Self {
        Self {
            metadata: LocalToolMetadata {
                name: name.to_string(),
                description: description_for(name).to_string(),
                input_schema: schema_for(name),
            },
        }
    }
}

#[async_trait]
impl LocalTool for DispatchTool {
    fn metadata(&self) -> &LocalToolMetadata {
        &self.metadata
    }

    async fn call(&self, input: Value, runtime: Arc<LocalToolRuntime>) -> McpToolResult {
        let started = Instant::now();
        let output = match self.metadata.name.as_str() {
            "read" => read_tool(input, runtime).await,
            "batch_read" => batch_read_tool(input, runtime).await,
            "write" => write_tool(input, runtime).await,
            "edit" => edit_tool(input, runtime, false).await,
            "glob" => glob_tool(input, runtime).await,
            "grep" => grep_tool(input, runtime).await,
            "list" => list_tool(input, runtime).await,
            "patch" => patch_tool(input, runtime).await,
            "export_artifact" => export_artifact_tool(input, runtime).await,
            "list_artifacts" => list_artifacts_tool(runtime).await,
            "batch_export_artifacts" => batch_export_artifacts_tool(input, runtime).await,
            "bash" => bash_tool(input, runtime).await,
            "ast_parse" => ast_parse_tool(input, runtime).await,
            "ast_find_symbols" => ast_find_symbols_tool(input, runtime).await,
            "ast_extract_function" => ast_extract_function_tool(input, runtime).await,
            "ast_get_imports" => ast_get_imports_tool(input, runtime).await,
            "code_index_build" => code_index_build_tool(input, runtime).await,
            "find_definition" => find_definition_tool(input, runtime).await,
            "find_references" => find_references_tool(input, runtime).await,
            "call_graph" => call_graph_tool(input, runtime).await,
            "dependency_graph" => dependency_graph_tool(input, runtime).await,
            "edit_by_ast" => edit_by_ast_tool(input, runtime).await,
            "batch_edit" => batch_edit_tool(input, runtime).await,
            "preview_edit" => edit_tool(input, runtime, true).await,
            "generate_tests" => generate_tests_tool(input, runtime).await,
            "run_tests" => run_tests_tool(input, runtime).await,
            "analyze_coverage" => analyze_coverage_tool(input, runtime).await,
            "git_diff" => git_diff_tool(input, runtime).await,
            "git_log" => git_log_tool(input, runtime).await,
            "generate_commit" => generate_commit_tool(input, runtime).await,
            "start_terminal" => start_terminal_tool(input, runtime).await,
            "stop_terminal" => stop_terminal_tool(input, runtime).await,
            "get_terminal_status" => get_terminal_status_tool(input, runtime).await,
            "restart_terminal" => restart_terminal_tool(input, runtime).await,
            "start_desktop" => start_desktop_tool(input, runtime).await,
            "stop_desktop" => stop_desktop_tool(runtime).await,
            "get_desktop_status" => get_desktop_status_tool(runtime).await,
            "change_resolution" => change_resolution_tool(input, runtime).await,
            "restart_desktop" => restart_desktop_tool(input, runtime).await,
            "import_file" => import_file_tool(input, runtime).await,
            "import_files_batch" => import_files_batch_tool(input, runtime).await,
            "mcp_server_install" => mcp_server_install_tool(input, runtime).await,
            "mcp_server_start" => mcp_server_start_tool(input, runtime).await,
            "mcp_server_stop" => mcp_server_stop_tool(input, runtime).await,
            "mcp_server_list" => mcp_server_list_tool(runtime).await,
            "mcp_server_discover_tools" => mcp_server_discover_tools_tool(input, runtime).await,
            "mcp_server_call_tool" => mcp_server_call_tool(input, runtime).await,
            "mcp_server_list_prompts" => mcp_server_list_prompts_tool(input, runtime).await,
            "mcp_server_set_log_level" => mcp_server_set_log_level_tool(input, runtime).await,
            "deps_install" => deps_install_tool(input, runtime).await,
            "deps_check" => deps_check_tool(input, runtime).await,
            "plugin_tool_exec" => plugin_tool_exec_tool(input, runtime).await,
            _ => Err(format!("unknown tool: {}", self.metadata.name)),
        };
        match output {
            Ok(value) => mcp_json(value_with_elapsed(value, started)),
            Err(error) => mcp_error(error),
        }
    }
}

fn description_for(name: &str) -> &'static str {
    match name {
        "read" => "Read a workspace file.",
        "batch_read" => "Read multiple workspace files.",
        "write" => "Write a workspace file.",
        "edit" => "Replace text in a workspace file.",
        "glob" => "Match workspace paths by glob pattern.",
        "grep" => "Search workspace files by regular expression.",
        "list" => "List workspace directory entries.",
        "patch" => "Apply a unified diff inside the workspace.",
        "export_artifact" => {
            "Export an immutable artifact version. Reuse artifact_id when publishing a new version."
        }
        "list_artifacts" => "List exported immutable artifact versions.",
        "batch_export_artifacts" => "Export multiple immutable artifact versions.",
        "bash" => "Run a shell command inside the workspace.",
        _ => "Desktop local MCP-compatible tool.",
    }
}

fn schema_for(name: &str) -> Value {
    let mut properties = serde_json::Map::new();
    let mut required = Vec::new();

    match name {
        "read" | "write" | "edit" | "import_file" => {
            properties.insert("path".into(), json!({ "type": "string" }));
            required.push("path");
        }
        "batch_read" => {
            properties.insert(
                "paths".into(),
                json!({ "type": "array", "items": { "type": "string" } }),
            );
            required.push("paths");
        }
        "glob" => {
            properties.insert("pattern".into(), json!({ "type": "string" }));
            required.push("pattern");
        }
        "grep" => {
            properties.insert("pattern".into(), json!({ "type": "string" }));
            required.push("pattern");
        }
        "export_artifact" => {
            properties.insert("artifact_id".into(), json!({ "type": "string" }));
            properties.insert("filename".into(), json!({ "type": "string" }));
            properties.insert("content".into(), json!({ "type": "string" }));
            properties.insert("mime_type".into(), json!({ "type": "string" }));
            properties.insert("sources".into(), json!({ "type": "array" }));
            properties.insert("checks".into(), json!({ "type": "array" }));
            required.extend(["filename", "content"]);
        }
        "batch_export_artifacts" => {
            properties.insert(
                "artifacts".into(),
                json!({ "type": "array", "items": { "type": "object" } }),
            );
            required.push("artifacts");
        }
        "bash" | "deps_install" | "deps_check" | "plugin_tool_exec" => {
            properties.insert("command".into(), json!({ "type": "string" }));
            required.push("command");
        }
        "find_definition" | "find_references" | "call_graph" => {
            properties.insert("symbol".into(), json!({ "type": "string" }));
            required.push("symbol");
        }
        _ => {}
    }

    json!({
        "type": "object",
        "additionalProperties": true,
        "properties": properties,
        "required": required,
    })
}

async fn read_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let path = input_path(&input)?;
    let absolute = runtime.resolve_existing_path(&path)?;
    let bytes = fs::read(&absolute)
        .await
        .map_err(|error| error.to_string())?;
    let text = String::from_utf8_lossy(&bytes).to_string();
    let offset = usize_field(&input, "offset").unwrap_or(0);
    let limit = usize_field(&input, "limit").unwrap_or(text.len());
    let sliced = slice_chars(&text, offset, limit);
    Ok(json!({
        "path": path,
        "absolute_path": absolute,
        "content": sliced,
        "bytes": bytes.len(),
        "truncated": text.len() > sliced.len(),
    }))
}

async fn batch_read_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let paths = array_strings(&input, "paths")?;
    let mut files = Vec::new();
    for path in paths {
        let result = read_tool(json!({ "path": path }), Arc::clone(&runtime)).await;
        files.push(match result {
            Ok(value) => value,
            Err(error) => json!({ "path": path, "error": error }),
        });
    }
    Ok(json!({ "files": files }))
}

async fn write_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let path = input_path(&input)?;
    let content = string_any(&input, &["content", "text", "data"])?;
    let absolute = runtime.resolve_write_path(&path)?;
    let existed_before = absolute.exists();
    fs::write(&absolute, content.as_bytes())
        .await
        .map_err(|error| error.to_string())?;
    Ok(json!({
        "path": path,
        "absolute_path": absolute,
        "bytes_written": content.len(),
        "created": !existed_before,
    }))
}

async fn edit_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
    preview: bool,
) -> Result<Value, String> {
    let path = input_path(&input)?;
    let old_text = string_any(&input, &["old_text", "old", "target"])?;
    let new_text = string_any(&input, &["new_text", "new", "replacement"])?;
    let all = bool_field(&input, "replace_all").unwrap_or(false);
    let absolute = runtime.resolve_existing_path(&path)?;
    let content = fs::read_to_string(&absolute)
        .await
        .map_err(|error| error.to_string())?;
    if !content.contains(&old_text) {
        return Err(format!("target text not found in {path}"));
    }
    let changed = if all {
        content.replace(&old_text, &new_text)
    } else {
        content.replacen(&old_text, &new_text, 1)
    };
    if !preview {
        fs::write(&absolute, changed.as_bytes())
            .await
            .map_err(|error| error.to_string())?;
    }
    Ok(json!({
        "path": path,
        "preview": preview,
        "changed": changed != content,
        "diff": make_simple_diff(&content, &changed),
    }))
}

async fn glob_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let pattern = string_any(&input, &["pattern", "glob"])?;
    let root = runtime.workspace_root().to_path_buf();
    let matches = tokio::task::spawn_blocking(move || glob_matches(&root, &pattern))
        .await
        .map_err(|error| error.to_string())??;
    Ok(json!({ "matches": matches }))
}

fn glob_matches(root: &Path, pattern: &str) -> Result<Vec<String>, String> {
    let pattern = root.join(pattern);
    let pattern = pattern.to_string_lossy().to_string();
    let mut matches = Vec::new();
    for entry in glob::glob(&pattern).map_err(|error| error.to_string())? {
        let path = entry.map_err(|error| error.to_string())?;
        if path.starts_with(root) {
            matches.push(relative_string(root, &path));
        }
    }
    matches.sort();
    Ok(matches)
}

async fn grep_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let pattern = string_any(&input, &["pattern", "query", "regex"])?;
    let regex = Regex::new(&pattern).map_err(|error| error.to_string())?;
    let dir =
        runtime.resolve_dir_path(string_opt(&input, &["path", "directory", "dir"]).as_deref())?;
    let root = runtime.workspace_root().to_path_buf();
    let (matches, truncated) =
        tokio::task::spawn_blocking(move || grep_matches(&root, &dir, &regex))
            .await
            .map_err(|error| error.to_string())?;
    Ok(json!({ "matches": matches, "truncated": truncated }))
}

fn grep_matches(root: &Path, dir: &Path, regex: &Regex) -> (Vec<Value>, bool) {
    let mut matches = Vec::new();
    for entry in WalkDir::new(dir).into_iter().filter_map(Result::ok) {
        if !entry.file_type().is_file() || is_ignored_path(entry.path()) {
            continue;
        }
        let Ok(text) = std::fs::read_to_string(entry.path()) else {
            continue;
        };
        for (index, line) in text.lines().enumerate() {
            if regex.is_match(line) {
                matches.push(json!({
                    "path": relative_string(root, entry.path()),
                    "line": index + 1,
                    "preview": truncate_text(line, 300),
                }));
            }
            if matches.len() >= 500 {
                return (matches, true);
            }
        }
    }
    (matches, false)
}

async fn list_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let dir =
        runtime.resolve_dir_path(string_opt(&input, &["path", "directory", "dir"]).as_deref())?;
    let recursive = bool_field(&input, "recursive").unwrap_or(false);
    let root = runtime.workspace_root().to_path_buf();
    let entries = if recursive {
        let walk_dir = dir.clone();
        tokio::task::spawn_blocking(move || recursive_entries(&root, &walk_dir))
            .await
            .map_err(|error| error.to_string())??
    } else {
        let mut read_dir = fs::read_dir(&dir)
            .await
            .map_err(|error| error.to_string())?;
        let mut paths = Vec::new();
        while let Some(entry) = read_dir
            .next_entry()
            .await
            .map_err(|error| error.to_string())?
        {
            paths.push(entry.path());
        }
        tokio::task::spawn_blocking(move || path_entries(&root, &paths))
            .await
            .map_err(|error| error.to_string())??
    };
    Ok(json!({ "path": relative_string(runtime.workspace_root(), &dir), "entries": entries }))
}

fn recursive_entries(root: &Path, dir: &Path) -> Result<Vec<Value>, String> {
    let mut entries = Vec::new();
    for entry in WalkDir::new(dir)
        .max_depth(8)
        .into_iter()
        .filter_map(Result::ok)
    {
        if entry.path() == dir || is_ignored_path(entry.path()) {
            continue;
        }
        entries.push(path_entry(root, entry.path())?);
    }
    Ok(entries)
}

fn path_entries(root: &Path, paths: &[PathBuf]) -> Result<Vec<Value>, String> {
    paths.iter().map(|path| path_entry(root, path)).collect()
}

async fn patch_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let patch = string_any(&input, &["patch", "diff"])?;
    let cwd = runtime.resolve_cwd_path(string_opt(&input, &["cwd", "path"]).as_deref())?;
    let output = run_command("patch", &["-p0"], Some(&patch), &cwd, timeout_ms(&input)).await?;
    Ok(command_json(output))
}

async fn export_artifact_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let filename = string_opt(&input, &["filename", "name"])
        .unwrap_or_else(|| format!("artifact-{}.txt", Uuid::new_v4()));
    let safe_name = safe_filename(&filename);
    let artifact_id = string_opt(&input, &["artifact_id", "artifactId"])
        .map(|value| safe_filename(&value))
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| format!("artifact-{}", Uuid::new_v4()));
    let artifact_version_id = format!("artifact-version-{}", Uuid::new_v4());
    let content = string_any(&input, &["content", "data", "text"])?;
    let path = runtime.resolve_write_path(
        &Path::new(".agistack")
            .join("artifacts")
            .join(&artifact_id)
            .join(&artifact_version_id)
            .join(&safe_name)
            .to_string_lossy(),
    )?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .await
            .map_err(|error| error.to_string())?;
    }
    fs::write(&path, content.as_bytes())
        .await
        .map_err(|error| error.to_string())?;
    let relative_path = relative_string(runtime.workspace_root(), &path);
    Ok(json!({
        "artifact_id": artifact_id,
        "artifact_version_id": artifact_version_id,
        "filename": safe_name,
        "path": path,
        "relative_path": relative_path,
        "bytes": content.len(),
        "mime_type": string_opt(&input, &["mime_type", "mimeType"])
            .unwrap_or_else(|| "application/octet-stream".to_string()),
        "status": "ready",
        "sources": input.get("sources").cloned().unwrap_or_else(|| json!([])),
        "checks": input.get("checks").cloned().unwrap_or_else(|| json!([])),
    }))
}

async fn list_artifacts_tool(runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let mut artifacts = Vec::new();
    for entry in WalkDir::new(runtime.artifacts_root())
        .min_depth(3)
        .follow_links(false)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_file())
    {
        let path = entry.path();
        let relative = path
            .strip_prefix(runtime.artifacts_root())
            .map_err(|error| error.to_string())?;
        let mut components = relative.components();
        let artifact_id = components
            .next()
            .and_then(|component| component.as_os_str().to_str())
            .unwrap_or_default();
        let artifact_version_id = components
            .next()
            .and_then(|component| component.as_os_str().to_str())
            .unwrap_or_default();
        let meta = entry.metadata().map_err(|error| error.to_string())?;
        artifacts.push(json!({
            "artifact_id": artifact_id,
            "artifact_version_id": artifact_version_id,
            "filename": entry.file_name().to_string_lossy(),
            "path": path,
            "relative_path": relative_string(runtime.workspace_root(), path),
            "bytes": meta.len(),
        }));
    }
    Ok(json!({ "artifacts": artifacts }))
}

async fn batch_export_artifacts_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let items = input
        .get("artifacts")
        .and_then(Value::as_array)
        .ok_or_else(|| "missing artifacts array".to_string())?;
    let mut exported = Vec::new();
    for item in items {
        exported.push(export_artifact_tool(item.clone(), Arc::clone(&runtime)).await?);
    }
    Ok(json!({ "artifacts": exported }))
}

async fn bash_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let command = string_any(&input, &["command", "cmd"])?;
    let cwd = runtime.resolve_cwd_path(string_opt(&input, &["cwd", "path"]).as_deref())?;
    let output = run_shell(&command, &cwd, timeout_ms(&input)).await?;
    Ok(command_json(output))
}

async fn ast_parse_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let path = input_path(&input)?;
    let absolute = runtime.resolve_existing_path(&path)?;
    let content = fs::read_to_string(&absolute)
        .await
        .map_err(|error| error.to_string())?;
    let symbols = find_symbols_in_text(&content);
    Ok(json!({
        "path": path,
        "language": language_for(&absolute),
        "line_count": content.lines().count(),
        "symbols": symbols,
    }))
}

async fn ast_find_symbols_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let path = input_path(&input)?;
    let absolute = runtime.resolve_existing_path(&path)?;
    let content = fs::read_to_string(&absolute)
        .await
        .map_err(|error| error.to_string())?;
    Ok(json!({ "path": path, "symbols": find_symbols_in_text(&content) }))
}

async fn ast_extract_function_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let path = input_path(&input)?;
    let symbol = string_any(&input, &["symbol", "function", "name"])?;
    let absolute = runtime.resolve_existing_path(&path)?;
    let content = fs::read_to_string(&absolute)
        .await
        .map_err(|error| error.to_string())?;
    let range =
        symbol_range(&content, &symbol).ok_or_else(|| format!("symbol not found: {symbol}"))?;
    let lines: Vec<&str> = content.lines().collect();
    let body = lines[range.0 - 1..range.1].join("\n");
    Ok(
        json!({ "path": path, "symbol": symbol, "start_line": range.0, "end_line": range.1, "content": body }),
    )
}

async fn ast_get_imports_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let path = input_path(&input)?;
    let absolute = runtime.resolve_existing_path(&path)?;
    let content = fs::read_to_string(&absolute)
        .await
        .map_err(|error| error.to_string())?;
    let imports: Vec<Value> = content
        .lines()
        .enumerate()
        .filter_map(|(index, line)| {
            let trimmed = line.trim();
            let is_import = trimmed.starts_with("use ")
                || trimmed.starts_with("mod ")
                || trimmed.starts_with("import ")
                || trimmed.starts_with("from ")
                || trimmed.starts_with("#include")
                || trimmed.starts_with("require(")
                || trimmed.starts_with("const ") && trimmed.contains("require(");
            is_import.then(|| json!({ "line": index + 1, "statement": trimmed }))
        })
        .collect();
    Ok(json!({ "path": path, "imports": imports }))
}

async fn code_index_build_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let dir =
        runtime.resolve_dir_path(string_opt(&input, &["path", "directory", "dir"]).as_deref())?;
    let root = runtime.workspace_root().to_path_buf();
    let (files, symbols) = tokio::task::spawn_blocking(move || build_code_index(&root, &dir))
        .await
        .map_err(|error| error.to_string())?;
    Ok(json!({ "files_indexed": files, "symbols_indexed": symbols.len(), "symbols": symbols }))
}

fn build_code_index(root: &Path, dir: &Path) -> (usize, Vec<Value>) {
    let mut symbols = Vec::new();
    let mut files = 0usize;
    for entry in WalkDir::new(dir)
        .max_depth(12)
        .into_iter()
        .filter_map(Result::ok)
    {
        if !entry.file_type().is_file() || is_ignored_path(entry.path()) {
            continue;
        }
        let Some(language) = language_for(entry.path()) else {
            continue;
        };
        files += 1;
        let Ok(content) = std::fs::read_to_string(entry.path()) else {
            continue;
        };
        for symbol in find_symbols_in_text(&content) {
            symbols.push(json!({
                "file": relative_string(root, entry.path()),
                "language": language,
                "symbol": symbol,
            }));
        }
    }
    (files, symbols)
}

async fn find_definition_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let symbol = string_any(&input, &["symbol", "name"])?;
    let root = runtime.workspace_root().to_path_buf();
    let lookup = symbol.clone();
    let definitions = tokio::task::spawn_blocking(move || find_definitions(&root, &lookup))
        .await
        .map_err(|error| error.to_string())?;
    Ok(json!({ "symbol": symbol, "definitions": definitions }))
}

fn find_definitions(root: &Path, symbol: &str) -> Vec<Value> {
    let mut definitions = Vec::new();
    for source in source_files(root) {
        let Ok(content) = std::fs::read_to_string(&source) else {
            continue;
        };
        for found in find_symbols_in_text(&content) {
            if found.get("name").and_then(Value::as_str) == Some(symbol) {
                definitions.push(json!({
                    "file": relative_string(root, &source),
                    "symbol": found,
                }));
            }
        }
    }
    definitions
}

async fn find_references_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let symbol = string_any(&input, &["symbol", "name"])?;
    grep_tool(
        json!({ "pattern": format!(r"\b{}\b", regex::escape(&symbol)) }),
        runtime,
    )
    .await
}

async fn call_graph_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let symbol = string_any(&input, &["symbol", "name"])?;
    let refs = find_references_tool(json!({ "symbol": symbol }), Arc::clone(&runtime)).await?;
    Ok(json!({ "root": string_any(&input, &["symbol", "name"])?, "references": refs }))
}

async fn dependency_graph_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let dir =
        runtime.resolve_dir_path(string_opt(&input, &["path", "directory", "dir"]).as_deref())?;
    let root = runtime.workspace_root().to_path_buf();
    let graph = tokio::task::spawn_blocking(move || dependency_graph(&root, &dir))
        .await
        .map_err(|error| error.to_string())?;
    Ok(json!({ "dependencies": graph }))
}

fn dependency_graph(root: &Path, dir: &Path) -> BTreeMap<String, Vec<String>> {
    let mut graph = BTreeMap::new();
    for source in source_files(dir) {
        let Ok(content) = std::fs::read_to_string(&source) else {
            continue;
        };
        let deps: Vec<String> = content
            .lines()
            .filter_map(extract_dependency)
            .collect::<BTreeSet<_>>()
            .into_iter()
            .collect();
        if !deps.is_empty() {
            graph.insert(relative_string(root, &source), deps);
        }
    }
    graph
}

async fn edit_by_ast_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let path = input_path(&input)?;
    let symbol = string_any(&input, &["symbol", "function", "name"])?;
    let replacement = string_any(&input, &["replacement", "content", "new_text"])?;
    let absolute = runtime.resolve_existing_path(&path)?;
    let content = fs::read_to_string(&absolute)
        .await
        .map_err(|error| error.to_string())?;
    let range =
        symbol_range(&content, &symbol).ok_or_else(|| format!("symbol not found: {symbol}"))?;
    let mut lines: Vec<String> = content.lines().map(ToString::to_string).collect();
    lines.splice(
        range.0 - 1..range.1,
        replacement.lines().map(ToString::to_string),
    );
    let changed = format!("{}\n", lines.join("\n"));
    fs::write(&absolute, changed.as_bytes())
        .await
        .map_err(|error| error.to_string())?;
    Ok(json!({ "path": path, "symbol": symbol, "start_line": range.0, "end_line": range.1 }))
}

async fn batch_edit_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let edits = input
        .get("edits")
        .and_then(Value::as_array)
        .ok_or_else(|| "missing edits array".to_string())?;
    let mut results = Vec::new();
    for edit in edits {
        let result = edit_tool(edit.clone(), Arc::clone(&runtime), false).await;
        results.push(match result {
            Ok(value) => value,
            Err(error) => json!({ "error": error }),
        });
    }
    Ok(json!({ "results": results }))
}

async fn generate_tests_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let target = string_opt(&input, &["path", "target", "file"]).unwrap_or_else(|| ".".to_string());
    let resolved = runtime.resolve_lexical_path(&target)?;
    let test_name = format!(
        "test_{}",
        resolved
            .file_stem()
            .and_then(|name| name.to_str())
            .unwrap_or("generated")
            .replace('-', "_")
    );
    Ok(json!({
        "target": target,
        "suggested_test_name": test_name,
        "content": format!("# Generated test scaffold for {target}\ndef {test_name}():\n    assert True\n"),
    }))
}

async fn run_tests_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let command = string_opt(&input, &["command", "cmd"])
        .unwrap_or_else(|| detect_test_command(runtime.workspace_root()));
    let output = run_shell(&command, runtime.workspace_root(), timeout_ms(&input)).await?;
    Ok(command_json(output))
}

async fn analyze_coverage_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let command = string_opt(&input, &["command", "cmd"]).unwrap_or_else(|| {
        if runtime.workspace_root().join("pyproject.toml").exists() {
            "uv run pytest --cov".to_string()
        } else if runtime.workspace_root().join("Cargo.toml").exists() {
            "cargo test".to_string()
        } else {
            "npm test -- --coverage".to_string()
        }
    });
    let output = run_shell(&command, runtime.workspace_root(), timeout_ms(&input)).await?;
    Ok(command_json(output))
}

async fn git_diff_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let timeout = timeout_ms(&input);
    let stat = run_command(
        "git",
        &["diff", "--no-ext-diff", "--stat", "--"],
        None,
        runtime.workspace_root(),
        timeout,
    )
    .await?;
    let mut diff = run_command(
        "git",
        &["diff", "--no-ext-diff", "--no-color", "--"],
        None,
        runtime.workspace_root(),
        timeout,
    )
    .await?;
    diff.stdout = match (stat.stdout.trim(), diff.stdout.trim()) {
        ("", _) => diff.stdout,
        (_, "") => stat.stdout,
        _ => format!("{}\n{}", stat.stdout.trim_end(), diff.stdout),
    };
    if !stat.stderr.trim().is_empty() {
        if !diff.stderr.is_empty() {
            diff.stderr.push('\n');
        }
        diff.stderr.push_str(stat.stderr.trim_end());
    }
    diff.timed_out |= stat.timed_out;
    if stat.exit_code != Some(0) {
        diff.exit_code = stat.exit_code;
    }
    Ok(command_json(diff))
}

async fn git_log_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let limit = usize_field(&input, "limit").unwrap_or(10).min(100);
    let command = format!("git log --oneline -n {limit}");
    Ok(command_json(
        run_shell(&command, runtime.workspace_root(), timeout_ms(&input)).await?,
    ))
}

async fn generate_commit_tool(
    _input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let diff = run_shell(
        "git diff --stat",
        runtime.workspace_root(),
        DEFAULT_TIMEOUT_MS,
    )
    .await?;
    let summary = if diff.stdout.trim().is_empty() {
        "chore: record local workspace state".to_string()
    } else {
        "feat(desktop): support local runtime execution".to_string()
    };
    Ok(json!({
        "message": summary,
        "body": "Confidence: medium\nScope-risk: moderate\nTested: generated by local tool host\n",
        "diff_stat": diff.stdout,
    }))
}

async fn start_terminal_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let session_id =
        string_opt(&input, &["session_id"]).unwrap_or_else(|| Uuid::new_v4().to_string());
    let cwd = runtime.resolve_cwd_path(string_opt(&input, &["cwd", "path"]).as_deref())?;
    let shell = string_opt(&input, &["shell"]).unwrap_or_else(default_shell);
    let mut sessions = runtime
        .terminals
        .lock()
        .map_err(|error| error.to_string())?;
    sessions.insert(
        session_id.clone(),
        TerminalSession {
            session_id: session_id.clone(),
            cwd,
            shell,
            status: "running".to_string(),
        },
    );
    Ok(json!({ "success": true, "session_id": session_id, "status": "running" }))
}

async fn stop_terminal_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let session_id = string_opt(&input, &["session_id"]).unwrap_or_else(|| "default".to_string());
    let mut sessions = runtime
        .terminals
        .lock()
        .map_err(|error| error.to_string())?;
    if let Some(session) = sessions.get_mut(&session_id) {
        session.status = "stopped".to_string();
    }
    Ok(json!({ "success": true, "session_id": session_id, "status": "stopped" }))
}

async fn get_terminal_status_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let session_id = string_opt(&input, &["session_id"]);
    let sessions = runtime
        .terminals
        .lock()
        .map_err(|error| error.to_string())?;
    if let Some(session_id) = session_id {
        return Ok(json!({ "terminal": sessions.get(&session_id) }));
    }
    Ok(json!({ "terminals": sessions.values().collect::<Vec<_>>() }))
}

async fn restart_terminal_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let session_id =
        string_opt(&input, &["session_id"]).unwrap_or_else(|| Uuid::new_v4().to_string());
    stop_terminal_tool(json!({ "session_id": session_id }), Arc::clone(&runtime)).await?;
    start_terminal_tool(input, runtime).await
}

async fn start_desktop_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let resolution = string_opt(&input, &["resolution"]).unwrap_or_else(|| "1440x900".to_string());
    let mut desktop = runtime.desktop.lock().map_err(|error| error.to_string())?;
    desktop.running = true;
    desktop.resolution = resolution.clone();
    Ok(
        json!({ "success": true, "status": "running", "resolution": resolution, "display": "native" }),
    )
}

async fn stop_desktop_tool(runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let mut desktop = runtime.desktop.lock().map_err(|error| error.to_string())?;
    desktop.running = false;
    Ok(json!({ "success": true, "status": "stopped" }))
}

async fn get_desktop_status_tool(runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let desktop = runtime.desktop.lock().map_err(|error| error.to_string())?;
    Ok(json!({
        "success": true,
        "status": if desktop.running { "running" } else { "stopped" },
        "resolution": desktop.resolution,
        "display": "native",
    }))
}

async fn change_resolution_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let resolution = string_any(&input, &["resolution"])?;
    let mut desktop = runtime.desktop.lock().map_err(|error| error.to_string())?;
    desktop.resolution = resolution.clone();
    Ok(json!({ "success": true, "resolution": resolution }))
}

async fn restart_desktop_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    stop_desktop_tool(Arc::clone(&runtime)).await?;
    start_desktop_tool(input, runtime).await
}

async fn import_file_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let source = string_any(&input, &["source_path", "source", "path"])?;
    let source_path = runtime.resolve_existing_path(&source)?;
    let destination = string_opt(&input, &["destination", "dest_path"]).unwrap_or_else(|| {
        Path::new(&source)
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or("imported-file")
            .to_string()
    });
    let dest = runtime.resolve_write_path(&destination)?;
    fs::copy(&source_path, &dest)
        .await
        .map_err(|error| error.to_string())?;
    Ok(json!({ "source": source, "destination": relative_string(runtime.workspace_root(), &dest) }))
}

async fn import_files_batch_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let files = input
        .get("files")
        .and_then(Value::as_array)
        .ok_or_else(|| "missing files array".to_string())?;
    let mut imported = Vec::new();
    for file in files {
        imported.push(import_file_tool(file.clone(), Arc::clone(&runtime)).await?);
    }
    Ok(json!({ "files": imported }))
}

async fn mcp_server_install_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let name = string_any(&input, &["name", "server"])?;
    let command = string_opt(&input, &["command"]);
    let mut servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    servers.insert(
        name.clone(),
        McpServerRecord {
            name: name.clone(),
            command,
            status: "installed".to_string(),
            log_level: "info".to_string(),
        },
    );
    Ok(json!({ "name": name, "status": "installed" }))
}

async fn mcp_server_start_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let name = string_any(&input, &["name", "server"])?;
    let mut servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    let server = servers
        .entry(name.clone())
        .or_insert_with(|| McpServerRecord {
            name: name.clone(),
            command: string_opt(&input, &["command"]),
            status: "installed".to_string(),
            log_level: "info".to_string(),
        });
    server.status = "running".to_string();
    Ok(json!({ "name": name, "status": "running" }))
}

async fn mcp_server_stop_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let name = string_any(&input, &["name", "server"])?;
    let mut servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    if let Some(server) = servers.get_mut(&name) {
        server.status = "stopped".to_string();
    }
    Ok(json!({ "name": name, "status": "stopped" }))
}

async fn mcp_server_list_tool(runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    Ok(json!({ "servers": servers.values().collect::<Vec<_>>() }))
}

async fn mcp_server_discover_tools_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let name = string_any(&input, &["name", "server"])?;
    let servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    let status = servers
        .get(&name)
        .map(|server| server.status.as_str())
        .unwrap_or("missing");
    Ok(json!({ "name": name, "status": status, "tools": [] }))
}

async fn mcp_server_call_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let name = string_any(&input, &["name", "server"])?;
    let tool = string_any(&input, &["tool", "tool_name"])?;
    let servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    let status = servers
        .get(&name)
        .map(|server| server.status.as_str())
        .unwrap_or("missing");
    Ok(json!({
        "name": name,
        "tool": tool,
        "status": status,
        "content": [],
        "isError": status != "running",
    }))
}

async fn mcp_server_list_prompts_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let name = string_any(&input, &["name", "server"])?;
    let servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    let status = servers
        .get(&name)
        .map(|server| server.status.as_str())
        .unwrap_or("missing");
    Ok(json!({ "name": name, "status": status, "prompts": [] }))
}

async fn mcp_server_set_log_level_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let name = string_any(&input, &["name", "server"])?;
    let level = string_opt(&input, &["level", "log_level"]).unwrap_or_else(|| "info".to_string());
    let mut servers = runtime
        .mcp_servers
        .lock()
        .map_err(|error| error.to_string())?;
    let server = servers
        .entry(name.clone())
        .or_insert_with(|| McpServerRecord {
            name: name.clone(),
            command: None,
            status: "installed".to_string(),
            log_level: "info".to_string(),
        });
    server.log_level = level.clone();
    Ok(json!({ "name": name, "log_level": level }))
}

async fn deps_install_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let command = string_opt(&input, &["command", "cmd"]).unwrap_or_else(|| {
        if runtime.workspace_root().join("Cargo.toml").exists() {
            "cargo fetch".to_string()
        } else if runtime.workspace_root().join("package.json").exists() {
            "pnpm install".to_string()
        } else if runtime.workspace_root().join("pyproject.toml").exists() {
            "uv sync".to_string()
        } else {
            "true".to_string()
        }
    });
    Ok(command_json(
        run_shell(&command, runtime.workspace_root(), timeout_ms(&input)).await?,
    ))
}

async fn deps_check_tool(input: Value, runtime: Arc<LocalToolRuntime>) -> Result<Value, String> {
    let command = string_opt(&input, &["command", "cmd"]).unwrap_or_else(|| {
        if runtime.workspace_root().join("Cargo.toml").exists() {
            "cargo metadata --no-deps --format-version 1".to_string()
        } else if runtime.workspace_root().join("package.json").exists() {
            "pnpm list --depth 0".to_string()
        } else if runtime.workspace_root().join("pyproject.toml").exists() {
            "uv tree --depth 1".to_string()
        } else {
            "true".to_string()
        }
    });
    Ok(command_json(
        run_shell(&command, runtime.workspace_root(), timeout_ms(&input)).await?,
    ))
}

async fn plugin_tool_exec_tool(
    input: Value,
    runtime: Arc<LocalToolRuntime>,
) -> Result<Value, String> {
    let command = string_any(&input, &["command", "cmd"])?;
    Ok(command_json(
        run_shell(&command, runtime.workspace_root(), timeout_ms(&input)).await?,
    ))
}

#[derive(Clone, Debug, Serialize)]
struct TerminalSession {
    session_id: String,
    cwd: PathBuf,
    shell: String,
    status: String,
}

#[derive(Debug)]
struct DesktopState {
    running: bool,
    resolution: String,
}

impl Default for DesktopState {
    fn default() -> Self {
        Self {
            running: false,
            resolution: "1440x900".to_string(),
        }
    }
}

#[derive(Clone, Debug, Serialize)]
struct McpServerRecord {
    name: String,
    command: Option<String>,
    status: String,
    log_level: String,
}

#[derive(Debug)]
struct CommandOutput {
    stdout: String,
    stderr: String,
    exit_code: Option<i32>,
    timed_out: bool,
}

async fn run_shell(command: &str, cwd: &Path, timeout_ms: u64) -> Result<CommandOutput, String> {
    run_command(
        default_shell().as_str(),
        &["-lc", command],
        None,
        cwd,
        timeout_ms,
    )
    .await
}

async fn run_command(
    program: &str,
    args: &[&str],
    stdin: Option<&str>,
    cwd: &Path,
    timeout_ms: u64,
) -> Result<CommandOutput, String> {
    let mut command = Command::new(program);
    #[cfg(unix)]
    command.process_group(0);
    command.args(args);
    command.current_dir(cwd);
    command.stdout(Stdio::piped());
    command.stderr(Stdio::piped());
    if stdin.is_some() {
        command.stdin(Stdio::piped());
    }
    let mut child = command.spawn().map_err(|error| error.to_string())?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "child stdout pipe missing".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "child stderr pipe missing".to_string())?;
    let stdout_task = tokio::spawn(read_capped(stdout));
    let stderr_task = tokio::spawn(read_capped(stderr));
    if let Some(input) = stdin {
        if let Some(mut child_stdin) = child.stdin.take() {
            child_stdin
                .write_all(input.as_bytes())
                .await
                .map_err(|error| error.to_string())?;
        }
    }
    let timeout = Duration::from_millis(timeout_ms.max(1));
    let (exit_code, timed_out) = match time::timeout(timeout, child.wait()).await {
        Ok(status) => (status.map_err(|error| error.to_string())?.code(), false),
        Err(_) => {
            #[cfg(unix)]
            if let Some(pid) = child.id() {
                let _ = std::process::Command::new("/bin/kill")
                    .args(["-KILL", "--", &format!("-{pid}")])
                    .status();
            }
            let _ = child.start_kill();
            child.wait().await.map_err(|error| error.to_string())?;
            (None, true)
        }
    };
    let stdout = stdout_task.await.map_err(|error| error.to_string())??;
    let mut stderr = stderr_task.await.map_err(|error| error.to_string())??;
    if timed_out {
        if !stderr.is_empty() {
            stderr.push('\n');
        }
        stderr.push_str(&format!("command timed out after {timeout_ms}ms"));
    }
    Ok(CommandOutput {
        stdout,
        stderr,
        exit_code,
        timed_out,
    })
}

async fn read_capped(mut reader: impl AsyncRead + Unpin) -> Result<String, String> {
    let mut retained = Vec::with_capacity(MAX_TEXT_BYTES.min(8 * 1024));
    let mut buffer = [0_u8; 8 * 1024];
    loop {
        let size = reader
            .read(&mut buffer)
            .await
            .map_err(|error| error.to_string())?;
        if size == 0 {
            break;
        }
        let remaining = MAX_TEXT_BYTES.saturating_sub(retained.len());
        retained.extend_from_slice(&buffer[..size.min(remaining)]);
    }
    Ok(String::from_utf8_lossy(&retained).to_string())
}

fn command_json(output: CommandOutput) -> Value {
    json!({
        "stdout": output.stdout,
        "stderr": output.stderr,
        "exit_code": output.exit_code,
        "timed_out": output.timed_out,
        "success": output.exit_code == Some(0) && !output.timed_out,
    })
}

fn value_with_elapsed(mut value: Value, started: Instant) -> Value {
    if let Value::Object(map) = &mut value {
        map.insert(
            "elapsed_ms".to_string(),
            json!(started.elapsed().as_millis() as u64),
        );
    }
    value
}

fn mcp_json(value: Value) -> McpToolResult {
    McpToolResult {
        content: vec![McpContent {
            kind: "text".to_string(),
            text: serde_json::to_string_pretty(&value).unwrap_or_else(|_| value.to_string()),
        }],
        is_error: false,
    }
}

fn mcp_error(message: impl Into<String>) -> McpToolResult {
    McpToolResult {
        content: vec![McpContent {
            kind: "text".to_string(),
            text: message.into(),
        }],
        is_error: true,
    }
}

fn input_path(input: &Value) -> Result<String, String> {
    string_any(input, &["path", "file_path", "filename"])
}

fn string_any(input: &Value, keys: &[&str]) -> Result<String, String> {
    string_opt(input, keys).ok_or_else(|| format!("missing {}", keys.join("/")))
}

fn string_opt(input: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        input
            .get(*key)
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToString::to_string)
    })
}

fn array_strings(input: &Value, key: &str) -> Result<Vec<String>, String> {
    let values = input
        .get(key)
        .and_then(Value::as_array)
        .ok_or_else(|| format!("missing {key} array"))?;
    values
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(ToString::to_string)
                .ok_or_else(|| format!("{key} must contain strings"))
        })
        .collect()
}

fn bool_field(input: &Value, key: &str) -> Option<bool> {
    input.get(key).and_then(Value::as_bool)
}

fn usize_field(input: &Value, key: &str) -> Option<usize> {
    input
        .get(key)
        .and_then(Value::as_u64)
        .map(|value| value as usize)
}

fn timeout_ms(input: &Value) -> u64 {
    input
        .get("timeout_ms")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_TIMEOUT_MS)
}

fn path_entry(root: &Path, path: &Path) -> Result<Value, String> {
    let meta = std::fs::metadata(path).map_err(|error| error.to_string())?;
    Ok(json!({
        "path": relative_string(root, path),
        "kind": if meta.is_dir() { "directory" } else { "file" },
        "bytes": if meta.is_file() { Some(meta.len()) } else { None },
    }))
}

fn relative_string(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .to_string()
}

fn truncate_text(text: &str, max: usize) -> String {
    if text.len() <= max {
        return text.to_string();
    }
    let mut end = max;
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}\n[truncated at {max} bytes]", &text[..end])
}

fn slice_chars(text: &str, offset: usize, limit: usize) -> String {
    text.chars().skip(offset).take(limit).collect()
}

fn make_simple_diff(old: &str, new: &str) -> String {
    let old_lines: Vec<&str> = old.lines().collect();
    let new_lines: Vec<&str> = new.lines().collect();
    // Membership sets: the previous per-line `Vec::contains` made this O(n²)
    // in line count (~10^8 string comparisons on a 10k-line file edit).
    let old_set: std::collections::HashSet<&&str> = old_lines.iter().collect();
    let new_set: std::collections::HashSet<&&str> = new_lines.iter().collect();
    let mut diff = String::new();
    for line in old_lines.iter().filter(|line| !new_set.contains(*line)) {
        diff.push_str("- ");
        diff.push_str(line);
        diff.push('\n');
    }
    for line in new_lines.iter().filter(|line| !old_set.contains(*line)) {
        diff.push_str("+ ");
        diff.push_str(line);
        diff.push('\n');
    }
    truncate_text(&diff, MAX_TEXT_BYTES)
}

fn is_ignored_path(path: &Path) -> bool {
    path.components().any(|component| {
        matches!(
            component.as_os_str().to_str(),
            Some(".git" | "target" | "node_modules" | ".venv" | "__pycache__")
        )
    })
}

fn language_for(path: &Path) -> Option<&'static str> {
    match path.extension().and_then(|ext| ext.to_str()) {
        Some("rs") => Some("rust"),
        Some("py") => Some("python"),
        Some("ts") | Some("tsx") => Some("typescript"),
        Some("js") | Some("jsx") => Some("javascript"),
        Some("go") => Some("go"),
        Some("java") => Some("java"),
        Some("c") | Some("h") => Some("c"),
        Some("cc") | Some("cpp") | Some("hpp") => Some("cpp"),
        _ => None,
    }
}

fn source_files(root: &Path) -> Vec<PathBuf> {
    WalkDir::new(root)
        .max_depth(12)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| entry.file_type().is_file())
        .map(|entry| entry.into_path())
        .filter(|path| !is_ignored_path(path) && language_for(path).is_some())
        .collect()
}

fn find_symbols_in_text(content: &str) -> Vec<Value> {
    content
        .lines()
        .enumerate()
        .filter_map(|(index, line)| {
            parse_symbol_line(line).map(|(kind, name)| (index + 1, kind, name))
        })
        .map(|(line, kind, name)| json!({ "name": name, "kind": kind, "line": line }))
        .collect()
}

fn parse_symbol_line(line: &str) -> Option<(&'static str, String)> {
    let trimmed = line.trim_start();
    let candidates = [
        ("pub async fn ", "function"),
        ("pub fn ", "function"),
        ("async fn ", "function"),
        ("fn ", "function"),
        ("def ", "function"),
        ("class ", "class"),
        ("pub struct ", "struct"),
        ("struct ", "struct"),
        ("pub enum ", "enum"),
        ("enum ", "enum"),
        ("function ", "function"),
        ("export function ", "function"),
        ("const ", "constant"),
        ("let ", "variable"),
    ];
    for (prefix, kind) in candidates {
        if let Some(rest) = trimmed.strip_prefix(prefix) {
            let name: String = rest
                .chars()
                .take_while(|ch| ch.is_alphanumeric() || *ch == '_' || *ch == '$')
                .collect();
            if !name.is_empty() {
                return Some((kind, name));
            }
        }
    }
    None
}

fn symbol_range(content: &str, symbol: &str) -> Option<(usize, usize)> {
    let lines: Vec<&str> = content.lines().collect();
    let start = lines.iter().position(|line| {
        parse_symbol_line(line)
            .map(|(_, name)| name == symbol)
            .unwrap_or(false)
    })? + 1;
    let base_indent = lines[start - 1]
        .chars()
        .take_while(|ch| ch.is_whitespace())
        .count();
    let mut end = lines.len();
    for (index, line) in lines.iter().enumerate().skip(start) {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let indent = line.chars().take_while(|ch| ch.is_whitespace()).count();
        if indent <= base_indent && parse_symbol_line(line).is_some() {
            end = index;
            break;
        }
    }
    Some((start, end))
}

fn extract_dependency(line: &str) -> Option<String> {
    let trimmed = line.trim();
    if let Some(rest) = trimmed.strip_prefix("use ") {
        return Some(
            rest.split("::")
                .next()?
                .trim()
                .trim_end_matches(';')
                .to_string(),
        );
    }
    if let Some(rest) = trimmed.strip_prefix("import ") {
        return Some(rest.trim().trim_end_matches(';').to_string());
    }
    if let Some(rest) = trimmed.strip_prefix("from ") {
        return Some(rest.split_whitespace().next()?.to_string());
    }
    None
}

fn detect_test_command(root: &Path) -> String {
    if root.join("Cargo.toml").exists() {
        "cargo test".to_string()
    } else if root.join("package.json").exists() {
        "pnpm test".to_string()
    } else if root.join("pyproject.toml").exists() {
        "uv run pytest".to_string()
    } else {
        "true".to_string()
    }
}

fn default_shell() -> String {
    std::env::var("SHELL").unwrap_or_else(|_| "/bin/sh".to_string())
}

fn safe_filename(name: &str) -> String {
    name.chars()
        .map(|ch| {
            if ch.is_alphanumeric() || matches!(ch, '.' | '-' | '_') {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

fn to_tool<E: std::fmt::Display>(error: E) -> CoreError {
    CoreError::Tool(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_root() -> PathBuf {
        std::env::temp_dir().join(format!("agistack-local-tools-{}", Uuid::new_v4()))
    }

    #[tokio::test]
    async fn tool_registry_matches_python_names_without_extras() {
        let host = LocalToolHost::new(temp_root()).expect("host");
        let agent_tools = host.list_tools();
        assert!(!agent_tools
            .iter()
            .any(|name| name.starts_with("mcp_server_")));
        assert!(!agent_tools.iter().any(|name| name == "plugin_tool_exec"));
        assert_eq!(host.list_tool_metadata().len(), 52);
        assert_eq!(
            host.mcp_tools_list_result()["tools"]
                .as_array()
                .unwrap()
                .len(),
            52
        );
    }

    #[tokio::test]
    async fn agent_tool_host_rejects_internal_management_calls() {
        let host = LocalToolHost::new(temp_root()).expect("host");
        for tool in [
            "mcp_server_list",
            "mcp_server_set_log_level",
            "plugin_tool_exec",
        ] {
            let error = host
                .call(tool, "{}")
                .await
                .expect_err("internal tool rejected");
            assert!(error.to_string().contains("not available to local agents"));
        }
    }

    #[tokio::test]
    async fn read_write_round_trip_returns_mcp_content_shape() {
        let root = temp_root();
        let host = LocalToolHost::new(&root).expect("host");
        let output = host
            .call(
                "write",
                r#"{"path":"notes/todo.txt","content":"ship local"}"#,
            )
            .await
            .expect("write");
        assert!(output.contains("\"isError\":false"));

        let output = host
            .call("read", r#"{"path":"notes/todo.txt"}"#)
            .await
            .expect("read");
        assert!(output.contains("ship local"));
    }

    #[tokio::test]
    async fn path_escape_is_rejected() {
        let host = LocalToolHost::new(temp_root()).expect("host");
        let error = host
            .call("write", r#"{"path":"../outside.txt","content":"bad"}"#)
            .await
            .expect_err("escape rejected");
        assert!(error.to_string().contains("path escape rejected"));
    }

    #[tokio::test]
    async fn bash_runs_inside_workspace() {
        let host = LocalToolHost::new(temp_root()).expect("host");
        let output = host
            .call(
                "bash",
                r#"{"command":"pwd && printf ok","timeout_ms":5000}"#,
            )
            .await
            .expect("bash");
        assert!(output.contains("ok"));
    }

    #[tokio::test]
    async fn git_diff_rejects_shell_injection_by_ignoring_free_form_arguments() {
        let root = temp_root();
        std::fs::create_dir_all(&root).expect("workspace");
        let git = |args: &[&str]| {
            let output = std::process::Command::new("git")
                .arg("-C")
                .arg(&root)
                .args(args)
                .output()
                .expect("git command");
            assert!(output.status.success());
        };
        git(&["init"]);
        git(&["config", "user.email", "test@agistack.local"]);
        git(&["config", "user.name", "Agistack Test"]);
        std::fs::write(root.join("tracked.txt"), "before\n").expect("tracked file");
        git(&["add", "tracked.txt"]);
        git(&["commit", "-m", "base"]);
        std::fs::write(root.join("tracked.txt"), "after\n").expect("changed file");
        let host = LocalToolHost::new(&root).expect("host");

        let output = host
            .call(
                "git_diff",
                r#"{"args":"--stat; touch injected-by-git-diff"}"#,
            )
            .await
            .expect("safe git diff");

        assert!(output.contains("tracked.txt"));
        assert!(!root.join("injected-by-git-diff").exists());
        std::fs::remove_dir_all(root).expect("remove workspace");
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn write_rejects_symlink_target_even_when_parent_is_inside_workspace() {
        use std::os::unix::fs::symlink;

        let root = temp_root();
        let outside = temp_root().join("outside.txt");
        std::fs::create_dir_all(&root).expect("workspace");
        std::fs::create_dir_all(outside.parent().expect("outside parent"))
            .expect("outside directory");
        std::fs::write(&outside, "protected").expect("outside file");
        symlink(&outside, root.join("link.txt")).expect("symlink");
        let host = LocalToolHost::new(&root).expect("host");

        let error = host
            .call("write", r#"{"path":"link.txt","content":"overwrite"}"#)
            .await
            .expect_err("symlink write rejected");

        assert!(error.to_string().contains("symlink path rejected"));
        assert_eq!(
            std::fs::read_to_string(outside).expect("outside content"),
            "protected"
        );
    }

    #[tokio::test]
    async fn import_rejects_source_outside_workspace() {
        let root = temp_root();
        let outside = temp_root().join("outside.txt");
        std::fs::create_dir_all(&root).expect("workspace");
        std::fs::create_dir_all(outside.parent().expect("outside parent"))
            .expect("outside directory");
        std::fs::write(&outside, "secret").expect("outside file");
        let host = LocalToolHost::new(&root).expect("host");

        let error = host
            .call(
                "import_file",
                &json!({ "source_path": outside, "destination": "imported.txt" }).to_string(),
            )
            .await
            .expect_err("external import rejected");

        assert!(error.to_string().contains("path escape rejected"));
        assert!(!root.join("imported.txt").exists());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn artifact_export_rejects_symlink_target() {
        use std::os::unix::fs::symlink;

        let root = temp_root();
        let outside = temp_root().join("outside");
        std::fs::create_dir_all(&root).expect("workspace");
        std::fs::create_dir_all(&outside).expect("outside directory");
        let protected = outside.join("report.txt");
        std::fs::write(&protected, "protected").expect("outside file");
        let host = LocalToolHost::new(&root).expect("host");
        symlink(&outside, host.runtime().artifacts_root().join("report")).expect("symlink");

        let error = host
            .call(
                "export_artifact",
                r#"{"artifact_id":"report","filename":"report.txt","content":"overwrite"}"#,
            )
            .await
            .expect_err("symlink artifact rejected");

        assert!(error.to_string().contains("symlink path rejected"));
        assert_eq!(
            std::fs::read_to_string(protected).expect("outside content"),
            "protected"
        );
    }

    #[tokio::test]
    async fn artifact_export_creates_immutable_versions_for_one_artifact() {
        let root = temp_root();
        std::fs::create_dir_all(&root).expect("workspace");
        let host = LocalToolHost::new(&root).expect("host");

        let first = host
            .mcp_tools_call_result(
                "export_artifact",
                json!({
                    "artifact_id": "release-notes",
                    "filename": "release-notes.md",
                    "content": "version one",
                    "sources": [{ "kind": "file", "id": "README.md", "label": "README" }],
                    "checks": [{ "kind": "test", "id": "docs-lint", "status": "passed" }]
                }),
            )
            .await;
        assert!(!first.is_error);
        let first_value: Value =
            serde_json::from_str(&first.content[0].text).expect("first artifact value");

        let second = host
            .mcp_tools_call_result(
                "export_artifact",
                json!({
                    "artifact_id": "release-notes",
                    "filename": "release-notes.md",
                    "content": "version two"
                }),
            )
            .await;
        assert!(!second.is_error);
        let second_value: Value =
            serde_json::from_str(&second.content[0].text).expect("second artifact value");

        assert_eq!(first_value["artifact_id"], "release-notes");
        assert_eq!(second_value["artifact_id"], "release-notes");
        assert_ne!(
            first_value["artifact_version_id"],
            second_value["artifact_version_id"]
        );
        assert_ne!(first_value["path"], second_value["path"]);
        assert_eq!(first_value["status"], "ready");
        assert_eq!(first_value["sources"].as_array().map(Vec::len), Some(1));
        assert_eq!(first_value["checks"].as_array().map(Vec::len), Some(1));

        let first_path = PathBuf::from(first_value["path"].as_str().expect("first path"));
        let second_path = PathBuf::from(second_value["path"].as_str().expect("second path"));
        assert_eq!(
            std::fs::read_to_string(first_path).expect("first content"),
            "version one"
        );
        assert_eq!(
            std::fs::read_to_string(second_path).expect("second content"),
            "version two"
        );
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn timed_out_command_is_killed_and_reaped() {
        let root = temp_root();
        std::fs::create_dir_all(&root).expect("workspace");
        let pid_file = root.join("child.pid");
        let command = format!("printf '%s' $$ > '{}'; sleep 30", pid_file.display());

        let output = run_command("/bin/sh", &["-c", &command], None, &root, 50)
            .await
            .expect("timeout result");
        assert!(output.timed_out);

        let pid = std::fs::read_to_string(pid_file).expect("pid");
        let alive = std::process::Command::new("kill")
            .args(["-0", pid.trim()])
            .stderr(Stdio::null())
            .status()
            .expect("kill probe")
            .success();
        assert!(!alive, "timed-out shell process must be reaped");
    }
}
