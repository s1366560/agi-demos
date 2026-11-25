// Electron Vite replaces this flag in both privileged bundles. Direct module tests
// exercise the historical full client unless they explicitly compile the package profile.
declare const __AGISTACK_FULL_DESKTOP__: boolean;
export const fullDesktop = typeof __AGISTACK_FULL_DESKTOP__ === 'undefined' || __AGISTACK_FULL_DESKTOP__;

declare const __AGISTACK_COMPAT_DESKTOP__: boolean;
export const sidecarRuntimeProfile =
  typeof __AGISTACK_COMPAT_DESKTOP__ !== 'undefined' && __AGISTACK_COMPAT_DESKTOP__
    ? 'compat'
    : fullDesktop ? 'full' : 'package-host';

export const packageCommands = new Set([
  'frontend_ready', 'device_plugin_manage_v2', 'cloud_request', 'cloud_request_cancel',
  'cloud_session_presence', 'cloud_session_projection', 'cloud_auth_password',
  'cloud_auth_force_password_change', 'cloud_auth_device_begin', 'cloud_auth_device_poll',
  'cloud_auth_device_cancel', 'cloud_auth_status', 'cloud_auth_cancel_pending', 'cloud_auth_signout',
  'oauth_list_providers', 'oauth_begin_authorization', 'oauth_restore_authorization',
  'oauth_cancel_authorization', 'open_device_authorization_url', 'local_run_execute',
  'local_run_stop', 'local_runtime_status', 'local_runtime_configure', 'workspace_core_status',
  'package_workspace_choose', 'choose_workspace_directory', 'focus_main_window', 'window_controls',
  'platform_plugin_authority_select_v2', 'platform_plugin_renderer_distribution_current_v2',
  'platform_plugin_renderer_delivery_current_v2', 'platform_plugin_renderer_receipt_submit_v2',
  'platform_plugin_renderer_owner_retire_v2',
]);
