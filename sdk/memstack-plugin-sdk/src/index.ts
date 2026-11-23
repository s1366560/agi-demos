/** In-repo contract. This package is not published to a registry. */

export const CONTRIBUTION_SCHEMA = 'memstack.plugin.contributions/1';
export { SLOT_UI_SCHEMA, parseSlotUi, type SlotUiAction, type SlotUiDocument } from './slotUi';
export const INVOKE_INPUT_OFFSET = 0;
export const INVOKE_OUTPUT_OFFSET = 65536;
export const MAX_INVOKE_OUTPUT_BYTES = 65536;

export const PERMISSIONS = [
  'tools.execute',
  'services.call',
  'services.provide',
  'graph.projection.compute',
  'agent.loop.drive',
  'app.agent.list',
  'app.agent.create',
  'app.agent.history',
  'app.agent.turn',
  'app.agent.cancel',
  'app.automation.playbooks.read',
  'app.workspace.directory.read',
  'app.workspace.detail.read',
  'app.environments.sandbox.read',
  'app.environments.sandbox.prepare',
  'app.environments.terminal.authorize',
  'model.chat.adapt',
  'model.chat.adapt.openai',
  'model.chat.adapt.deepseek',
  'skills.register',
  'ui.slot',
  'storage.read',
  'storage.write',
] as const;

export type PluginPermission = (typeof PERMISSIONS)[number];

export interface ScanEvidence {
  readonly status: 'unknown' | 'passed' | 'failed';
  readonly reportDigest: string | null;
}

export type { RichPageCallOptions, RichPageContext, RichPageRuntime } from './pageRuntime';
