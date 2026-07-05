use super::*;

pub(in super::super) fn workspace_with_drone_pipeline_contract_missing_host_root() -> WorkspaceRecord
{
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

pub(in super::super) fn workspace_with_drone_pipeline_contract_missing_branch() -> WorkspaceRecord {
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

pub(in super::super) fn workspace_with_drone_pipeline_contract_git_publish(
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

pub(in super::super) fn workspace_with_drone_api_pipeline_contract(
    server_url: &str,
    token_env: &str,
) -> WorkspaceRecord {
    workspace_with_drone_api_pipeline_contract_with_host_root(server_url, token_env, None)
}

pub(in super::super) fn workspace_with_drone_api_pipeline_contract_with_host_root(
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

pub(in super::super) fn workspace_with_drone_cli_pipeline_contract(
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

pub(in super::super) fn workspace_with_drone_docker_deploy_pipeline_contract(
    server_url: &str,
    token_env: &str,
) -> WorkspaceRecord {
    workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(server_url, token_env, None)
}

pub(in super::super) fn workspace_with_drone_docker_deploy_pipeline_contract_with_host_root(
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
