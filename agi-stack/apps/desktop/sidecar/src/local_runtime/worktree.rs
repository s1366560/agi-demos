use std::{
    path::{Path, PathBuf},
    process::Command,
};

use super::authority_store::{DesktopExecutionEnvironment, DesktopExecutionEnvironmentKind};

pub(super) struct PreparedExecutionEnvironment {
    pub environment: DesktopExecutionEnvironment,
    pub created_worktree: bool,
}

pub(super) struct WorktreeManager {
    workspace_root: PathBuf,
}

impl WorktreeManager {
    pub(super) fn new(workspace_root: impl Into<PathBuf>) -> Self {
        Self {
            workspace_root: workspace_root.into(),
        }
    }

    pub(super) fn prepare(
        &self,
        kind: DesktopExecutionEnvironmentKind,
        environment_id: &str,
        now: &str,
    ) -> Result<PreparedExecutionEnvironment, String> {
        match kind {
            DesktopExecutionEnvironmentKind::Local => self.prepare_local(environment_id, now),
            DesktopExecutionEnvironmentKind::Worktree => {
                self.prepare_worktree(environment_id, None, None, now)
            }
        }
    }

    pub(super) fn prepare_recovery_fork(
        &self,
        source: &DesktopExecutionEnvironment,
        source_run_id: &str,
        environment_id: &str,
        now: &str,
    ) -> Result<PreparedExecutionEnvironment, String> {
        let source_path = PathBuf::from(&source.workspace_path);
        self.validate(source)?;
        let source_head = git_stdout(&source_path, &["rev-parse", "HEAD"])?;
        self.prepare_worktree(
            environment_id,
            Some(source_head.trim()),
            Some(source_run_id),
            now,
        )
    }

    pub(super) fn validate(&self, environment: &DesktopExecutionEnvironment) -> Result<(), String> {
        let workspace_path = PathBuf::from(&environment.workspace_path);
        if !workspace_path.is_dir() {
            return Err("execution environment workspace is unavailable".to_string());
        }
        if environment.kind == DesktopExecutionEnvironmentKind::Worktree {
            let detected_root = PathBuf::from(git_stdout(
                &workspace_path,
                &["rev-parse", "--show-toplevel"],
            )?);
            let expected = workspace_path
                .canonicalize()
                .map_err(|error| error.to_string())?;
            let detected = detected_root
                .canonicalize()
                .map_err(|error| error.to_string())?;
            if detected != expected {
                return Err(
                    "execution worktree identity does not match its persisted path".to_string(),
                );
            }
        }
        Ok(())
    }

    pub(super) fn cleanup(&self, environment: &DesktopExecutionEnvironment) {
        let _ = self.cleanup_checked(environment);
    }

    pub(super) fn cleanup_checked(
        &self,
        environment: &DesktopExecutionEnvironment,
    ) -> Result<(), String> {
        if environment.kind != DesktopExecutionEnvironmentKind::Worktree {
            return Ok(());
        }
        let Some(repository_root) = environment.repository_root.as_deref() else {
            return Err("execution worktree repository root is missing".to_string());
        };
        let Some(branch) = environment.branch.as_deref() else {
            return Err("execution worktree branch is missing".to_string());
        };
        let repository_root = Path::new(repository_root);
        git_command(
            repository_root,
            &["worktree", "remove", "--force", &environment.workspace_path],
        )?;
        git_command(repository_root, &["branch", "-D", branch])?;
        Ok(())
    }

    fn prepare_local(
        &self,
        environment_id: &str,
        now: &str,
    ) -> Result<PreparedExecutionEnvironment, String> {
        let workspace_root = self
            .workspace_root
            .canonicalize()
            .map_err(|error| error.to_string())?;
        let repository_root = git_stdout(&workspace_root, &["rev-parse", "--show-toplevel"])
            .ok()
            .map(|value| value.trim().to_string());
        let branch = git_stdout(&workspace_root, &["branch", "--show-current"])
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        let base_commit = git_stdout(&workspace_root, &["rev-parse", "HEAD"])
            .ok()
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty());
        Ok(PreparedExecutionEnvironment {
            environment: DesktopExecutionEnvironment {
                id: environment_id.to_string(),
                kind: DesktopExecutionEnvironmentKind::Local,
                label: "Local workspace".to_string(),
                workspace_path: path_string(&workspace_root)?,
                repository_root,
                branch,
                base_commit,
                source_run_id: None,
                created_at: now.to_string(),
            },
            created_worktree: false,
        })
    }

    fn prepare_worktree(
        &self,
        environment_id: &str,
        start_ref: Option<&str>,
        source_run_id: Option<&str>,
        now: &str,
    ) -> Result<PreparedExecutionEnvironment, String> {
        let workspace_root = self
            .workspace_root
            .canonicalize()
            .map_err(|error| error.to_string())?;
        let repository_root = PathBuf::from(git_stdout(
            &workspace_root,
            &["rev-parse", "--show-toplevel"],
        )?);
        let repository_root = repository_root
            .canonicalize()
            .map_err(|error| error.to_string())?;
        let repository_name = repository_root
            .file_name()
            .and_then(|value| value.to_str())
            .filter(|value| !value.is_empty())
            .unwrap_or("repository");
        let worktrees_root = repository_root
            .parent()
            .unwrap_or(&repository_root)
            .join(".agistack-worktrees")
            .join(repository_name);
        std::fs::create_dir_all(&worktrees_root).map_err(|error| error.to_string())?;
        let workspace_path = worktrees_root.join(environment_id);
        if workspace_path.exists() {
            return Err("execution worktree path already exists".to_string());
        }
        let branch = format!("agistack/{environment_id}");
        let start_ref = start_ref.unwrap_or("HEAD");
        let base_commit = git_stdout(&repository_root, &["rev-parse", start_ref])?;
        let workspace_path_value = path_string(&workspace_path)?;
        git_command(
            &repository_root,
            &[
                "worktree",
                "add",
                "-b",
                &branch,
                &workspace_path_value,
                start_ref,
            ],
        )?;
        Ok(PreparedExecutionEnvironment {
            environment: DesktopExecutionEnvironment {
                id: environment_id.to_string(),
                kind: DesktopExecutionEnvironmentKind::Worktree,
                label: format!("Worktree · {branch}"),
                workspace_path: workspace_path_value,
                repository_root: Some(path_string(&repository_root)?),
                branch: Some(branch),
                base_commit: Some(base_commit),
                source_run_id: source_run_id.map(ToString::to_string),
                created_at: now.to_string(),
            },
            created_worktree: true,
        })
    }
}

