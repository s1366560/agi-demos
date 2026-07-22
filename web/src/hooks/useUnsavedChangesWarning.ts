import { useEffect } from 'react';

/**
 * Warns before the page is closed or reloaded while there are unsaved
 * changes. Covers tab close / reload / external navigation; in-app SPA
 * route changes are not interceptable without a data router, so callers
 * should additionally guard their own cancel/back affordances.
 */
export function useUnsavedChangesWarning(isDirty: boolean): void {
  useEffect(() => {
    if (!isDirty) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [isDirty]);
}
