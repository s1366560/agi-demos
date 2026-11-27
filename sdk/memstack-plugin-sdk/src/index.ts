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
  'model.chat.adapt',
  'model.chat.adapt.openai',
  'model.chat.adapt.deepseek',
  'skills.register',
  'subagents.register',
  'ui.slot',
  'ui.media.microphone',
  'storage.read',
  'storage.write',
] as const;

export type PluginPermission = (typeof PERMISSIONS)[number] | `app.${string}.${string}`;

export interface ScanEvidence {
  readonly status: 'unknown' | 'passed' | 'failed';
  readonly reportDigest: string | null;
}

export type { RichPageCallOptions, RichPageContext, RichPageRuntime } from './pageRuntime';
