/**
 * Shared unsaved-changes registry.
 *
 * Pages with dirty form state register here so surrounding navigation chrome
 * (tab bars, back buttons rendered by a parent layout) can warn before an
 * in-app route change would silently discard edits. Full page unloads are
 * still covered by each page's own `beforeunload` handler.
 */

let unsavedChanges = false;

export const setUnsavedChanges = (value: boolean): void => {
  unsavedChanges = value;
};

export const hasUnsavedChanges = (): boolean => unsavedChanges;
