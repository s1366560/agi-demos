//! The trusted Electron launch handshake selects a process composition once.

use serde::Deserialize;

#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "kebab-case")]
pub(crate) enum SidecarProfile {
    #[default]
    PackageHost,
    Full,
    #[cfg_attr(not(feature = "legacy-business"), serde(skip_deserializing))]
    Compat,
}

impl SidecarProfile {
    pub(crate) fn allows_command(self, command: &str) -> bool {
        self != Self::PackageHost
            || matches!(
                command,
                "local_run_execute"
                    | "local_run_stop"
                    | "local_runtime_status"
                    | "local_runtime_configure"
                    | "device_plugin_manage_v2"
                    | "workspace_core_status"
                    | "retire_local_workspace_history"
                    | "legacy_local_login_purge"
                    | "trusted_session_save"
                    | "trusted_session_load"
                    | "trusted_session_clear"
                    | "oauth_pending_attempt_save"
                    | "oauth_pending_attempt_load"
                    | "oauth_pending_attempt_clear"
                    | "plugin_data_plane_credential_import_v2"
                    | "plugin_data_plane_credential_clear_v2"
                    | "plugin_renderer_data_plane_credential_import_v2"
                    | "plugin_renderer_data_plane_credential_clear_v2"
                    | "platform_plugin_authority_select_v2"
                    | "platform_plugin_renderer_delivery_current_v2"
                    | "platform_plugin_renderer_distribution_current_v2"
                    | "platform_plugin_renderer_receipt_submit_v2"
                    | "platform_plugin_renderer_owner_retire_v2"
            )
    }
}
