use std::{path::Path, process::Command};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use super::authority_store::{DesktopExecutionEnvironmentKind, DesktopRun};

const MAX_DIFF_BYTES: usize = 1_048_576;
const MAX_UNTRACKED_FILE_BYTES: usize = 65_536;
const MAX_UNTRACKED_LINES: usize = 300;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ChangeSnapshotStatus {
    Ready,
    Unattributed,
    Unavailable,
    Failed,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct ChangeLine {
    pub kind: ChangeLineKind,
    pub old_line: Option<u64>,
    pub new_line: Option<u64>,
    pub text: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum ChangeLineKind {
    Context,
    Addition,
    Deletion,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct ChangeHunk {
    pub header: String,
    pub old_start: u64,
    pub new_start: u64,
    pub lines: Vec<ChangeLine>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct ChangeFile {
    pub path: String,
    pub old_path: Option<String>,
    pub status: String,
    pub additions: u64,
    pub deletions: u64,
    pub binary: bool,
    pub untracked: bool,
    pub patch_digest: String,
    pub hunks: Vec<ChangeHunk>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub(super) struct ChangeSnapshot {
    pub id: String,
    pub run_id: String,
    pub conversation_id: String,
    pub run_revision: u64,
    pub environment_id: Option<String>,
    pub repository_root: Option<String>,
    pub workspace_path: Option<String>,
    pub branch: Option<String>,
    pub base_revision: Option<String>,
    pub head_revision: Option<String>,
    pub status: ChangeSnapshotStatus,
    pub reason: Option<String>,
    pub additions: u64,
    pub deletions: u64,
    pub files_changed: usize,
    pub truncated: bool,
    pub captured_at: String,
    pub files: Vec<ChangeFile>,
}

pub(super) struct GitChangesInspector;

impl GitChangesInspector {
    pub(super) fn inspect(run: &DesktopRun, captured_at: &str) -> ChangeSnapshot {
        let Some(environment) = run.environment.as_ref() else {
            return unavailable_snapshot(run, captured_at, "run_environment_unavailable");
        };
        let Some(repository_root) = environment.repository_root.as_deref() else {
            return unavailable_snapshot(run, captured_at, "repository_unavailable");
        };
        let Some(base_revision) = environment.base_commit.as_deref() else {
            return status_snapshot(
                run,
                captured_at,
                ChangeSnapshotStatus::Unattributed,
                "base_revision_unavailable",
            );
        };
        let workspace_path = Path::new(&environment.workspace_path);
        if !workspace_path.is_dir() {
            return unavailable_snapshot(run, captured_at, "workspace_path_unavailable");
        }
        let detected_root = match git_stdout(workspace_path, &["rev-parse", "--show-toplevel"]) {
            Ok(value) => value,
            Err(_) => return unavailable_snapshot(run, captured_at, "git_repository_unavailable"),
        };
        let detected = match Path::new(detected_root.trim()).canonicalize() {
            Ok(value) => value,
            Err(_) => return unavailable_snapshot(run, captured_at, "repository_path_invalid"),
        };
        let expected = match workspace_path.canonicalize() {
            Ok(value) => value,
            Err(_) => return unavailable_snapshot(run, captured_at, "workspace_path_invalid"),
        };
        if environment.kind == DesktopExecutionEnvironmentKind::Worktree && detected != expected {
            return unavailable_snapshot(run, captured_at, "worktree_identity_mismatch");
        }

        let head_revision = git_stdout(workspace_path, &["rev-parse", "HEAD"])
            .ok()
            .map(|value| value.trim().to_string());
        let diff_output = match git_output(
            workspace_path,
            &[
                "diff",
                "--no-ext-diff",
                "--no-color",
                "--unified=3",
                base_revision,
                "--",
            ],
        ) {
            Ok(value) => value,
            Err(_) => {
                return status_snapshot(
                    run,
                    captured_at,
                    ChangeSnapshotStatus::Failed,
                    "git_diff_failed",
                )
            }
        };
        let truncated = diff_output.len() > MAX_DIFF_BYTES;
        let visible_diff = &diff_output[..diff_output.len().min(MAX_DIFF_BYTES)];
        let diff_text = String::from_utf8_lossy(visible_diff);
        let mut files = parse_unified_diff(&diff_text);

        if let Ok(status) = git_output(
            workspace_path,
            &["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        ) {
            append_untracked_files(workspace_path, &status, &mut files);
        }

        let additions = files.iter().map(|file| file.additions).sum();
        let deletions = files.iter().map(|file| file.deletions).sum();
        let digest = snapshot_digest(
            run,
            environment.id.as_str(),
            base_revision,
            head_revision.as_deref(),
            &diff_output,
            &files,
        );
        ChangeSnapshot {
            id: format!("change-snapshot-{digest}"),
            run_id: run.id.clone(),
            conversation_id: run.conversation_id.clone(),
            run_revision: run.revision,
            environment_id: Some(environment.id.clone()),
            repository_root: Some(repository_root.to_string()),
            workspace_path: Some(environment.workspace_path.clone()),
            branch: environment.branch.clone(),
            base_revision: Some(base_revision.to_string()),
            head_revision,
            status: ChangeSnapshotStatus::Ready,
            reason: None,
            additions,
            deletions,
            files_changed: files.len(),
            truncated,
            captured_at: captured_at.to_string(),
            files,
        }
    }
}

fn unavailable_snapshot(run: &DesktopRun, captured_at: &str, reason: &str) -> ChangeSnapshot {
    status_snapshot(run, captured_at, ChangeSnapshotStatus::Unavailable, reason)
}

fn status_snapshot(
    run: &DesktopRun,
    captured_at: &str,
    status: ChangeSnapshotStatus,
    reason: &str,
) -> ChangeSnapshot {
    let environment = run.environment.as_ref();
    let digest = sha256_hex(format!("{}:{}:{status:?}:{reason}", run.id, run.revision).as_bytes());
    ChangeSnapshot {
        id: format!("change-snapshot-{digest}"),
        run_id: run.id.clone(),
        conversation_id: run.conversation_id.clone(),
        run_revision: run.revision,
        environment_id: environment.map(|value| value.id.clone()),
        repository_root: environment.and_then(|value| value.repository_root.clone()),
        workspace_path: environment.map(|value| value.workspace_path.clone()),
        branch: environment.and_then(|value| value.branch.clone()),
        base_revision: environment.and_then(|value| value.base_commit.clone()),
        head_revision: None,
        status,
        reason: Some(reason.to_string()),
        additions: 0,
        deletions: 0,
        files_changed: 0,
        truncated: false,
        captured_at: captured_at.to_string(),
        files: Vec::new(),
    }
}

fn append_untracked_files(workspace_path: &Path, status: &[u8], files: &mut Vec<ChangeFile>) {
    for record in status
        .split(|byte| *byte == 0)
        .filter(|record| !record.is_empty())
    {
        let Ok(record) = std::str::from_utf8(record) else {
            continue;
        };
        let Some(relative_path) = record.strip_prefix("?? ") else {
            continue;
        };
        if files.iter().any(|file| file.path == relative_path) {
            continue;
        }
        let candidate = workspace_path.join(relative_path);
        let Ok(canonical) = candidate.canonicalize() else {
            continue;
        };
        let Ok(root) = workspace_path.canonicalize() else {
            continue;
        };
        if !canonical.starts_with(&root) || !canonical.is_file() {
            continue;
        }
        let Ok(bytes) = std::fs::read(&canonical) else {
            continue;
        };
        let visible = &bytes[..bytes.len().min(MAX_UNTRACKED_FILE_BYTES)];
        let Ok(content) = std::str::from_utf8(visible) else {
            files.push(ChangeFile {
                path: relative_path.to_string(),
                old_path: None,
                status: "untracked".to_string(),
                additions: 0,
                deletions: 0,
                binary: true,
                untracked: true,
                patch_digest: sha256_hex(&bytes),
                hunks: Vec::new(),
            });
            continue;
        };
        let lines = content
            .lines()
            .take(MAX_UNTRACKED_LINES)
            .enumerate()
            .map(|(index, text)| ChangeLine {
                kind: ChangeLineKind::Addition,
                old_line: None,
                new_line: Some(index as u64 + 1),
                text: text.to_string(),
            })
            .collect::<Vec<_>>();
        let additions = lines.len() as u64;
        files.push(ChangeFile {
            path: relative_path.to_string(),
            old_path: None,
            status: "untracked".to_string(),
            additions,
            deletions: 0,
            binary: false,
            untracked: true,
            patch_digest: sha256_hex(&bytes),
            hunks: if lines.is_empty() {
                Vec::new()
            } else {
                vec![ChangeHunk {
                    header: format!("@@ -0,0 +1,{additions} @@"),
                    old_start: 0,
                    new_start: 1,
                    lines,
                }]
            },
        });
    }
}

fn parse_unified_diff(input: &str) -> Vec<ChangeFile> {
    let mut files = Vec::new();
    let mut file: Option<ChangeFile> = None;
    let mut hunk: Option<ChangeHunk> = None;
    let mut patch = String::new();
    let mut old_line = 0;
    let mut new_line = 0;

    let flush_hunk = |file: &mut Option<ChangeFile>, hunk: &mut Option<ChangeHunk>| {
        if let (Some(file), Some(hunk)) = (file.as_mut(), hunk.take()) {
            file.hunks.push(hunk);
        }
    };
    let flush_file = |files: &mut Vec<ChangeFile>,
                      file: &mut Option<ChangeFile>,
                      hunk: &mut Option<ChangeHunk>,
                      patch: &mut String| {
        flush_hunk(file, hunk);
        if let Some(mut finished) = file.take() {
            finished.patch_digest = sha256_hex(patch.as_bytes());
            files.push(finished);
        }
        patch.clear();
    };

    for line in input.lines() {
        if line.starts_with("diff --git ") {
            flush_file(&mut files, &mut file, &mut hunk, &mut patch);
            let path = line
                .split(" b/")
                .nth(1)
                .map(ToString::to_string)
                .unwrap_or_else(|| "unknown".to_string());
            file = Some(ChangeFile {
                path,
                old_path: None,
                status: "modified".to_string(),
                additions: 0,
                deletions: 0,
                binary: false,
                untracked: false,
                patch_digest: String::new(),
                hunks: Vec::new(),
            });
            patch.push_str(line);
            patch.push('\n');
            continue;
        }
        let Some(current_file) = file.as_mut() else {
            continue;
        };
        patch.push_str(line);
        patch.push('\n');
        if let Some(path) = line.strip_prefix("--- a/") {
            current_file.old_path = Some(path.to_string());
            continue;
        }
        if line == "--- /dev/null" {
            current_file.status = "added".to_string();
            continue;
        }
        if let Some(path) = line.strip_prefix("+++ b/") {
            current_file.path = path.to_string();
            continue;
        }
        if line == "+++ /dev/null" {
            current_file.status = "deleted".to_string();
            continue;
        }
        if line.starts_with("Binary files ") || line.starts_with("GIT binary patch") {
            current_file.binary = true;
            continue;
        }
        if line.starts_with("@@ ") {
            flush_hunk(&mut file, &mut hunk);
            let (old_start, new_start) = parse_hunk_starts(line).unwrap_or((0, 0));
            old_line = old_start;
            new_line = new_start;
            hunk = Some(ChangeHunk {
                header: line.to_string(),
                old_start,
                new_start,
                lines: Vec::new(),
            });
            continue;
        }
        let Some(current_hunk) = hunk.as_mut() else {
            continue;
        };
        if let Some(text) = line.strip_prefix('+') {
            current_file.additions += 1;
            current_hunk.lines.push(ChangeLine {
                kind: ChangeLineKind::Addition,
                old_line: None,
                new_line: Some(new_line),
                text: text.to_string(),
            });
            new_line += 1;
        } else if let Some(text) = line.strip_prefix('-') {
            current_file.deletions += 1;
            current_hunk.lines.push(ChangeLine {
                kind: ChangeLineKind::Deletion,
                old_line: Some(old_line),
                new_line: None,
                text: text.to_string(),
            });
            old_line += 1;
        } else if let Some(text) = line.strip_prefix(' ') {
            current_hunk.lines.push(ChangeLine {
                kind: ChangeLineKind::Context,
                old_line: Some(old_line),
                new_line: Some(new_line),
                text: text.to_string(),
            });
            old_line += 1;
            new_line += 1;
        }
    }
    flush_file(&mut files, &mut file, &mut hunk, &mut patch);
    files
}

fn parse_hunk_starts(header: &str) -> Option<(u64, u64)> {
    let mut parts = header.split_whitespace();
    parts.next()?;
    let old = parts
        .next()?
        .strip_prefix('-')?
        .split(',')
        .next()?
        .parse()
        .ok()?;
    let new = parts
        .next()?
        .strip_prefix('+')?
        .split(',')
        .next()?
        .parse()
        .ok()?;
    Some((old, new))
}

fn snapshot_digest(
    run: &DesktopRun,
    environment_id: &str,
    base_revision: &str,
    head_revision: Option<&str>,
    diff: &[u8],
    files: &[ChangeFile],
) -> String {
    let mut hasher = Sha256::new();
    hasher.update(run.id.as_bytes());
    hasher.update(run.revision.to_le_bytes());
    hasher.update(environment_id.as_bytes());
    hasher.update(base_revision.as_bytes());
    hasher.update(head_revision.unwrap_or_default().as_bytes());
    hasher.update(diff);
    for file in files {
        hasher.update(file.path.as_bytes());
        hasher.update(file.patch_digest.as_bytes());
    }
    lower_hex(&hasher.finalize())
}

fn sha256_hex(bytes: &[u8]) -> String {
    lower_hex(&Sha256::digest(bytes))
}

fn lower_hex(bytes: &[u8]) -> String {
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        use std::fmt::Write as _;
        let _ = write!(encoded, "{byte:02x}");
    }
    encoded
}

fn git_stdout(cwd: &Path, args: &[&str]) -> Result<String, String> {
    String::from_utf8(git_output(cwd, args)?).map_err(|error| error.to_string())
}

fn git_output(cwd: &Path, args: &[&str]) -> Result<Vec<u8>, String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(cwd)
        .args(args)
        .output()
        .map_err(|error| error.to_string())?;
    if output.status.success() {
        return Ok(output.stdout);
    }
    Err("git inspection failed".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::local_runtime::authority_store::{
        DesktopExecutionEnvironment, DesktopPermissionProfile, DesktopRunStatus,
    };
    use serde_json::json;
    use uuid::Uuid;

    #[test]
    fn inspector_projects_tracked_and_untracked_changes_from_the_run_environment() {
        let root = std::env::temp_dir().join(format!("agistack-changes-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&root).expect("create repository");
        git(&root, &["init"]);
        git(&root, &["config", "user.email", "test@agistack.local"]);
        git(&root, &["config", "user.name", "Agistack Test"]);
        std::fs::write(root.join("tracked.txt"), "before\n").expect("write tracked file");
        git(&root, &["add", "tracked.txt"]);
        git(&root, &["commit", "-m", "base"]);
        let base_commit = git_stdout(&root, &["rev-parse", "HEAD"])
            .expect("base commit")
            .trim()
            .to_string();
        std::fs::write(root.join("tracked.txt"), "after\n").expect("modify tracked file");
        std::fs::write(root.join("new.txt"), "new line\n").expect("write untracked file");
        let run = DesktopRun {
            id: "run-changes".to_string(),
            conversation_id: "conversation-changes".to_string(),
            project_id: "project-changes".to_string(),
            plan_version_id: "plan-changes".to_string(),
            idempotency_key: "idempotency-changes".to_string(),
            message_id: "message-changes".to_string(),
            request_message: "Inspect changes".to_string(),
            status: DesktopRunStatus::Running,
            revision: 3,
            created_at: "2026-01-01T00:00:00Z".to_string(),
            updated_at: "2026-01-01T00:00:00Z".to_string(),
            started_at: Some("2026-01-01T00:00:00Z".to_string()),
            completed_at: None,
            last_heartbeat_at: None,
            error: None,
            environment: Some(DesktopExecutionEnvironment {
                id: "environment-changes".to_string(),
                kind: DesktopExecutionEnvironmentKind::Local,
                label: "Test repository".to_string(),
                workspace_path: root.to_string_lossy().into_owned(),
                repository_root: Some(root.to_string_lossy().into_owned()),
                branch: None,
                base_commit: Some(base_commit),
                source_run_id: None,
                created_at: "2026-01-01T00:00:00Z".to_string(),
            }),
            permission_profile: DesktopPermissionProfile::ReadOnly,
            authorization_snapshot: json!({}),
        };

        let snapshot = GitChangesInspector::inspect(&run, "2026-01-01T00:00:01Z");

        assert_eq!(snapshot.status, ChangeSnapshotStatus::Ready);
        assert_eq!(snapshot.files_changed, 2);
        assert!(snapshot
            .files
            .iter()
            .any(|file| file.path == "tracked.txt" && file.deletions == 1 && file.additions == 1));
        assert!(snapshot
            .files
            .iter()
            .any(|file| file.path == "new.txt" && file.untracked && file.additions == 1));
        std::fs::remove_dir_all(root).expect("remove repository");
    }

    fn git(cwd: &Path, args: &[&str]) {
        let output = Command::new("git")
            .arg("-C")
            .arg(cwd)
            .args(args)
            .output()
            .expect("run git");
        assert!(
            output.status.success(),
            "git failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
}
