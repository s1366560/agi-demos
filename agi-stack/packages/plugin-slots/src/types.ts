/**
 * Frontend plugin slot contract (P3), mirroring
 * `src/domain/ports/plugins/ui.py` on the backend.
 */

export type UiSlotKind =
  | 'nav_item'
  | 'settings_page'
  | 'conversation_renderer'
  | 'tool_result_renderer'
  | 'composer_action'
  | 'mcp_canvas'
  | 'session_workspace_surface'
  | 'workspace_collaboration_surface'
  | 'new_thread_composer_surface'
  | 'my_work_queue_surface'
  | 'activity_inbox_surface'
  | 'authenticated_shell_surface'
  | 'session_canvas_surface'
  | 'workbench_surface';

export interface UiSlotDefinition {
  pluginId: string;
  slot: UiSlotKind;
  id: string;
  /** Capability contract id, e.g. `tool-result:memory_search` (renderer key). */
  contract: string;
  moduleRef: string;
  permission: string;
  sandbox: boolean;
}
