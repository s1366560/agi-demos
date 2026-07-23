/**
 * AppModal — accessible modal base.
 *
 * Provides:
 *  - Portal render to document.body
 *  - role="dialog" + aria-modal="true" + aria-labelledby (or aria-label)
 *  - Focus trap (enter, cycle, restore previously-focused element on close)
 *  - Escape to close (with dirty-guard)
 *  - Backdrop click to close (with dirty-guard)
 *  - Body scroll lock while open
 *  - overscroll-behavior: contain (via index.css on .app-modal__body)
 *
 * Intent: one canonical overlay primitive for the app. Custom fixed-inset-0
 * modals should migrate to this so every surface inherits correct a11y.
 */
import React, { useCallback, useEffect, useId, useRef } from 'react';

import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

import { X } from 'lucide-react';

import { confirmAction } from '@/utils/confirmAction';

export type AppModalSize = 'sm' | 'md' | 'lg' | 'xl';
export type AppModalPosition = 'center' | 'side';

const SIZE_MAX_WIDTH: Record<AppModalSize, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

export interface AppModalProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  /** If no visible title, supply an accessible name. */
  ariaLabel?: string;
  description?: React.ReactNode;
  size?: AppModalSize;
  /** Center (dialog) or side (right slide-over panel). */
  position?: AppModalPosition;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** Optional action buttons rendered in the header next to the close button. */
  headerActions?: React.ReactNode;
  /** When true (or () => true), Escape + backdrop click prompt confirm. */
  isDirty?: boolean | (() => boolean);
  /** Custom text for the dirty-confirm dialog. */
  dirtyConfirmText?: string;
  /** Hide the default close (X) button. */
  hideCloseButton?: boolean;
  /** Disable backdrop click to close. */
  closeOnBackdrop?: boolean;
  /** Disable Escape key to close (e.g. during async deletion). */
  closeOnEscape?: boolean;
  className?: string;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export const AppModal: React.FC<AppModalProps> = ({
  open,
  onClose,
  title,
  ariaLabel,
  description,
  size = 'md',
  position = 'center',
  children,
  footer,
  headerActions,
  isDirty,
  dirtyConfirmText,
  hideCloseButton = false,
  closeOnBackdrop = true,
  closeOnEscape = true,
  className,
}) => {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<Element | null>(null);
  const titleId = useId();
  const descId = useId();
  const { t } = useTranslation();

  const checkDirty = useCallback((): boolean => {
    if (typeof isDirty === 'function') return isDirty();
    return !!isDirty;
  }, [isDirty]);

  const attemptClose = useCallback(() => {
    if (checkDirty()) {
      const msg =
        dirtyConfirmText ||
        t('common.unsavedChanges', {
          defaultValue: 'You have unsaved changes. Discard them and close?',
        });
      void confirmAction({
        title: msg,
        okText: t('common.discard', { defaultValue: 'Discard' }),
        cancelText: t('common.cancel', { defaultValue: 'Cancel' }),
        danger: true,
      }).then((confirmed) => {
        if (confirmed) onClose();
      });
      return;
    }
    onClose();
  }, [checkDirty, dirtyConfirmText, onClose, t]);

  // Mount/unmount effects: body scroll lock + focus save/restore.
  useEffect(() => {
    if (!open) return;
    previouslyFocused.current = document.activeElement;
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';

    // Focus [autofocus] element, else first focusable that isn't the close
    // button, else the panel itself.
    const panel = panelRef.current;
    if (panel) {
      const auto = panel.querySelector<HTMLElement>('[autofocus]');
      if (auto) {
        auto.focus();
      } else {
        const all = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
        const first = all.find((el) => !el.classList.contains('app-modal__close'));
        (first ?? panel).focus();
      }
    }

    return () => {
      document.body.style.overflow = overflow;
      const prev = previouslyFocused.current;
      if (prev instanceof HTMLElement && typeof prev.focus === 'function') {
        prev.focus();
      }
    };
  }, [open]);

  // Key handling: Escape (with dirty guard) + Tab cycling.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (!closeOnEscape) return;
        // Let an open AntD overlay (Select/DatePicker/Dropdown/...) consume the
        // Escape first so it closes the overlay instead of the whole modal.
        const overlayOpen = document.querySelector(
          '.ant-select-dropdown:not(.ant-select-dropdown-hidden), ' +
            '.ant-picker-dropdown:not(.ant-picker-dropdown-hidden), ' +
            '.ant-dropdown:not(.ant-dropdown-hidden), ' +
            '.ant-cascader-menus, ' +
            '.ant-popover:not(.ant-popover-hidden)'
        );
        if (overlayOpen) return;
        e.stopPropagation();
        attemptClose();
        return;
      }
      if (e.key === 'Tab') {
        const panel = panelRef.current;
        if (!panel) return;
        const nodes = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
          (el) => el.offsetParent !== null || el === document.activeElement
        );
        if (nodes.length === 0) {
          e.preventDefault();
          panel.focus();
          return;
        }
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        const active = document.activeElement as HTMLElement;
        if (e.shiftKey) {
          if (active === first || !panel.contains(active)) {
            e.preventDefault();
            last?.focus();
          }
        } else if (active === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open, attemptClose, closeOnEscape]);

  if (!open) return null;

  const labelledBy = title ? titleId : undefined;
  const accessibleName = !title ? ariaLabel : undefined;
  const isSide = position === 'side';

  return createPortal(
    <div
      className="app-modal fixed inset-0 z-[1000] overflow-y-auto"
      role="presentation"
      onMouseDown={(e) => {
        // Close only on direct backdrop clicks, not content.
        if (closeOnBackdrop && e.target === e.currentTarget) attemptClose();
      }}
    >
      <div
        className="app-modal__backdrop fixed inset-0 bg-[var(--color-overlay-backdrop,#080c12cc)] transition-opacity"
        aria-hidden="true"
      />
      <div
        className={
          isSide
            ? 'app-modal__shell flex min-h-full items-stretch justify-end'
            : 'app-modal__shell flex min-h-full items-center justify-center p-4'
        }
      >
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={labelledBy}
          aria-label={accessibleName}
          aria-describedby={description ? descId : undefined}
          tabIndex={-1}
          className={
            isSide
              ? `app-modal__panel app-modal__panel--side relative flex h-full w-full ${SIZE_MAX_WIDTH[size]} flex-col overflow-hidden border-l border-[var(--color-border,#242d3a)] bg-[var(--color-panel,#0d121a)] text-[var(--color-text,#e7edf6)] shadow-2xl outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary,#38d6ff)] ${className ?? ''}`
              : `app-modal__panel relative w-full ${SIZE_MAX_WIDTH[size]} overflow-hidden rounded-lg border border-[var(--color-border,#242d3a)] bg-[var(--color-panel,#0d121a)] text-[var(--color-text,#e7edf6)] shadow-2xl outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary,#38d6ff)] ${className ?? ''}`
          }
        >
          {(title || !hideCloseButton || headerActions) && (
            <div className="app-modal__header flex shrink-0 items-start justify-between gap-4 border-b border-[var(--color-border,#242d3a)] px-6 py-4">
              <div className="min-w-0">
                {title && (
                  <h2 id={titleId} className="truncate text-lg font-semibold">
                    {title}
                  </h2>
                )}
                {description && (
                  <p id={descId} className="mt-1 text-sm text-[var(--color-muted,#8996a9)]">
                    {description}
                  </p>
                )}
              </div>
              {headerActions && (
                <div className="flex shrink-0 items-center gap-1">{headerActions}</div>
              )}
              {!hideCloseButton && (
                <button
                  type="button"
                  onClick={attemptClose}
                  aria-label={t('common.closeDialog', { defaultValue: 'Close dialog' })}
                  className="app-modal__close -mr-2 -mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-[var(--color-muted,#8996a9)] transition-colors hover:bg-[var(--color-panel-2,#111720)] hover:text-[var(--color-text,#e7edf6)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary,#38d6ff)]"
                >
                  <X size={18} aria-hidden="true" />
                </button>
              )}
            </div>
          )}
          <div
            className={
              isSide
                ? 'app-modal__body flex-1 overflow-y-auto px-6 py-4'
                : 'app-modal__body max-h-[calc(85vh-8rem)] overflow-y-auto px-6 py-4'
            }
          >
            {children}
          </div>
          {footer && (
            <div className="app-modal__footer flex shrink-0 items-center justify-end gap-2 border-t border-[var(--color-border,#242d3a)] px-6 py-3">
              {footer}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
};

export default AppModal;
