use super::*;

pub(in super::super) struct GitPublishFixture {
    pub(in super::super) root: PathBuf,
    pub(in super::super) repo: PathBuf,
    pub(in super::super) remote: PathBuf,
    pub(in super::super) commit_ref: String,
}

impl Drop for GitPublishFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

pub(in super::super) struct DroneYamlFixture {
    pub(in super::super) root: PathBuf,
}

impl Drop for DroneYamlFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

pub(in super::super) struct DroneCliFixture {
    pub(in super::super) root: PathBuf,
    pub(in super::super) command: PathBuf,
    pub(in super::super) capture: PathBuf,
}

impl Drop for DroneCliFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

pub(in super::super) fn drone_yaml_fixture(content: &str) -> DroneYamlFixture {
    let root =
        std::env::temp_dir().join(format!("agistack-drone-yaml-test-{}", generate_uuid_v4()));
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(root.join(".drone.yml"), content).unwrap();
    DroneYamlFixture { root }
}

pub(in super::super) fn drone_cli_fixture() -> DroneCliFixture {
    let root = std::env::temp_dir().join(format!("agistack-drone-cli-test-{}", generate_uuid_v4()));
    std::fs::create_dir_all(&root).unwrap();
    let command = root.join("drone");
    let capture = root.join("commands.log");
    let capture_text = capture.to_string_lossy();
    std::fs::write(
        &command,
        format!(
            r#"#!/bin/sh
CAPTURE="{capture_text}"
printf 'server=%s token=%s args=%s\n' "$DRONE_SERVER" "$DRONE_TOKEN" "$*" >> "$CAPTURE"
case "$1 $2" in
  "repo info")
    printf '%s\n' '{{"active":true,"trusted":true}}'
    ;;
  "repo enable")
    printf '%s\n' enabled
    ;;
  "repo update")
    printf '%s\n' updated
    ;;
  "build ls")
    exit 0
    ;;
  "build create")
    printf '%s\n' '{{"number":51,"status":"running"}}'
    ;;
  "build info")
    printf '%s\n' '{{"number":51,"status":"success","link":"http://drone.local/owner/repo/51","stages":[{{"name":"ci","number":1,"steps":[{{"name":"test","number":1,"status":"success","exit_code":0}}]}}]}}'
    ;;
  "log view")
    printf '%s\n' 'cargo test ok'
    ;;
  "build stop")
    printf '%s\n' stopped
    ;;
  *)
    printf 'unexpected drone args: %s\n' "$*" >&2
    exit 64
    ;;
esac
"#
        ),
    )
    .unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = std::fs::metadata(&command).unwrap().permissions();
        permissions.set_mode(0o700);
        std::fs::set_permissions(&command, permissions).unwrap();
    }
    DroneCliFixture {
        root,
        command,
        capture,
    }
}

pub(in super::super) fn git_publish_fixture() -> Option<GitPublishFixture> {
    if std::env::var_os("AGISTACK_RUN_GIT_PUBLISH_TESTS").is_none() {
        eprintln!(
            "[skip] set AGISTACK_RUN_GIT_PUBLISH_TESTS=1 to run subprocess-backed git publish tests"
        );
        return None;
    }
    if !git_available() {
        eprintln!("[skip] git binary is not available");
        return None;
    }
    let root = std::env::temp_dir().join(format!(
        "agistack-drone-publish-test-{}",
        generate_uuid_v4()
    ));
    let repo = root.join("repo");
    let remote = root.join("remote.git");
    std::fs::create_dir_all(&repo).unwrap();
    run_git_ok(&repo, &["init"]);
    run_git_ok(&repo, &["config", "user.email", "agent@example.test"]);
    run_git_ok(&repo, &["config", "user.name", "Agent Test"]);
    std::fs::write(repo.join("README.md"), "hello\n").unwrap();
    run_git_ok(&repo, &["add", "README.md"]);
    run_git_ok(&repo, &["commit", "-m", "initial"]);
    let commit_ref = run_git_ok(&repo, &["rev-parse", "HEAD"]).trim().to_string();
    run_git_ok(&root, &["init", "--bare", remote.to_str().unwrap()]);
    run_git_ok(
        &repo,
        &["remote", "add", "origin", remote.to_str().unwrap()],
    );
    Some(GitPublishFixture {
        root,
        repo,
        remote,
        commit_ref,
    })
}

pub(in super::super) fn git_available() -> bool {
    Command::new("git")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
}

pub(in super::super) fn run_git_ok(cwd: &Path, args: &[&str]) -> String {
    let output = Command::new("git")
        .args(args)
        .current_dir(cwd)
        .output()
        .unwrap_or_else(|err| panic!("git {} failed to start: {err}", args.join(" ")));
    assert!(
        output.status.success(),
        "git {} failed\nstdout:\n{}\nstderr:\n{}",
        args.join(" "),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout).into_owned()
}
