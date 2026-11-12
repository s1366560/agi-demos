use super::super::{authority_store::DesktopPermissionProfile, LocalRuntimeState};
use super::sandbox::Sandbox;
use std::path::{Path, PathBuf};
use std::sync::Arc;

pub(super) struct TemporaryRoot(PathBuf);

impl Drop for TemporaryRoot {
    fn drop(&mut self) {
        // This path was created exclusively by for_run; never scan or reclaim
        // unrelated temporary directories.
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[derive(Clone)]
pub(super) struct RuntimeConfig {
    pub _temporary_owner: Option<Arc<TemporaryRoot>>,
    pub sandbox: Sandbox,
    pub executable: PathBuf,
    pub entrypoint: PathBuf,
    pub artifact_root: PathBuf,
}

impl RuntimeConfig {
    pub(super) fn for_run(
        state: &LocalRuntimeState,
        workspace: &Path,
        profile: DesktopPermissionProfile,
    ) -> Result<Self, String> {
        let host_executable = std::env::current_exe()
            .map_err(|_| "repl_executable_unavailable")?
            .canonicalize()
            .map_err(|_| "repl_executable_unavailable")?;
        let packaged = host_executable
            .parent()
            .ok_or("repl_runtime_unavailable")?
            .join("cua-repl");
        let runtime = if packaged.join("bin/node").is_file() {
            packaged
        } else if cfg!(debug_assertions) {
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../build/cua-repl")
        } else {
            return Err("repl_packaged_runtime_missing".into());
        };
        let runtime = runtime
            .canonicalize()
            .map_err(|_| "repl_runtime_missing_run_desktop_staging")?;
        let executable = runtime
            .join("bin/node")
            .canonicalize()
            .map_err(|_| "repl_node_missing")?;
        let entrypoint = runtime
            .join("src/cli.mjs")
            .canonicalize()
            .map_err(|_| "repl_entrypoint_missing")?;
        let app_data = state
            .app_data_dir
            .as_ref()
            .ok_or("repl_application_storage_required")?
            .canonicalize()
            .map_err(|_| "repl_application_storage_missing")?;
        let temporary =
            std::env::temp_dir().join(format!("memstack-repl-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&temporary).map_err(|_| "repl_temporary_storage_failed")?;
        let temporary_owner = Arc::new(TemporaryRoot(temporary.clone()));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&temporary, std::fs::Permissions::from_mode(0o700))
                .map_err(|_| "repl_temporary_permissions_failed")?;
        }
        let temporary = temporary
            .canonicalize()
            .map_err(|_| "repl_temporary_storage_failed")?;
        let mut immutable = vec![host_executable.clone()];
        if let Some(host_directory) = host_executable.parent() {
            // Native helpers and their signed components live beside the sidecar.
            immutable.push(host_directory.to_path_buf());
        }
        if let Some(bundle) = host_executable
            .ancestors()
            .find(|path| path.extension().is_some_and(|extension| extension == "app"))
        {
            immutable.push(bundle.to_path_buf());
        }
        if cfg!(debug_assertions) {
            // electron-vite reloads these files in development. Task code must not
            // rewrite the process that holds its authorizations and credentials.
            for path in [
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(".."),
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../packages/cua-repl"),
            ] {
                if let Ok(path) = path.canonicalize() {
                    immutable.push(path);
                }
            }
        }
        let mut protected = vec![app_data.clone()];
        if let Ok(registry) = super::super::browser_bridge::registry_path() {
            if let Some(directory) = registry.parent() {
                protected.push(directory.to_path_buf());
                if let Ok(directory) = directory.canonicalize() {
                    protected.push(directory);
                }
            }
        }
        let sandbox = Sandbox {
            profile,
            workspace: workspace
                .canonicalize()
                .map_err(|_| "repl_workspace_missing")?,
            temporary,
            runtime,
            protected,
            immutable,
            module_roots: vec![],
        };
        Ok(Self {
            _temporary_owner: Some(temporary_owner),
            sandbox,
            executable,
            entrypoint,
            artifact_root: app_data.join("cua-repl-artifacts"),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn temporary_root_survives_clones_and_preserves_neighboring_files() {
        let parent =
            std::env::temp_dir().join(format!("memstack-repl-cleanup-{}", uuid::Uuid::new_v4()));
        let owned = parent.join("owned");
        std::fs::create_dir_all(&owned).unwrap();
        std::fs::write(owned.join("scratch"), "scratch").unwrap();
        std::fs::write(parent.join("keep"), "neighbor").unwrap();
        let owner = Arc::new(TemporaryRoot(owned.clone()));
        let child = owner.clone();
        drop(owner);
        assert!(owned.exists());
        drop(child);
        assert!(!owned.exists());
        assert_eq!(
            std::fs::read_to_string(parent.join("keep")).unwrap(),
            "neighbor"
        );
        std::fs::remove_dir_all(parent).unwrap();
    }
}
