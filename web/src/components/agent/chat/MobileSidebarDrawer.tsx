/**
 * MobileSidebarDrawer - Overlay drawer for conversation sidebar on mobile screens
 *
 * Slides in from the left with a semi-transparent backdrop.
 * Only visible on screens < md (768px).
 *
 * Enter/exit are transition-based and symmetric: enter runs 300ms on the
 * drawer curve via `starting:` (@starting-style); exit replays the same path
 * in 200ms, so the drawer stays mounted briefly after `open` flips to false.
 * Reduced-motion: opacity-only fade, no translate.
 */

import { useEffect, useCallback, useRef, useState } from 'react';
import type { FC, ReactNode } from 'react';

import { useTranslation } from 'react-i18next';

interface MobileSidebarDrawerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

/** Matches the 200ms exit transition below. */
const EXIT_DURATION_MS = 200;

export const MobileSidebarDrawer: FC<MobileSidebarDrawerProps> = ({ open, onClose, children }) => {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLElement>(null);
  // Keep the drawer mounted for the exit transition after `open` goes false.
  const [rendered, setRendered] = useState(open);
  const [prevOpen, setPrevOpen] = useState(open);

  // Mount synchronously when `open` flips to true (render-phase derived state).
  if (open !== prevOpen) {
    setPrevOpen(open);
    if (open) {
      setRendered(true);
    }
  }

  // Unmount only after the 200ms exit transition has played.
  useEffect(() => {
    if (open || !rendered) return undefined;
    const timer = setTimeout(() => {
      setRendered(false);
    }, EXIT_DURATION_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [open, rendered]);

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

  if (!rendered) return null;

  return (
    <div className="fixed inset-0 z-50 md:hidden">
      {/* Backdrop */}
      <div
        className={`absolute inset-0 bg-slate-950/45 transition-opacity duration-200 starting:opacity-0 ${
          open ? '' : 'opacity-0'
        }`}
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
        className={`absolute inset-y-0 left-0 w-80 max-w-[85vw] bg-slate-50 dark:bg-slate-900 shadow-lg shadow-slate-950/20 overscroll-contain focus:outline-none transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] starting:-translate-x-full starting:opacity-0 motion-reduce:transition-opacity ${
          open
            ? ''
            : '-translate-x-full duration-200 ease-out motion-reduce:translate-x-0 motion-reduce:opacity-0'
        }`}
      >
        {children}
      </aside>
    </div>
  );
};

export default MobileSidebarDrawer;
