/**
 * postMessage protocol between the host and sandboxed plugin slot iframes.
 *
 * Source of truth: `@agistack/plugin-slots` (shared with the desktop
 * renderer); this module stays as the web-side compatibility re-export.
 */

export {
  decodeSlotMessage,
  encodeSlotMessage,
  isGuestMessageForSlot,
  SLOT_MESSAGE_SOURCE,
} from '@agistack/plugin-slots';
export type { SlotGuestMessage, SlotHostMessage } from '@agistack/plugin-slots';
