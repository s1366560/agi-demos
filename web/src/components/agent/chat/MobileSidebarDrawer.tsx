/**
 * MobileSidebarDrawer - Overlay drawer for conversation sidebar on mobile screens
 *
 * Slides in from the left with a semi-transparent backdrop.
 * Only visible on screens < md (768px).
 */

import { useEffect, useCallback } from 'react';
import type { FC, ReactNode } from 'react';

interface MobileSidebarDrawerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export const MobileSidebarDrawer: FC<MobileSidebarDrawerProps> = ({ open, onClose, children }) => {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!open) return undefined;
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer panel */}
      <aside className="absolute inset-y-0 left-0 w-80 max-w-[85vw] bg-white dark:bg-slate-900 shadow-2xl drawer-slide-in">
        {children}
      </aside>
    </div>
  );
};

export default MobileSidebarDrawer;
