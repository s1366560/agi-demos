use super::support_fixtures::workspace_with_metadata;
use super::*;

pub(super) fn workspace_with_drone_pipeline_contract_missing_host_root() -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo",
                "branch": "main"
            }
        }
    }))
}

pub(super) fn workspace_with_drone_pipeline_contract_missing_branch() -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "code_context": {
            "host_code_root": "/tmp/worktree",
            "sandbox_code_root": "/workspace/project"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "provider_config": {
                "drone": {
                    "repo": "owner/repo"
                }
            }
        }
    }))
}

pub(super) fn workspace_with_drone_pipeline_contract_git_publish(
    host_code_root: &Path,
    remote_url: &Path,
) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "code_context": {
            "host_code_root": host_code_root.to_string_lossy().to_string(),
            "sandbox_code_root": "/workspace/project"
        },
        "source_control": {
            "clone_url": remote_url.to_string_lossy().to_string(),
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo"
            }
        }
    }))
}

pub(super) fn workspace_with_drone_api_pipeline_contract(
    server_url: &str,
    token_env: &str,
) -> WorkspaceRecord {
    workspace_with_drone_api_pipeline_contract_with_host_root(server_url, token_env, None)
}

pub(super) fn workspace_with_drone_api_pipeline_contract_with_host_root(
    server_url: &str,
    token_env: &str,
    host_code_root: Option<&Path>,
) -> WorkspaceRecord {
    let mut metadata = json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo",
                "branch": "main",
                "commit": "abc123",
                "server_url": server_url,
                "token_env": token_env,
                "poll_interval_seconds": 1,
                "timeout_seconds": 1,
                "params": {
                    "target": "workspace-ci"
                }
            }
        }
    });
    if let Some(host_code_root) = host_code_root {
        metadata
            .as_object_mut()
            .expect("workspace metadata object")
            .insert(
                "code_context".to_string(),
                json!({
                    "host_code_root": host_code_root.to_string_lossy().to_string(),
                    "sandbox_code_root": "/workspace/project"
                }),
            );
    }
    workspace_with_metadata(metadata)
}

pub(super) fn workspace_with_drone_cli_pipeline_contract(
    server_url: &str,
    token_env: &str,
    command: &Path,
) -> WorkspaceRecord {
    workspace_with_metadata(json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "drone": {
                "repo": "owner/repo",
                "branch": "main",
                "commit": "abc123",
                "server_url": server_url,
                "token_env": token_env,
                "client": "cli",
                "command": command.to_string_lossy().to_string(),
                "poll_interval_seconds": 1,
                "timeout_seconds": 1,
                "params": {
                    "target": "workspace-ci"
                }
            }
        }
    }))
}

pub(super) fn workspace_with_drone_docker_deploy_pipeline_contract(
    server_url: &str,
    token_env: &str,
) -> WorkspaceRecord {
    workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(server_url, token_env, None)
}

pub(super) fn workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(
    server_url: &str,
    token_env: &str,
    host_code_root: Option<&Path>,
) -> WorkspaceRecord {
    let mut metadata = json!({
        "source_control": {
            "default_branch": "main"
        },
        "delivery_cicd": {
            "provider": "drone",
            "auto_deploy": true,
            "contract_source": PLANNING_CONTRACT_SOURCE,
            "deploy": {
                "enabled": true,
                "mode": "docker",
                "stage": "deploy",
                "required": true,
                "target": "production",
                "docker": {
                    "trusted": true,
                    "host_port": 18080,
                    "labels": ["blue", "green"],
                    "deploy_services": [
                        {
                            "service_id": "web",
                            "container_name": "app-web",
                            "image": "registry.local/app-web:abc"
                        }
                    ]
                }
            },
            "drone": {
                "repo": "owner/repo",
                "branch": "main",
                "commit": "abc123",
                "server_url": server_url,
                "token_env": token_env,
                "poll_interval_seconds": 1,
                "timeout_seconds": 1
            }
        }
    });
    if let Some(host_code_root) = host_code_root {
        metadata
            .as_object_mut()
            .expect("workspace metadata object")
            .insert(
                "code_context".to_string(),
                json!({
                    "host_code_root": host_code_root.to_string_lossy().to_string(),
                    "sandbox_code_root": "/workspace/project"
                }),
            );
    }
    workspace_with_metadata(metadata)
}

pub(super) async fn drone_api_mock(
    responses: Vec<(u16, &'static str)>,
) -> (String, Arc<tokio::sync::Mutex<Vec<String>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let captured = Arc::new(tokio::sync::Mutex::new(Vec::<String>::new()));
    let responses = Arc::new(tokio::sync::Mutex::new(VecDeque::from(responses)));
    let captured_sink = captured.clone();
    let response_queue = responses.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                break;
            };
            let mut request = Vec::new();
            loop {
                let mut buffer = vec![0u8; 8192];
                let read = socket.read(&mut buffer).await.unwrap_or(0);
                if read == 0 {
                    break;
                }
                request.extend_from_slice(&buffer[..read]);
                if http_request_complete(&request) {
                    break;
                }
            }
            captured_sink
                .lock()
                .await
                .push(String::from_utf8_lossy(&request).to_string());
            let (status, body) = response_queue
                .lock()
                .await
                .pop_front()
                .unwrap_or((500, r#"{"error":"unexpected request"}"#));
            let reason = if status < 400 { "OK" } else { "ERROR" };
            let response = format!(
                    "HTTP/1.1 {status} {reason}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
            let _ = socket.write_all(response.as_bytes()).await;
            let _ = socket.flush().await;
        }
    });
    (format!("http://{addr}"), captured)
}

pub(super) fn http_request_complete(request: &[u8]) -> bool {
    let Some(header_end) = request.windows(4).position(|window| window == b"\r\n\r\n") else {
        return false;
    };
    let headers = String::from_utf8_lossy(&request[..header_end]).to_ascii_lowercase();
    let content_length = headers
        .lines()
        .find_map(|line| line.strip_prefix("content-length:"))
        .and_then(|value| value.trim().parse::<usize>().ok())
        .unwrap_or(0);
    request.len() >= header_end + 4 + content_length
}

pub(super) struct GitPublishFixture {
    pub(super) root: PathBuf,
    pub(super) repo: PathBuf,
    pub(super) remote: PathBuf,
    pub(super) commit_ref: String,
}

impl Drop for GitPublishFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

pub(super) struct DroneYamlFixture {
    pub(super) root: PathBuf,
}

impl Drop for DroneYamlFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

pub(super) struct DroneCliFixture {
    pub(super) root: PathBuf,
    pub(super) command: PathBuf,
    pub(super) capture: PathBuf,
}

impl Drop for DroneCliFixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

pub(super) fn drone_yaml_fixture(content: &str) -> DroneYamlFixture {
    let root =
        std::env::temp_dir().join(format!("agistack-drone-yaml-test-{}", generate_uuid_v4()));
    std::fs::create_dir_all(&root).unwrap();
    std::fs::write(root.join(".drone.yml"), content).unwrap();
    DroneYamlFixture { root }
}

pub(super) fn drone_cli_fixture() -> DroneCliFixture {
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

pub(super) fn git_publish_fixture() -> Option<GitPublishFixture> {
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

pub(super) fn git_available() -> bool {
    Command::new("git")
        .arg("--version")
        .output()
        .is_ok_and(|output| output.status.success())
}

pub(super) fn run_git_ok(cwd: &Path, args: &[&str]) -> String {
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
