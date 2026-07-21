/**
 * MobileSidebarDrawer - Overlay drawer for conversation sidebar on mobile screens
 *
 * Slides in from the left with a semi-transparent backdrop.
 * Only visible on screens < md (768px).
 */

import { useEffect, useCallback, useRef } from 'react';
import type { FC, ReactNode } from 'react';

import { useTranslation } from 'react-i18next';

interface MobileSidebarDrawerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export const MobileSidebarDrawer: FC<MobileSidebarDrawerProps> = ({ open, onClose, children }) => {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!open) return undefined;
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, handleKeyDown]);

  // Move focus inside the drawer when it opens
  useEffect(() => {
    if (open) {
      panelRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-slate-950/45 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer panel */}
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('agent.mobileSidebar.title', 'Conversation history')}
        tabIndex={-1}
        className="absolute inset-y-0 left-0 w-80 max-w-[85vw] bg-slate-50 dark:bg-slate-900 shadow-lg shadow-slate-950/20 drawer-slide-in overscroll-contain focus:outline-none"
      >
        {children}
      </aside>
    </div>
  );
};

export default MobileSidebarDrawer;
