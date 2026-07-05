pub(in crate::workspace_outbox_worker) const SANDBOX_NATIVE_PROVIDER: &str = "sandbox_native";
pub(in crate::workspace_outbox_worker) const DRONE_PROVIDER: &str = "drone";
pub(in crate::workspace_outbox_worker) const DRONE_SERVER_ENV: &str = "DRONE_SERVER";
pub(in crate::workspace_outbox_worker) const DRONE_SERVER_URL_ENV: &str = "DRONE_SERVER_URL";
pub(in crate::workspace_outbox_worker) const DRONE_TOKEN_ENV: &str = "DRONE_TOKEN";
pub(in crate::workspace_outbox_worker) const DRONE_CLI_JSON_TEMPLATE: &str = "{{ json . }}";
pub(in crate::workspace_outbox_worker) const DRONE_DOCKER_DEPLOY_VALIDATION: &str =
    "explicit_deploy_step_v1";
pub(in crate::workspace_outbox_worker) const DRONE_YAML_PREFLIGHT_VALIDATION: &str =
    "drone_yml_preflight_v1";
pub(in crate::workspace_outbox_worker) const DEFAULT_DRONE_DEPLOY_MODE: &str = "cli";
pub(in crate::workspace_outbox_worker) const DEFAULT_DRONE_DEPLOY_STAGE: &str = "deploy";
pub(in crate::workspace_outbox_worker) const PLANNING_CONTRACT_SOURCE: &str =
    "planner_agent_code_analysis";
pub(in crate::workspace_outbox_worker) const DEFAULT_PIPELINE_TIMEOUT_SECONDS: i32 = 600;
pub(in crate::workspace_outbox_worker) const DEFAULT_PREVIEW_PORT: i32 = 3000;
pub(in crate::workspace_outbox_worker) const PIPELINE_EXIT_MARKER: &str =
    "__MEMSTACK_PIPELINE_EXIT_CODE__=";
