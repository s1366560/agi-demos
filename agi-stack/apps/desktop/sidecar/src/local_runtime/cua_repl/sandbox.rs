//! macOS process isolation. No production path falls back to an ordinary Node process.

use std::path::{Path, PathBuf};

use super::super::authority_store::DesktopPermissionProfile;

#[derive(Clone, Debug)]
pub(super) struct Sandbox {
    pub profile: DesktopPermissionProfile,
    pub workspace: PathBuf,
    pub temporary: PathBuf,
    pub runtime: PathBuf,
    pub protected: Vec<PathBuf>,
    /// Running host code is readable, but cannot be replaced through the task workspace.
    pub immutable: Vec<PathBuf>,
    pub module_roots: Vec<PathBuf>,
}

fn literal(path: &Path) -> Result<String, String> {
    let value = path.to_str().ok_or("repl_path_not_utf8")?;
    if !path.is_absolute() || value.chars().any(char::is_control) {
        return Err("repl_path_invalid".into());
    }
    Ok(format!(
        "\"{}\"",
        value.replace('\\', "\\\\").replace('"', "\\\"")
    ))
}

impl Sandbox {
    pub(super) fn policy(&self, executable: &Path) -> Result<String, String> {
        let mut rules = vec![
            "(version 1)".to_string(),
            "(deny default)".into(),
            "(allow file-read-metadata)".into(),
            // dyld needs to open the root directory before resolving the executable.
            "(allow file-read* (literal \"/\") (subpath \"/System\") (subpath \"/usr/lib\") (subpath \"/usr/share\") (subpath \"/Library/Apple\") (subpath \"/dev\"))".into(),
            "(allow sysctl-read)".into(),
            "(allow mach-lookup (global-name \"com.apple.system.logger\"))".into(),
            "(allow process-info* (target self))".into(),
            "(allow signal (target self))".into(),
            format!("(allow process-exec (literal {}))", literal(executable)?),
            format!("(allow file-read* (literal {}))", literal(executable)?),
            "(deny process-fork)".into(),
            format!("(allow file-read* (subpath {}))", literal(&self.runtime)?),
            format!("(allow file-read* (subpath {}))", literal(&self.workspace)?),
            format!("(allow file-read* file-write* (subpath {}))", literal(&self.temporary)?),
        ];
        match self.profile {
            DesktopPermissionProfile::ReadOnly => {}
            DesktopPermissionProfile::WorkspaceWrite => rules.push(format!(
                "(allow file-write* (subpath {}))",
                literal(&self.workspace)?,
            )),
            DesktopPermissionProfile::FullAccess => {
                rules.push("(allow file-read* file-write*)".into());
                rules.push("(allow network-outbound (remote ip))".into());
                rules.push(
                    "(allow network-outbound (literal \"/private/var/run/mDNSResponder\"))".into(),
                );
                rules.push("(deny network-outbound (remote ip \"localhost:*\"))".into());
                // macOS does not consistently match the wildcard remote loopback
                // filter. A loopback connection also selects a loopback source;
                // explicit source rebinding remains denied by network-bind.
                rules.push("(deny network-outbound (local ip \"localhost:*\"))".into());
            }
        }
        for root in &self.module_roots {
            rules.push(format!("(allow file-read* (subpath {}))", literal(root)?));
        }
        // Helper sessions are created after a kernel may have started. Protect
        // their structural directory prefix, not a snapshot of current sessions.
        let system_temporary = std::env::temp_dir()
            .canonicalize()
            .map_err(|_| "repl_system_temporary_unavailable")?;
        for prefix in [
            system_temporary.join("memstack-cua-"),
            PathBuf::from("/private/tmp/agi-cua-lock-"),
        ] {
            let prefix = prefix.to_str().ok_or("repl_path_not_utf8")?;
            let escaped = prefix
                .chars()
                .flat_map(|character| {
                    if ".+*?()|[]{}^$\\".contains(character) {
                        vec!['\\', character]
                    } else {
                        vec![character]
                    }
                })
                .collect::<String>();
            let pattern = format!("^{escaped}[^/]+(/|$)")
                .replace('\\', "\\\\")
                .replace('"', "\\\"");
            rules.push(format!(
                "(deny file-read* file-write* (regex #\"{pattern}\"))"
            ));
        }
        // Rules for private application state take precedence over broad FullAccess rules.
        for path in &self.protected {
            rules.push(format!(
                "(deny file-read* file-write* (subpath {}))",
                literal(path)?
            ));
        }
        for path in &self.immutable {
            rules.push(format!("(deny file-write* (subpath {}))", literal(path)?));
        }
        // Runtime code and executable inodes remain immutable even under FullAccess.
        rules.push(format!(
            "(deny file-write* (subpath {}))",
            literal(&self.runtime)?
        ));
        rules.push(format!(
            "(deny file-write* (literal {}))",
            literal(executable)?
        ));
        Ok(rules.join("\n"))
    }

