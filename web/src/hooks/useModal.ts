/**
 * useModal Hook
 *
 * A generic hook for managing modal state with data.
 * Eliminates the common pattern of multiple useState calls for modal management.
 *
 * @example
 * ```tsx
 * // Without generic - for simple modals
 * const modal = useModal();
 * modal.open();  // Open without data
 * modal.close();
 *
 * // With generic - for modals with data
 * const userModal = useModal<User>();
 * userModal.open({ id: '123', name: 'John' });  // Open with data
 * userModal.close();  // Data is preserved
 * userModal.setData(null);  // Clear data
 * ```
 */

import { useState, useCallback } from 'react';

export interface ModalState<T = unknown> {
  /** Whether the modal is currently open */
  isOpen: boolean;
  /** Data associated with the modal */
  data: T | null;
}

export interface ModalActions<T = unknown> {
  /** Open the modal, optionally setting data */
  open: (data?: T | null) => void;
  /** Close the modal (preserves data) */
  close: () => void;
  /** Toggle modal open state */
  toggle: () => void;
  /** Update the modal data without changing open state */
  setData: (data: T | null) => void;
}

export type UseModalReturn<T = unknown> = ModalState<T> & ModalActions<T>;

/**
 * Hook for managing modal state with optional typed data.
 *
 * @param initialData - Optional initial data for the modal
 * @returns Modal state and actions
 */
export function useModal<T = unknown>(
  initialData: T | null = null
): UseModalReturn<T> {
  const [isOpen, setIsOpen] = useState(false);
  const [data, setData] = useState<T | null>(initialData);

  const open = useCallback((newData?: T | null) => {
    setIsOpen(true);
    if (newData !== undefined) {
      setData(newData);
    }
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
    // Note: we preserve data after close for potential reuse
  }, []);

  const toggle = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  return {
    isOpen,
    data,
    open,
    close,
    toggle,
    setData,
  };
}

export default useModal;
