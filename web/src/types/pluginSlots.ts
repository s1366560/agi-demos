/**
 * Frontend plugin slot contract (P3/I3).
 *
 * The source of truth moved to the shared `@agistack/plugin-slots` package
 * (`agi-stack/packages/plugin-slots`) so the desktop renderer consumes the
 * exact same contract; this module stays as the web-side compatibility
 * re-export.
 */

export type {
  PlatformPluginCapability,
  PlatformPluginSnapshotPayload,
  PlatformPluginSnapshotResponse,
  PlatformPluginSnapshotRow,
  UiSlotDefinition,
  UiSlotKind,
} from '@agistack/plugin-slots';