fn git_stdout(cwd: &Path, args: &[&str]) -> Result<String, String> {
    let output = git_command(cwd, args)?;
    String::from_utf8(output.stdout)
        .map(|value| value.trim().to_string())
        .map_err(|error| error.to_string())
}

fn git_command(cwd: &Path, args: &[&str]) -> Result<std::process::Output, String> {
    let output = Command::new("git")
        .arg("-C")
        .arg(cwd)
        .args(args)
        .output()
        .map_err(|error| error.to_string())?;
    if output.status.success() {
        return Ok(output);
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    Err(if stderr.is_empty() {
        format!("git command failed with status {}", output.status)
    } else {
        stderr
    })
}

fn path_string(path: &Path) -> Result<String, String> {
    path.to_str()
        .map(ToString::to_string)
        .ok_or_else(|| "execution environment path is not valid UTF-8".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    #[test]
    fn worktree_environment_is_isolated_and_recovery_forks_from_the_same_head() {
        let root = std::env::temp_dir().join(format!("agistack-worktree-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&root).expect("create repository");
        git_command(&root, &["init"]).expect("git init");
        git_command(
            &root,
            &["config", "user.email", "desktop-tests@example.invalid"],
        )
        .expect("configure email");
        git_command(&root, &["config", "user.name", "Desktop Tests"]).expect("configure name");
        std::fs::write(root.join("README.md"), "initial\n").expect("write fixture");
        git_command(&root, &["add", "README.md"]).expect("git add");
        git_command(&root, &["commit", "-m", "test fixture"]).expect("git commit");

        let manager = WorktreeManager::new(&root);
        let first = manager
            .prepare(
                DesktopExecutionEnvironmentKind::Worktree,
                "environment-one",
                "2026-07-13T00:00:00Z",
            )
            .expect("prepare worktree");
        assert!(first.created_worktree);
        assert_ne!(
            first.environment.workspace_path,
            path_string(&root).unwrap()
        );
        assert_eq!(
            std::fs::read_to_string(Path::new(&first.environment.workspace_path).join("README.md"))
                .unwrap(),
            "initial\n"
        );
        manager
            .validate(&first.environment)
            .expect("validate worktree");

        let forked = manager
            .prepare_recovery_fork(
                &first.environment,
                "run-one",
                "environment-two",
                "2026-07-13T00:01:00Z",
            )
            .expect("fork recovery worktree");
        assert_eq!(forked.environment.source_run_id.as_deref(), Some("run-one"));
        assert_ne!(
            forked.environment.workspace_path,
            first.environment.workspace_path
        );
        manager
            .validate(&forked.environment)
            .expect("validate fork");

        manager
            .cleanup_checked(&forked.environment)
            .expect("clean up recovery worktree");
        manager
            .cleanup_checked(&first.environment)
            .expect("clean up source worktree");
        let worktree_parent = Path::new(&first.environment.workspace_path)
            .parent()
            .expect("worktree parent");
        std::fs::remove_dir_all(worktree_parent).unwrap_or(());
        std::fs::remove_dir_all(root).expect("remove repository");
    }

    #[test]
    fn local_environment_uses_the_configured_workspace_without_creating_a_worktree() {
        let root = std::env::temp_dir().join(format!("agistack-local-env-{}", Uuid::new_v4()));
        std::fs::create_dir_all(&root).expect("create workspace");
        let manager = WorktreeManager::new(&root);
        let prepared = manager
            .prepare(
                DesktopExecutionEnvironmentKind::Local,
                "environment-local",
                "2026-07-13T00:00:00Z",
            )
            .expect("prepare local environment");
        assert!(!prepared.created_worktree);
        assert_eq!(
            prepared.environment.kind,
            DesktopExecutionEnvironmentKind::Local
        );
        assert_eq!(
            prepared.environment.workspace_path,
            path_string(&root.canonicalize().unwrap()).unwrap()
        );
        std::fs::remove_dir_all(root).expect("remove workspace");
    }
}