    pub(super) fn command(&self, executable: &Path) -> Result<tokio::process::Command, String> {
        if !cfg!(target_os = "macos") || !Path::new("/usr/bin/sandbox-exec").is_file() {
            return Err("repl_system_sandbox_unavailable".into());
        }
        let mut command = tokio::process::Command::new("/usr/bin/sandbox-exec");
        command
            .arg("-p")
            .arg(self.policy(executable)?)
            .arg(executable);
        command
            .env_clear()
            .env("HOME", &self.temporary)
            .env("TMPDIR", &self.temporary)
            .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
            .env("LANG", "en_US.UTF-8")
            .current_dir(&self.workspace)
            .kill_on_drop(true);
        Ok(command)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sandbox(profile: DesktopPermissionProfile) -> Sandbox {
        Sandbox {
            profile,
            workspace: "/owned/workspace".into(),
            temporary: "/owned/tmp".into(),
            runtime: "/owned/runtime".into(),
            protected: vec!["/owned/vault".into()],
            immutable: vec!["/owned/host".into()],
            module_roots: vec![],
        }
    }

    #[test]
    fn policy_paths_are_quoted_and_control_characters_are_rejected() {
        assert_eq!(
            literal(Path::new("/a/\"b\\c")).unwrap(),
            "\"/a/\\\"b\\\\c\""
        );
        assert!(literal(Path::new("/a\n(allow default)")).is_err());
        assert!(literal(Path::new("relative")).is_err());
    }

    #[test]
    fn profiles_keep_private_controls_and_runtime_out_of_writable_scope() {
        for profile in [
            DesktopPermissionProfile::ReadOnly,
            DesktopPermissionProfile::WorkspaceWrite,
            DesktopPermissionProfile::FullAccess,
        ] {
            let policy = sandbox(profile)
                .policy(Path::new("/owned/runtime/node"))
                .unwrap();
            assert!(policy.contains("(deny process-fork)"));
            assert!(policy.contains("(deny file-read* file-write* (subpath \"/owned/vault\"))"));
            assert!(policy.contains("(deny file-write* (subpath \"/owned/runtime\"))"));
            assert!(policy.contains("(deny file-write* (subpath \"/owned/host\"))"));
            assert_eq!(
                policy.contains("(allow network-outbound"),
                profile == DesktopPermissionProfile::FullAccess
            );
            assert_eq!(
                policy.contains("(allow file-write* (subpath \"/owned/workspace\"))"),
                profile == DesktopPermissionProfile::WorkspaceWrite
            );
        }
    }

    #[cfg(target_os = "macos")]
    #[tokio::test]
    async fn operating_system_blocks_unmanaged_spawn_and_outside_writes() {
        let root =
            std::env::temp_dir().join(format!("memstack-repl-sandbox-{}", uuid::Uuid::new_v4()));
        tokio::fs::create_dir_all(root.join("workspace"))
            .await
            .unwrap();
        tokio::fs::create_dir_all(root.join("tmp")).await.unwrap();
        let root = root.canonicalize().unwrap();
        let sandbox = Sandbox {
            workspace: root.join("workspace"),
            temporary: root.join("tmp"),
            runtime: "/usr/bin".into(),
            protected: vec![root.join("private")],
            immutable: vec![],
            module_roots: vec![],
            profile: DesktopPermissionProfile::WorkspaceWrite,
        };
        // macOS /bin/sh execs a selected shell; launch the fixed shell executable directly.
        let output = sandbox
            .command(Path::new("/bin/bash"))
            .unwrap()
            .arg("-c")
            .arg("echo owned > allowed; /usr/bin/true; echo blocked > ../outside")
            .output()
            .await
            .unwrap();
        assert!(!output.status.success());
        assert!(
            root.join("workspace/allowed").exists(),
            "sandbox probe failed before allowed write: {:?} {}",
            output.status,
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(
            tokio::fs::read(root.join("workspace/allowed"))
                .await
                .unwrap(),
            b"owned\n"
        );
        assert!(!root.join("outside").exists());
        assert!(String::from_utf8_lossy(&output.stderr).contains("Operation not permitted"));
        tokio::fs::remove_dir_all(root).await.unwrap();
    }
}

#[cfg(all(test, target_os = "macos"))]
#[path = "sandbox_native_tests.rs"]
mod native_tests;
